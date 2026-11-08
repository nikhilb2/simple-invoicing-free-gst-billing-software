"""TDS on receipts (#768) and on payments to suppliers (#770).

* ``GET /api/tds/suggestion``: the suggested TDS for one invoice and section.
* ``GET /api/tds/receivable`` (+ ``/csv``): TDS customers deducted from us, to
  match against Form 26AS / AIS.
* ``GET /api/tds/payable`` (+ ``/csv``): TDS we deducted from suppliers, the
  input for Form 140 (Form 26Q for periods up to 31 March 2026).
* ``PATCH /api/tds/allocations/{id}``: tick the TDS certificate as received.

A row's quarter is the quarter of its *deduction date*: the earlier of the
invoice date and the payment date (normally the invoice date). That is the
date the deductor reports it under, so the report lines up with Form 26AS.
"""

import csv
from datetime import date, datetime, time
from decimal import Decimal
from typing import Literal
from io import BytesIO, StringIO

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session, joinedload

from src.api.deps import get_active_company, get_current_user, require_company_role
from src.core.validation import pan_from_gstin
from src.db.session import get_db
from src.models.buyer import Buyer
from src.models.company import CompanyProfile
from src.models.invoice import Invoice
from src.models.payment import Payment, PaymentInvoiceAllocation
from src.models.tax_withholding_section import TaxWithholdingSection
from src.models.user import User, UserRole
from src.services.company_access import company_scope
from src.services.gst_tax_service import india_today
from src.services.tds_allocations import (
    deduction_date,
    money,
    quarter_bounds,
    quarter_of,
    suggest_tds_for_invoice,
    tax_year_label,
    tax_year_start,
)

router = APIRouter()


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------

class TdsSuggestionOut(BaseModel):
    invoice_id: int
    section_id: int
    section_ref: str
    act: int
    nature: str
    deduction_date: date
    in_force: bool
    has_pan: bool
    base_amount: float
    rate: float
    amount: float
    applies: bool
    reason: str | None = None
    tax_year_total: float | None = None


class TdsReportRow(BaseModel):
    allocation_id: int
    payment_id: int
    payment_number: str | None = None
    payment_date: datetime
    invoice_id: int
    invoice_number: str | None = None
    supplier_invoice_number: str | None = None
    invoice_date: datetime
    deduction_date: date
    quarter: int
    ledger_id: int | None = None
    party_name: str
    party_pan: str | None = None
    section_id: int | None = None
    section_ref: str | None = None
    rate: float | None = None
    taxable_amount: float
    base_amount: float | None = None
    cash_amount: float
    tds_amount: float
    certificate_received: bool = False


class TdsTotal(BaseModel):
    key: str
    label: str
    pan: str | None = None
    count: int
    base_amount: float
    tds_amount: float


class TdsReportOut(BaseModel):
    kind: str  # "receivable" or "payable"
    tax_year: int
    tax_year_label: str
    quarter: int | None = None
    from_date: date
    to_date: date
    rows: list[TdsReportRow]
    totals_by_section: list[TdsTotal]
    totals_by_party: list[TdsTotal]
    total_tds: float
    total_base: float


class TdsAllocationPatch(BaseModel):
    certificate_received: bool


class TdsAllocationOut(BaseModel):
    allocation_id: int
    certificate_received: bool


# ---------------------------------------------------------------------------
# Suggestion
# ---------------------------------------------------------------------------

