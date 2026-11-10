from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal, ROUND_HALF_UP

from fastapi import HTTPException
from sqlalchemy import func
from sqlalchemy.orm import Session

from src.models.credit_note import CreditNote, CreditNoteItem
from src.models.invoice import Invoice
from src.models.payment import Payment, PaymentInvoiceAllocation
from src.services.company_access import company_scope
from src.services import tds_allocations


@dataclass
class InvoicePaymentSummary:
    invoice_id: int
    credited_amount: float
    paid_amount: float
    remaining_amount: float
    outstanding_amount: float
    payment_status: str
    due_in_days: int | None
    # TDS the customer kept back (sales) or we kept back (purchases). Settles the
    # invoice like cash but is not cash, so paid_amount stays the cash figure.
    tds_amount: float = 0.0


def _money(value: Decimal) -> Decimal:
    return value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def _credit_totals_by_invoice(db: Session, invoice_ids: list[int]) -> dict[int, Decimal]:
    if not invoice_ids:
        return {}

    rows = (
        db.query(CreditNoteItem.invoice_id, func.coalesce(func.sum(CreditNoteItem.line_total), 0))
        .join(CreditNote, CreditNote.id == CreditNoteItem.credit_note_id)
        .filter(
            CreditNote.status == "active",
            CreditNoteItem.invoice_id.in_(invoice_ids),
        )
        .group_by(CreditNoteItem.invoice_id)
        .all()
    )
    return {invoice_id: _money(Decimal(str(total or 0))) for invoice_id, total in rows}


def _payment_totals_by_invoice(
    db: Session,
    invoice_ids: list[int],
    *,
    exclude_payment_id: int | None = None,
) -> dict[int, Decimal]:
    if not invoice_ids:
        return {}

    query = (
        db.query(PaymentInvoiceAllocation.invoice_id, func.coalesce(func.sum(PaymentInvoiceAllocation.allocated_amount), 0))
        .join(Payment, Payment.id == PaymentInvoiceAllocation.payment_id)
        .filter(
            Payment.status == "active",
            PaymentInvoiceAllocation.invoice_id.in_(invoice_ids),
        )
    )
    if exclude_payment_id is not None:
        query = query.filter(Payment.id != exclude_payment_id)

    rows = query.group_by(PaymentInvoiceAllocation.invoice_id).all()
    return {invoice_id: _money(Decimal(str(total or 0))) for invoice_id, total in rows}


def _tds_totals_by_invoice(
    db: Session,
    invoice_ids: list[int],
    *,
    exclude_payment_id: int | None = None,
) -> dict[int, Decimal]:
    """TDS settled per invoice on active receipts/payments (#768, #770)."""
    if not invoice_ids:
        return {}

    query = (
        db.query(PaymentInvoiceAllocation.invoice_id, func.coalesce(func.sum(PaymentInvoiceAllocation.tds_amount), 0))
        .join(Payment, Payment.id == PaymentInvoiceAllocation.payment_id)
        .filter(
            Payment.status == "active",
            PaymentInvoiceAllocation.invoice_id.in_(invoice_ids),
            PaymentInvoiceAllocation.tds_amount > 0,
        )
    )
    if exclude_payment_id is not None:
        query = query.filter(Payment.id != exclude_payment_id)

    rows = query.group_by(PaymentInvoiceAllocation.invoice_id).all()
    return {invoice_id: _money(Decimal(str(total or 0))) for invoice_id, total in rows}


