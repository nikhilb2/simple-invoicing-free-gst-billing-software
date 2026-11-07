"""The "TCS collected" report (#769): TCS on sales invoices, net of credit notes.

Input for Form 143 (Form 27EQ for periods ending on or before 31 March 2026).
"""

import csv
from calendar import monthrange
from collections import defaultdict
from datetime import date, datetime, time
from decimal import Decimal
from io import BytesIO, StringIO

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from src.api.deps import get_active_company, get_current_user
from src.core.validation import pan_from_gstin
from src.db.session import get_db
from src.models.company import CompanyProfile
from src.models.credit_note import CreditNote, CreditNoteItem
from src.models.invoice import Invoice
from src.models.tax_withholding_section import TaxWithholdingSection
from src.models.user import User
from src.schemas.tcs_report import TcsReportOut, TcsReportRow, TcsSectionTotal
from src.services.company_access import company_scope
from src.services.gst_tax_service import india_today, money
from src.services.tcs import DECLARATION_LEGACY_CODES

DECLARATION_REMARK = "Declaration – not collected"
NOT_COLLECTED_REMARK = "Not collected"

router = APIRouter()

FORM_27EQ_LAST_DAY = date(2026, 3, 31)
_ZERO = Decimal("0.00")


def _current_tax_year() -> int:
    today = india_today()
    return today.year if today.month >= 4 else today.year - 1


def _period(tax_year: int, quarter: int | None) -> tuple[date, date]:
    if quarter is None:
        return date(tax_year, 4, 1), date(tax_year + 1, 3, 31)
    first_month = {1: (tax_year, 4), 2: (tax_year, 7), 3: (tax_year, 10), 4: (tax_year + 1, 1)}[quarter]
    year, month = first_month
    end_month = month + 2
    return date(year, month, 1), date(year, end_month, monthrange(year, end_month)[1])


def _dec(value) -> Decimal:
    return Decimal(str(value if value is not None else 0))


def _buyer_pan(invoice: Invoice) -> str | None:
    ledger = invoice.ledger if hasattr(invoice, "ledger") else None
    pan = (getattr(ledger, "pan", None) or "").strip().upper() or None
    return pan or pan_from_gstin(invoice.ledger_gst) or pan_from_gstin(getattr(ledger, "gst", None))


def build_report(db: Session, company: CompanyProfile, tax_year: int | None, quarter: int | None) -> TcsReportOut:
    if tax_year is None:
        tax_year = _current_tax_year()
    from_date, to_date = _period(tax_year, quarter)
    start = datetime.combine(from_date, time.min)
    end = datetime.combine(to_date, time.max)
    company_id = getattr(company, "id", None)

    sections = {s.id: s for s in db.query(TaxWithholdingSection).all()}

    def section_of(invoice: Invoice):
        section = sections.get(invoice.tcs_section_id)
        return (invoice.tcs_section_ref or (section.section_ref if section else None)), (section.nature if section else None)

    rows: list[TcsReportRow] = []
    invoices = (
        db.query(Invoice)
        .filter(
            Invoice.voucher_type == "sales",
            Invoice.status == "active",
            # A sale with a section but no TCS is reported too: Form 27EQ lists
            # non-collection under a s.394(2) declaration (Form 27C) with a remark.
            or_(Invoice.tcs_amount != 0, Invoice.tcs_section_id.isnot(None)),
            Invoice.invoice_date >= start,
            Invoice.invoice_date <= end,
            company_scope(Invoice.company_id, company_id),
        )
        .all()
    )
    def remark_for(invoice: Invoice) -> str | None:
        if _dec(invoice.tcs_amount) != 0:
            return None
        section = sections.get(invoice.tcs_section_id)
        ledger = getattr(invoice, "ledger", None)
        declared = bool(getattr(ledger, "tcs_declaration_received", False))
        if declared and section is not None and section.legacy_code in DECLARATION_LEGACY_CODES:
            return DECLARATION_REMARK
        return NOT_COLLECTED_REMARK

    for invoice in invoices:
        ref, nature = section_of(invoice)
        rows.append(TcsReportRow(
            remark=remark_for(invoice),
            kind="invoice", id=invoice.id, document_number=invoice.invoice_number or f"INV-{invoice.id}",
            date=invoice.invoice_date.date(), buyer_name=invoice.ledger_name, buyer_pan=_buyer_pan(invoice),
            section_ref=ref, nature=nature, base_amount=money(_dec(invoice.tcs_base_amount)),
            rate=_dec(invoice.tcs_rate), tcs_amount=money(_dec(invoice.tcs_amount)),
        ))

    notes = (
        db.query(CreditNote)
        .filter(
            CreditNote.status == "active",
            CreditNote.direction == "outward",
            CreditNote.credit_note_date >= start,
            CreditNote.credit_note_date <= end,
            company_scope(CreditNote.company_id, company_id),
        )
        .all()
    )
    note_ids = [n.id for n in notes]
    reversed_by_note: dict[int, dict[int, Decimal]] = defaultdict(dict)
    if note_ids:
        for note_id, invoice_id, total in (
            db.query(CreditNoteItem.credit_note_id, CreditNoteItem.invoice_id, func.sum(CreditNoteItem.tcs_amount))
            .filter(CreditNoteItem.credit_note_id.in_(note_ids), CreditNoteItem.tcs_amount != 0)
            .group_by(CreditNoteItem.credit_note_id, CreditNoteItem.invoice_id)
            .all()
        ):
            if invoice_id is not None:
                reversed_by_note[note_id][invoice_id] = _dec(total)
    source_ids = {i for per in reversed_by_note.values() for i in per}
    sources = {i.id: i for i in db.query(Invoice).filter(Invoice.id.in_(source_ids)).all()} if source_ids else {}
    for note in notes:
        for invoice_id, note_tcs in reversed_by_note.get(note.id, {}).items():
            source = sources.get(invoice_id)
            if source is None or _dec(source.tcs_amount) == 0:
                continue
            base = money(_dec(source.tcs_base_amount) * note_tcs / _dec(source.tcs_amount))
            ref, nature = section_of(source)
            rows.append(TcsReportRow(
                kind="credit_note", id=note.id, document_number=note.credit_note_number,
                date=note.credit_note_date.date(), invoice_number=source.invoice_number,
                buyer_name=source.ledger_name, buyer_pan=_buyer_pan(source), section_ref=ref, nature=nature,
                base_amount=-base, rate=_dec(source.tcs_rate), tcs_amount=-money(note_tcs),
            ))

    rows.sort(key=lambda r: (r.date, r.document_number, r.kind))

    grouped: dict[tuple, dict] = {}
    for row in rows:
        entry = grouped.setdefault((row.section_ref or "", row.nature or ""), {
            "section_ref": row.section_ref, "nature": row.nature, "count": 0, "base": _ZERO, "tcs": _ZERO,
            "not_collected": _ZERO})
        entry["count"] += 1
        if row.remark:
            entry["not_collected"] += row.base_amount
        else:
            entry["base"] += row.base_amount
        entry["tcs"] += row.tcs_amount
    totals = [
        TcsSectionTotal(section_ref=e["section_ref"], nature=e["nature"], count=e["count"],
                        base_amount=money(e["base"]), tcs_amount=money(e["tcs"]),
                        not_collected_base=money(e["not_collected"]))
        for _, e in sorted(grouped.items())
    ]
    return TcsReportOut(
        tax_year=tax_year, quarter=quarter, from_date=from_date, to_date=to_date,
        return_form="Form 27EQ" if to_date <= FORM_27EQ_LAST_DAY else "Form 143",
        rows=rows, totals_by_section=totals,
        total_base=money(sum((t.base_amount for t in totals), _ZERO)),
        total_tcs=money(sum((t.tcs_amount for t in totals), _ZERO)),
    )