@router.get("/suggestion", response_model=TdsSuggestionOut)
def get_tds_suggestion(
    invoice_id: int = Query(...),
    section_id: int = Query(...),
    payment_date: date | None = Query(None),
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
    active_company: CompanyProfile = Depends(get_active_company),
):
    """Suggested TDS for one invoice under one section. Never binding."""
    company_id = getattr(active_company, "id", None)
    query = db.query(Invoice).filter(Invoice.id == invoice_id)
    if company_id is not None:
        query = query.filter(company_scope(Invoice.company_id, company_id))
    invoice = query.first()
    if invoice is None:
        raise HTTPException(status_code=404, detail="Invoice not found")
    section = db.get(TaxWithholdingSection, section_id)
    if section is None or section.kind != "tds":
        raise HTTPException(status_code=404, detail="TDS section not found")
    ledger = db.get(Buyer, invoice.ledger_id) if invoice.ledger_id is not None else None
    return suggest_tds_for_invoice(
        db,
        invoice,
        section,
        ledger=ledger,
        payment_date=payment_date,
        company_id=company_id,
    )


# ---------------------------------------------------------------------------
# Reports
# ---------------------------------------------------------------------------

def _default_tax_year() -> int:
    return tax_year_start(india_today()).year


def _build_report(
    db: Session,
    *,
    kind: str,
    tax_year: int,
    quarter: int | None,
    company_id: int | None,
) -> TdsReportOut:
    voucher_type = "receipt" if kind == "receivable" else "payment"
    from_date, to_date = quarter_bounds(tax_year, quarter)
    # A row's deduction date is the earlier of its invoice and payment dates,
    # so it can only fall in the period if one of them is on or before the
    # period's end. Narrow by that in SQL and test the exact date in Python.
    period_end = datetime.combine(to_date, time.max)
    query = (
        db.query(PaymentInvoiceAllocation)
        .join(Payment, Payment.id == PaymentInvoiceAllocation.payment_id)
        .join(Invoice, Invoice.id == PaymentInvoiceAllocation.invoice_id)
        .options(
            joinedload(PaymentInvoiceAllocation.payment).joinedload(Payment.ledger),
            joinedload(PaymentInvoiceAllocation.invoice),
        )
        .filter(
            Payment.status == "active",
            Invoice.status == "active",
            Payment.voucher_type == voucher_type,
            PaymentInvoiceAllocation.tds_amount > 0,
            (Invoice.invoice_date <= period_end) | (Payment.date <= period_end),
        )
    )
    if company_id is not None:
        query = query.filter(company_scope(Payment.company_id, company_id))

    rows: list[TdsReportRow] = []
    for allocation in query.all():
        payment = allocation.payment
        invoice = allocation.invoice
        on_date = deduction_date(invoice.invoice_date, payment.date)
        if not (from_date <= on_date <= to_date):
            continue
        ledger = payment.ledger
        party_pan = (ledger.pan or pan_from_gstin(ledger.gst)) if ledger is not None else None
        rows.append(TdsReportRow(
            allocation_id=allocation.id,
            payment_id=payment.id,
            payment_number=payment.payment_number,
            payment_date=payment.date,
            invoice_id=invoice.id,
            invoice_number=invoice.invoice_number,
            supplier_invoice_number=invoice.supplier_invoice_number,
            invoice_date=invoice.invoice_date,
            deduction_date=on_date,
            quarter=quarter_of(on_date),
            ledger_id=payment.ledger_id,
            party_name=(ledger.name if ledger is not None else None) or invoice.ledger_name or "Unknown party",
            party_pan=party_pan,
            section_id=allocation.tds_section_id,
            section_ref=allocation.tds_section_ref,
            rate=float(allocation.tds_rate) if allocation.tds_rate is not None else None,
            taxable_amount=float(money(invoice.taxable_amount)),
            base_amount=float(allocation.tds_base_amount) if allocation.tds_base_amount is not None else None,
            cash_amount=float(money(allocation.allocated_amount)),
            tds_amount=float(money(allocation.tds_amount)),
            certificate_received=bool(allocation.tds_certificate_received),
        ))
    rows.sort(key=lambda row: (row.deduction_date, row.payment_date, row.allocation_id))

    def _totals(key_of, label_of, pan_of=None) -> list[TdsTotal]:
        buckets: dict[str, dict] = {}
        for row in rows:
            key = key_of(row)
            bucket = buckets.setdefault(key, {
                "key": key,
                "label": label_of(row),
                "pan": pan_of(row) if pan_of else None,
                "count": 0,
                "base_amount": Decimal("0"),
                "tds_amount": Decimal("0"),
            })
            bucket["count"] += 1
            bucket["base_amount"] += Decimal(str(row.base_amount if row.base_amount is not None else row.taxable_amount))
            bucket["tds_amount"] += Decimal(str(row.tds_amount))
        return [
            TdsTotal(
                key=bucket["key"],
                label=bucket["label"],
                pan=bucket["pan"],
                count=bucket["count"],
                base_amount=float(money(bucket["base_amount"])),
                tds_amount=float(money(bucket["tds_amount"])),
            )
            for bucket in sorted(buckets.values(), key=lambda b: b["label"].lower())
        ]

    by_section = _totals(
        lambda row: row.section_ref or "",
        lambda row: f"s.{row.section_ref}" if row.section_ref else "Section not recorded",
    )
    by_party = _totals(
        lambda row: str(row.ledger_id) if row.ledger_id is not None else row.party_name,
        lambda row: row.party_name,
        lambda row: row.party_pan,
    )
    total_tds = money(sum((Decimal(str(row.tds_amount)) for row in rows), Decimal("0")))
    total_base = money(sum(
        (Decimal(str(row.base_amount if row.base_amount is not None else row.taxable_amount)) for row in rows),
        Decimal("0"),
    ))
    return TdsReportOut(
        kind=kind,
        tax_year=tax_year,
        tax_year_label=tax_year_label(tax_year),
        quarter=quarter,
        from_date=from_date,
        to_date=to_date,
        rows=rows,
        totals_by_section=by_section,
        totals_by_party=by_party,
        total_tds=float(total_tds),
        total_base=float(total_base),
    )