def build_invoice_payment_summaries(
    db: Session,
    invoices: list[Invoice],
    *,
    exclude_payment_id: int | None = None,
) -> dict[int, InvoicePaymentSummary]:
    if not invoices:
        return {}

    invoice_ids = [invoice.id for invoice in invoices]
    credit_totals = _credit_totals_by_invoice(db, invoice_ids)
    payment_totals = _payment_totals_by_invoice(db, invoice_ids, exclude_payment_id=exclude_payment_id)
    tds_totals = _tds_totals_by_invoice(db, invoice_ids, exclude_payment_id=exclude_payment_id)
    today = date.today()

    summaries: dict[int, InvoicePaymentSummary] = {}
    for invoice in invoices:
        total_amount = _money(Decimal(str(invoice.total_amount or 0)))
        credited_amount = credit_totals.get(invoice.id, Decimal("0.00"))
        paid_amount = payment_totals.get(invoice.id, Decimal("0.00"))
        tds_amount = tds_totals.get(invoice.id, Decimal("0.00"))
        remaining_amount = _money(total_amount - credited_amount - paid_amount - tds_amount)
        if remaining_amount < 0:
            remaining_amount = Decimal("0.00")

        if remaining_amount <= 0:
            payment_status = "paid"
        elif paid_amount > 0 or tds_amount > 0:
            payment_status = "partial"
        else:
            payment_status = "unpaid"

        due_in_days = None
        if invoice.due_date is not None:
            due_in_days = (invoice.due_date.date() - today).days

        summaries[invoice.id] = InvoicePaymentSummary(
            invoice_id=invoice.id,
            credited_amount=float(credited_amount),
            paid_amount=float(paid_amount),
            remaining_amount=float(remaining_amount),
            outstanding_amount=float(remaining_amount),
            payment_status=payment_status,
            due_in_days=due_in_days,
            tds_amount=float(tds_amount),
        )

    return summaries


def open_amounts_by_ledger(
    db: Session,
    ledger_ids: list[int],
    *,
    company_id: int,
) -> dict[int, tuple[float, float]]:
    """Open (receivable, payable) per ledger, for display and reminders only.

    Receivable is the remaining amount of active sales invoices, payable that of
    active purchase invoices. Allocation never offsets one against the other;
    this just lets a ledger that is both customer and supplier be shown net.
    """
    if not ledger_ids:
        return {}

    invoices = (
        db.query(Invoice)
        .filter(
            Invoice.company_id == company_id,
            Invoice.ledger_id.in_(ledger_ids),
            Invoice.voucher_type.in_(["sales", "purchase"]),
            Invoice.status == "active",
        )
        .all()
    )
    summaries = build_invoice_payment_summaries(db, invoices)

    totals: dict[int, list[Decimal]] = {}
    for invoice in invoices:
        bucket = totals.setdefault(invoice.ledger_id, [Decimal("0.00"), Decimal("0.00")])
        remaining = Decimal(str(summaries[invoice.id].remaining_amount))
        bucket[0 if invoice.voucher_type == "sales" else 1] += remaining
    return {
        ledger_id: (float(_money(receivable)), float(_money(payable)))
        for ledger_id, (receivable, payable) in totals.items()
    }


def is_offset_by_payables(receivable: float, payable: float) -> bool:
    """True when a ledger owes us nothing net because open payables cover its receivable."""
    return payable > 0 and round(receivable - payable, 2) <= 0


def get_outstanding_invoices_for_ledger(
    db: Session,
    ledger_id: int,
    *,
    voucher_type: str,
    exclude_payment_id: int | None = None,
    company_id: int | None = None,
) -> list[tuple[Invoice, InvoicePaymentSummary]]:
    invoice_voucher_type = "sales" if voucher_type == "receipt" else "purchase"
    invoices_query = db.query(Invoice).filter(
        Invoice.ledger_id == ledger_id,
        Invoice.voucher_type == invoice_voucher_type,
        Invoice.status == "active",
    )
    if company_id is not None:
        invoices_query = invoices_query.filter(company_scope(Invoice.company_id, company_id))
    invoices = invoices_query.order_by(Invoice.invoice_date.asc(), Invoice.id.asc()).all()
    summaries = build_invoice_payment_summaries(db, invoices, exclude_payment_id=exclude_payment_id)
    outstanding_rows = [
        (invoice, summaries[invoice.id])
        for invoice in invoices
        if summaries[invoice.id].remaining_amount > 0
    ]
    outstanding_rows.sort(
        key=lambda row: (
            row[0].due_date or row[0].invoice_date,
            row[0].invoice_date,
            row[0].id,
        )
    )
    return outstanding_rows