def _csv(report: TcsReportOut) -> bytes:
    out = StringIO()
    writer = csv.writer(out)
    writer.writerow(["Type", "Document", "Date", "Buyer", "Buyer PAN", "Section", "Nature", "Base", "Rate %", "TCS", "Remark"])
    for r in report.rows:
        writer.writerow([
            "Credit note" if r.kind == "credit_note" else "Invoice", r.document_number, r.date.isoformat(),
            r.buyer_name or "", r.buyer_pan or "", r.section_ref or "", r.nature or "",
            f"{r.base_amount:.2f}", f"{r.rate:f}", f"{r.tcs_amount:.2f}", r.remark or "",
        ])
    writer.writerow([])
    writer.writerow(["Totals by section"])
    writer.writerow(["Section", "Nature", "Documents", "Base", "TCS", "Not collected"])
    for t in report.totals_by_section:
        writer.writerow([
            t.section_ref or "", t.nature or "", t.count, f"{t.base_amount:.2f}", f"{t.tcs_amount:.2f}",
            f"{t.not_collected_base:.2f}",
        ])
    writer.writerow(["Grand total", "", "", f"{report.total_base:.2f}", f"{report.total_tcs:.2f}"])
    return out.getvalue().encode("utf-8-sig")


def _validated(tax_year: int | None, quarter: int | None) -> None:
    if quarter is not None and quarter not in (1, 2, 3, 4):
        raise HTTPException(status_code=400, detail="quarter must be 1, 2, 3 or 4")
    if tax_year is not None and not 2000 <= tax_year <= 2100:
        raise HTTPException(status_code=400, detail="tax_year is out of range")


@router.get("", response_model=TcsReportOut, summary="TCS collected")
def tcs_collected(
    tax_year: int | None = Query(None),
    quarter: int | None = Query(None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    active_company: CompanyProfile = Depends(get_active_company),
):
    _validated(tax_year, quarter)
    return build_report(db, active_company, tax_year, quarter)


@router.get("/export-csv", summary="TCS collected CSV")
def tcs_collected_csv(
    tax_year: int | None = Query(None),
    quarter: int | None = Query(None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    active_company: CompanyProfile = Depends(get_active_company),
):
    _validated(tax_year, quarter)
    report = build_report(db, active_company, tax_year, quarter)
    label = f"{report.tax_year}-{str(report.tax_year + 1)[2:]}" + (f"_Q{quarter}" if quarter else "")
    return StreamingResponse(
        BytesIO(_csv(report)),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="tcs_collected_{label}.csv"'},
    )