def _csv_text(value: str | None) -> str:
    """Stop free text from running as a formula when the file opens in a spreadsheet."""
    text = value or ""
    return f"'{text}" if text[:1] in ("=", "+", "-", "@") else text


def _csv_amount(value: float | None) -> str:
    return "" if value is None else f"{value:.2f}"


def _report_csv(report: TdsReportOut) -> StreamingResponse:
    buffer = StringIO(newline="")
    writer = csv.writer(buffer)
    party = "Customer" if report.kind == "receivable" else "Supplier"
    document = "Invoice" if report.kind == "receivable" else "Bill"
    voucher = "Receipt" if report.kind == "receivable" else "Payment"
    title = "TDS receivable" if report.kind == "receivable" else "TDS payable"
    period = f"Q{report.quarter}" if report.quarter else "All quarters"
    writer.writerow([f"{title} - tax year {report.tax_year_label} - {period}"])
    writer.writerow([])
    header = [
        "Quarter", "Deduction date", party, f"{party} PAN", f"{document} number",
    ]
    if report.kind == "payable":
        header.append("Supplier bill number")
    header += [
        f"{document} date", f"{voucher} number", f"{voucher} date", "Section", "Rate %",
        "Taxable amount", "TDS base", "Cash", "TDS amount",
    ]
    if report.kind == "receivable":
        header.append("Certificate received")
    writer.writerow(header)
    for row in report.rows:
        line = [
            f"Q{row.quarter}",
            row.deduction_date.isoformat(),
            _csv_text(row.party_name),
            _csv_text(row.party_pan),
            _csv_text(row.invoice_number),
        ]
        if report.kind == "payable":
            line.append(_csv_text(row.supplier_invoice_number))
        line += [
            row.invoice_date.date().isoformat(),
            _csv_text(row.payment_number),
            row.payment_date.date().isoformat(),
            _csv_text(f"s.{row.section_ref}" if row.section_ref else ""),
            "" if row.rate is None else f"{row.rate:g}",
            _csv_amount(row.taxable_amount),
            _csv_amount(row.base_amount),
            _csv_amount(row.cash_amount),
            _csv_amount(row.tds_amount),
        ]
        if report.kind == "receivable":
            line.append("Yes" if row.certificate_received else "No")
        writer.writerow(line)
    writer.writerow([])
    writer.writerow(["Totals by section"])
    writer.writerow(["Section", "Entries", "TDS base", "TDS amount"])
    for total in report.totals_by_section:
        writer.writerow([_csv_text(total.label), total.count, _csv_amount(total.base_amount), _csv_amount(total.tds_amount)])
    writer.writerow([])
    writer.writerow([f"Totals by {party.lower()}"])
    writer.writerow([party, "PAN", "Entries", "TDS base", "TDS amount"])
    for total in report.totals_by_party:
        writer.writerow([
            _csv_text(total.label), _csv_text(total.pan), total.count,
            _csv_amount(total.base_amount), _csv_amount(total.tds_amount),
        ])
    writer.writerow([])
    writer.writerow(["Total TDS", "", "", _csv_amount(report.total_base), _csv_amount(report.total_tds)])

    suffix = f"_q{report.quarter}" if report.quarter else ""
    filename = f"tds_{report.kind}_{report.tax_year_label}{suffix}.csv"
    return StreamingResponse(
        BytesIO(buffer.getvalue().encode("utf-8-sig")),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


def _report_params(tax_year: int | None, quarter: int | None) -> tuple[int, int | None]:
    return (tax_year if tax_year is not None else _default_tax_year()), quarter


@router.get("/{kind}", response_model=TdsReportOut)
def get_tds_report(
    kind: Literal["receivable", "payable"],
    tax_year: int | None = Query(None, ge=2000, le=2100, description="Start year, e.g. 2026 for 2026-27"),
    quarter: int | None = Query(None, ge=1, le=4),
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
    active_company: CompanyProfile = Depends(get_active_company),
):
    """TDS customers deducted from our invoices (receivable, for Form 26AS/AIS) or
    TDS we deducted from suppliers (payable, the input for Form 140 / 26Q)."""
    year, q = _report_params(tax_year, quarter)
    return _build_report(db, kind=kind, tax_year=year, quarter=q, company_id=getattr(active_company, "id", None))


@router.get("/{kind}/csv")
def download_tds_report_csv(
    kind: Literal["receivable", "payable"],
    tax_year: int | None = Query(None, ge=2000, le=2100),
    quarter: int | None = Query(None, ge=1, le=4),
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
    active_company: CompanyProfile = Depends(get_active_company),
):
    year, q = _report_params(tax_year, quarter)
    report = _build_report(db, kind=kind, tax_year=year, quarter=q, company_id=getattr(active_company, "id", None))
    return _report_csv(report)


@router.patch("/allocations/{allocation_id}", response_model=TdsAllocationOut)
def update_tds_allocation(
    allocation_id: int,
    payload: TdsAllocationPatch,
    db: Session = Depends(get_db),
    _: User = Depends(require_company_role(UserRole.admin, UserRole.manager)),
    active_company: CompanyProfile = Depends(get_active_company),
):
    """Tick or untick the TDS certificate (Form 16A / Form 131) as received."""
    company_id = getattr(active_company, "id", None)
    query = (
        db.query(PaymentInvoiceAllocation)
        .join(Payment, Payment.id == PaymentInvoiceAllocation.payment_id)
        .filter(PaymentInvoiceAllocation.id == allocation_id, PaymentInvoiceAllocation.tds_amount > 0)
    )
    if company_id is not None:
        query = query.filter(company_scope(Payment.company_id, company_id))
    allocation = query.first()
    if allocation is None:
        raise HTTPException(status_code=404, detail="TDS entry not found")
    allocation.tds_certificate_received = payload.certificate_received
    db.commit()
    return TdsAllocationOut(allocation_id=allocation.id, certificate_received=bool(allocation.tds_certificate_received))