def auto_allocate_outstanding_invoices(
    rows: list[tuple[Invoice, InvoicePaymentSummary]],
    amount: float,
) -> dict[int, float]:
    remaining_amount = _money(Decimal(str(amount or 0)))
    suggestions: dict[int, float] = {}

    for invoice, summary in rows:
        if remaining_amount <= 0:
            break

        invoice_remaining = _money(Decimal(str(summary.remaining_amount or 0)))
        if invoice_remaining <= 0:
            continue

        allocated_amount = min(remaining_amount, invoice_remaining)
        if allocated_amount <= 0:
            continue

        suggestions[invoice.id] = float(allocated_amount)
        remaining_amount = _money(remaining_amount - allocated_amount)

    return suggestions


def validate_payment_allocations(
    db: Session,
    *,
    ledger_id: int | None,
    voucher_type: str,
    payment_amount: float,
    invoice_allocations,
    exclude_payment_id: int | None = None,
    company_id: int | None = None,
    payment_date: date | None = None,
) -> list[tuple[Invoice, Decimal]]:
    return [
        (row.invoice, row.allocated_amount)
        for row in _validate_payment_allocations_detailed(
            db,
            ledger_id=ledger_id,
            voucher_type=voucher_type,
            payment_amount=payment_amount,
            invoice_allocations=invoice_allocations,
            exclude_payment_id=exclude_payment_id,
            company_id=company_id,
            payment_date=payment_date,
        )
    ]


def _validate_payment_allocations_detailed(
    db: Session,
    *,
    ledger_id: int | None,
    voucher_type: str,
    payment_amount: float,
    invoice_allocations,
    exclude_payment_id: int | None = None,
    company_id: int | None = None,
    payment_date: date | None = None,
) -> list["tds_allocations.NormalizedAllocation"]:
    if not invoice_allocations:
        return []

    if voucher_type not in {"receipt", "payment"}:
        raise HTTPException(status_code=400, detail="Only receipts and payments can be allocated to invoices")

    if ledger_id is None:
        raise HTTPException(status_code=400, detail="Invoice allocations require a ledger")

    invoice_ids = [allocation.invoice_id for allocation in invoice_allocations]
    if len(set(invoice_ids)) != len(invoice_ids):
        raise HTTPException(status_code=400, detail="Each invoice may only appear once in invoice_allocations")

    invoices_query = db.query(Invoice).filter(Invoice.id.in_(invoice_ids))
    if company_id is not None:
        invoices_query = invoices_query.filter(company_scope(Invoice.company_id, company_id))
    # Serialise settlement checks: two receipts or payments saved at once against
    # the same bill would otherwise both see the same remaining amount and both
    # allocate cash and TDS against it. Locking in id order avoids deadlocks;
    # SQLAlchemy ignores FOR UPDATE on SQLite.
    invoices = invoices_query.order_by(Invoice.id).with_for_update().all()
    invoice_map = {invoice.id: invoice for invoice in invoices}
    missing_ids = sorted(set(invoice_ids) - set(invoice_map))
    if missing_ids:
        raise HTTPException(status_code=404, detail=f"Invoices not found: {missing_ids}")

    expected_invoice_type = "sales" if voucher_type == "receipt" else "purchase"
    summaries = build_invoice_payment_summaries(db, invoices, exclude_payment_id=exclude_payment_id)

    normalized: list[tds_allocations.NormalizedAllocation] = []
    allocated_total = Decimal("0.00")
    previous_allocations = {}
    if exclude_payment_id is not None:
        # The rows an edit replaces: TDS left exactly as it was stays allowed
        # even if purchase TDS has since been turned off.
        previous_allocations = {
            row.invoice_id: row
            for row in db.query(PaymentInvoiceAllocation).filter(PaymentInvoiceAllocation.payment_id == exclude_payment_id)
        }
    tds_context = tds_allocations.TdsContext(
        db,
        voucher_type=voucher_type,
        ledger_id=ledger_id,
        company_id=company_id,
        previous_allocations=previous_allocations,
    )
    for allocation in invoice_allocations:
        invoice = invoice_map[allocation.invoice_id]
        if invoice.ledger_id != ledger_id:
            raise HTTPException(status_code=400, detail=f"Invoice {invoice.id} does not belong to ledger {ledger_id}")
        if invoice.status != "active":
            raise HTTPException(status_code=400, detail=f"Invoice {invoice.id} is not active")
        if invoice.voucher_type != expected_invoice_type:
            raise HTTPException(
                status_code=400,
                detail=f"Invoice {invoice.id} cannot be allocated to a {voucher_type}",
            )

        allocated_amount = _money(Decimal(str(allocation.allocated_amount)))
        tds_amount = _money(Decimal(str(getattr(allocation, "tds_amount", 0) or 0)))
        if tds_amount > 0:
            # TDS alone may settle an invoice the cash went elsewhere for, but
            # neither part may be negative.
            if allocated_amount < 0:
                raise HTTPException(status_code=400, detail="Allocated amounts must not be negative")
        elif allocated_amount <= 0:
            raise HTTPException(status_code=400, detail="Allocated amounts must be greater than zero")

        summary = summaries[invoice.id]
        available_amount = _money(Decimal(str(summary.remaining_amount)))
        if allocated_amount + tds_amount > available_amount:
            if tds_amount > 0:
                raise HTTPException(
                    status_code=400,
                    detail=(
                        f"Invoice {invoice.invoice_number or invoice.id} only has {float(available_amount):.2f} remaining, "
                        f"but cash {float(allocated_amount):.2f} plus TDS {float(tds_amount):.2f} "
                        f"comes to {float(allocated_amount + tds_amount):.2f}"
                    ),
                )
            raise HTTPException(
                status_code=400,
                detail=f"Invoice {invoice.invoice_number or invoice.id} only has {float(available_amount):.2f} remaining",
            )

        normalized.append(tds_context.normalize(
            invoice,
            allocated_amount,
            tds_amount,
            getattr(allocation, "tds_section_id", None),
            payment_date=payment_date,
        ))
        allocated_total = _money(allocated_total + allocated_amount)

    if allocated_total > _money(Decimal(str(payment_amount or 0))):
        raise HTTPException(status_code=400, detail="Allocated total cannot exceed the receipt/payment amount")

    return normalized


def sync_payment_allocations(
    db: Session,
    *,
    payment: Payment,
    invoice_allocations,
    exclude_payment_id: int | None = None,
    company_id: int | None = None,
) -> None:
    payment_day = payment.date.date() if isinstance(payment.date, datetime) else payment.date
    normalized = _validate_payment_allocations_detailed(
        db,
        ledger_id=payment.ledger_id,
        voucher_type=payment.voucher_type,
        payment_amount=float(payment.amount or 0),
        invoice_allocations=invoice_allocations,
        exclude_payment_id=exclude_payment_id,
        company_id=company_id,
        payment_date=payment_day,
    )

    # Keep the section copies of a row whose section did not change, so editing
    # a receipt never re-reads the (possibly newer) section table or party PAN.
    previous_by_invoice = {
        existing.invoice_id: existing for existing in list(payment.invoice_allocations)
    }
    for existing_allocation in list(payment.invoice_allocations):
        db.delete(existing_allocation)
    db.flush()

    for row in normalized:
        db.add(PaymentInvoiceAllocation(
            payment_id=payment.id,
            invoice_id=row.invoice.id,
            allocated_amount=float(row.allocated_amount),
            **tds_allocations.allocation_tds_columns(row, previous_by_invoice.get(row.invoice.id)),
        ))


def invoice_has_tds_allocated(db: Session, invoice_id: int) -> bool:
    """True when an active receipt/payment has TDS settled against this invoice (#768, #770)."""
    return (
        db.query(PaymentInvoiceAllocation.id)
        .join(Payment, Payment.id == PaymentInvoiceAllocation.payment_id)
        .filter(
            Payment.status == "active",
            PaymentInvoiceAllocation.invoice_id == invoice_id,
            PaymentInvoiceAllocation.tds_amount > 0,
        )
        .first()
        is not None
    )
