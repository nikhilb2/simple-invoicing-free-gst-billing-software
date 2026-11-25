"""Deleting a ledger that has entries (#1050).

The ledger is soft-deleted: everything still live on it is cancelled through the same
code the cancel buttons use, and the row stays, hidden, so the cancelled documents and
the reports that list them keep the party's name. In order:

1. its active credit notes (an invoice with a live note cannot be cancelled);
2. its active receipts and payments, opening balance included; their invoice
   allocations and TDS stop counting with them, as with any cancelled payment;
3. its active invoices, sales first so the stock and serials a purchase brought in
   are back before that purchase takes them out again; this reopens their
   quotations and challans;
4. its open delivery challans and quotations, including the ones step 3 reopened;
5. the live public links to its statement and documents;
6. the ledger itself: ``deleted_at`` and ``deleted_by``.

Steps 1-4 may take stock below zero on the way, and only the end result is checked
(#1080): cancelling a return takes its goods out again before cancelling the sale
puts them back, and a purchase from the party can be cancelled before the challan
that sent the same goods back to it. Stock still short at the end refuses it all.

Nothing here commits. The route commits once at the end, or rolls everything back
when a step refuses: :class:`LedgerDeletionBlocked` names the document and the reason.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime
from decimal import Decimal

from fastapi import HTTPException
from sqlalchemy import and_, or_
from sqlalchemy.orm import Session

from src.models.buyer import Buyer as Ledger
from src.models.credit_note import CreditNote
from src.models.delivery_challan import STATUS_INVOICED, STATUS_OPEN as CHALLAN_OPEN, DeliveryChallan
from src.models.inventory import Inventory
from src.models.invoice import Invoice
from src.models.payment import Payment
from src.models.product import Product
from src.models.quotation import STATUS_CONVERTED, Quotation
from src.models.share_link import ShareLink
from src.services.company_access import company_scope
from src.services.credit_note import cancel_credit_note
from src.services.delivery_challan import cancel_challan
from src.services.gst_tax_service import india_today
from src.services.inventory_service import DeferredStockCheck, deferred_stock_check
from src.services.invoice_cancellation import cancel_invoice_record
from src.services.quotation import CANCELLABLE_STATUSES, cancel_quotation, document_label
from src.services.share_documents import (
    RESOURCE_CREDIT_NOTE,
    RESOURCE_INVOICE,
    RESOURCE_PAYMENT,
    RESOURCE_QUOTATION,
    RESOURCE_STATEMENT,
)


@dataclass
class LedgerEntryCounts:
    """What deleting the ledger cancels (or, after the fact, cancelled)."""

    sales_invoices: int = 0
    purchase_invoices: int = 0
    receipts: int = 0
    payments: int = 0
    opening_balance: bool = False
    credit_notes: int = 0
    delivery_challans: int = 0
    quotations: int = 0
    share_links: int = 0

    def as_dict(self) -> dict:
        return asdict(self)


class LedgerDeletionBlocked(HTTPException):
    def __init__(self, document_type: str, document_id: int, label: str, reason: HTTPException):
        detail = reason.detail
        why = str(detail.get("message") if isinstance(detail, dict) else detail).rstrip()
        if not why.endswith((".", "!", "?")):
            why += "."
        super().__init__(
            status_code=409,
            detail={
                "code": "ledger_delete_blocked",
                "message": f"{label} cannot be cancelled: {why} Nothing was changed.",
                "document_type": document_type,
                "document_id": document_id,
            },
        )


def ledger_has_documents(db: Session, ledger_id: int, company_id: int | None) -> bool:
    """Whether anything at all, cancelled or not, points at the ledger.

    Such a ledger cannot be removed outright: the rows reference it.
    """
    for model in (Invoice, Payment, CreditNote):
        query = db.query(model.id).filter(model.ledger_id == ledger_id)
        if company_id is not None:
            query = query.filter(company_scope(model.company_id, company_id))
        if query.first() is not None:
            return True
    for model in (Quotation, DeliveryChallan):
        query = db.query(model.id).filter(model.ledger_id == ledger_id)
        if company_id is not None:
            query = query.filter(model.company_id == company_id)
        if query.first() is not None:
            return True
    return False


def _scoped(query, model, company_id: int | None, *, strict: bool = False):
    if company_id is None:
        return query
    if strict:
        return query.filter(model.company_id == company_id)
    return query.filter(company_scope(model.company_id, company_id))


def _active_invoices(db: Session, ledger_id: int, company_id: int | None):
    query = db.query(Invoice).filter(Invoice.ledger_id == ledger_id, Invoice.status == "active")
    return _scoped(query, Invoice, company_id)


def _active_payments(db: Session, ledger_id: int, company_id: int | None):
    query = db.query(Payment).filter(Payment.ledger_id == ledger_id, Payment.status == "active")
    return _scoped(query, Payment, company_id)


def _active_credit_notes(db: Session, ledger_id: int, company_id: int | None):
    query = db.query(CreditNote).filter(CreditNote.ledger_id == ledger_id, CreditNote.status == "active")
    return _scoped(query, CreditNote, company_id)


def _open_challans(db: Session, ledger_id: int, company_id: int | None, *, after_invoices: bool):
    """Challans to cancel. ``after_invoices``: also the ones step 3 is about to reopen."""
    condition = DeliveryChallan.status == CHALLAN_OPEN
    if after_invoices:
        reopened = _active_invoices(db, ledger_id, company_id).with_entities(Invoice.source_challan_id)
        condition = or_(
            condition,
            and_(DeliveryChallan.status == STATUS_INVOICED, DeliveryChallan.id.in_(reopened.scalar_subquery())),
        )
    query = db.query(DeliveryChallan).filter(DeliveryChallan.ledger_id == ledger_id, condition)
    return _scoped(query, DeliveryChallan, company_id, strict=True)


def _open_quotations(db: Session, ledger_id: int, company_id: int | None, *, after_invoices: bool):
    condition = Quotation.status.in_(CANCELLABLE_STATUSES)
    if after_invoices:
        reopened = _active_invoices(db, ledger_id, company_id).with_entities(Invoice.source_quotation_id)
        condition = or_(
            condition,
            and_(Quotation.status == STATUS_CONVERTED, Quotation.id.in_(reopened.scalar_subquery())),
        )
    query = db.query(Quotation).filter(Quotation.ledger_id == ledger_id, condition)
    return _scoped(query, Quotation, company_id, strict=True)


def _live_share_links(db: Session, ledger_id: int, company_id: int | None):
    """Live public links to the statement and to any of the ledger's documents."""

    def ids(model, *, strict: bool = False):
        query = db.query(model.id).filter(model.ledger_id == ledger_id)
        return _scoped(query, model, company_id, strict=strict).scalar_subquery()

    query = db.query(ShareLink).filter(
        ShareLink.revoked_at.is_(None),
        or_(
            and_(ShareLink.resource_type == RESOURCE_STATEMENT, ShareLink.resource_id == ledger_id),
            and_(ShareLink.resource_type == RESOURCE_INVOICE, ShareLink.resource_id.in_(ids(Invoice))),
            and_(ShareLink.resource_type == RESOURCE_PAYMENT, ShareLink.resource_id.in_(ids(Payment))),
            and_(ShareLink.resource_type == RESOURCE_CREDIT_NOTE, ShareLink.resource_id.in_(ids(CreditNote))),
            and_(ShareLink.resource_type == RESOURCE_QUOTATION, ShareLink.resource_id.in_(ids(Quotation, strict=True))),
        ),
    )
    if company_id is not None:
        query = query.filter(ShareLink.company_id == company_id)
    return query


def preview_ledger_deletion(db: Session, ledger: Ledger, company_id: int | None) -> tuple[LedgerEntryCounts, bool]:
    """What deleting ``ledger`` would cancel, and whether any invoice is from before this month.

    An invoice from an earlier month may already be in a GSTR-1 that was filed.
    """
    invoices = _active_invoices(db, ledger.id, company_id).with_entities(Invoice.voucher_type, Invoice.invoice_date).all()
    payments = _active_payments(db, ledger.id, company_id).with_entities(Payment.voucher_type).all()
    month_start = india_today().replace(day=1)
    counts = LedgerEntryCounts(
        sales_invoices=sum(1 for voucher_type, _ in invoices if voucher_type != "purchase"),
        purchase_invoices=sum(1 for voucher_type, _ in invoices if voucher_type == "purchase"),
        receipts=sum(1 for (voucher_type,) in payments if voucher_type == "receipt"),
        payments=sum(1 for (voucher_type,) in payments if voucher_type == "payment"),
        opening_balance=any(voucher_type == "opening_balance" for (voucher_type,) in payments),
        credit_notes=_active_credit_notes(db, ledger.id, company_id).count(),
        delivery_challans=_open_challans(db, ledger.id, company_id, after_invoices=True).count(),
        quotations=_open_quotations(db, ledger.id, company_id, after_invoices=True).count(),
        share_links=_live_share_links(db, ledger.id, company_id).count(),
    )
    earlier_months = any(
        invoice_date is not None and invoice_date.date() < month_start for _, invoice_date in invoices
    )
    return counts, earlier_months


def _plain(quantity) -> str:
    return format(Decimal(str(quantity)).normalize(), "f")


def _require_stock_left(db: Session, company_id: int | None, stock_check: DeferredStockCheck) -> None:
    """Refuse if a product the cancels took below zero is still below zero (#1080)."""
    if not stock_check.short:
        return
    db.flush()
    query = (
        db.query(Inventory, Product.name)
        .join(Product, Product.id == Inventory.product_id)
        .filter(Inventory.product_id.in_(stock_check.short), Inventory.quantity < 0)
    )
    if company_id is not None:
        query = query.filter(company_scope(Inventory.company_id, company_id))
    row = query.order_by(Product.name, Product.id).first()
    if row is None:
        return
    inventory, name = row
    document_type, document_id, label = stock_check.short[inventory.product_id]
    reason = HTTPException(
        status_code=400,
        detail=(
            f"Not enough stock of {name}. Cancelling everything on this ledger would leave it "
            f"{_plain(-inventory.quantity)} short."
        ),
    )
    raise LedgerDeletionBlocked(document_type, document_id, label, reason)


def delete_ledger_with_entries(db: Session, ledger: Ledger, company_id: int | None, user_id: int) -> LedgerEntryCounts:
    """Cancel everything live on ``ledger`` and soft-delete it. Flushes, never commits."""
    with deferred_stock_check(db) as stock_check:
        counts = _cancel_documents(db, ledger, company_id, stock_check)
        _require_stock_left(db, company_id, stock_check)

    # 5. Public links: revoked, never deleted, like the Revoke button.
    now = datetime.utcnow()
    for link in _live_share_links(db, ledger.id, company_id).all():
        link.revoked_at = now
        counts.share_links += 1

    # 6. The ledger.
    ledger.deleted_at = now
    ledger.deleted_by = user_id
    db.flush()
    return counts


def _cancel_documents(
    db: Session, ledger: Ledger, company_id: int | None, stock_check: DeferredStockCheck
) -> LedgerEntryCounts:
    """Steps 1-4. Shortfalls in stock are left for :func:`_require_stock_left`."""
    counts = LedgerEntryCounts()

    # Lock the documents before any stock row, in the order the cancel paths take
    # them (challan, quotation, invoice, then stock), so a concurrent cancel or edit
    # waits for this instead of deadlocking with it.
    _open_challans(db, ledger.id, company_id, after_invoices=True).order_by(DeliveryChallan.id).with_for_update().all()
    _open_quotations(db, ledger.id, company_id, after_invoices=True).order_by(Quotation.id).with_for_update().all()
    _active_invoices(db, ledger.id, company_id).order_by(Invoice.id).with_for_update().all()

    # 1. Credit notes.
    for note in _active_credit_notes(db, ledger.id, company_id).order_by(CreditNote.id).all():
        label = f"Credit note {note.credit_note_number}"
        stock_check.document = ("credit_note", note.id, label)
        try:
            cancel_credit_note(note.id, db, company_id=company_id, commit=False)
        except HTTPException as exc:
            raise LedgerDeletionBlocked("credit_note", note.id, label, exc) from exc
        counts.credit_notes += 1

    # 2. Receipts and payments: the same status change as cancelling one by hand.
    for payment in _active_payments(db, ledger.id, company_id).order_by(Payment.id).all():
        payment.status = "cancelled"
        if payment.voucher_type == "receipt":
            counts.receipts += 1
        elif payment.voucher_type == "payment":
            counts.payments += 1
        else:
            counts.opening_balance = True
    db.flush()

    # 3. Invoices, sales before purchases.
    invoices = _active_invoices(db, ledger.id, company_id).all()
    invoices.sort(key=lambda invoice: (invoice.voucher_type == "purchase", invoice.id))
    for invoice in invoices:
        is_purchase = invoice.voucher_type == "purchase"
        label = f"{'Purchase' if is_purchase else 'Sales'} invoice {invoice.invoice_number or invoice.id}"
        stock_check.document = ("invoice", invoice.id, label)
        try:
            cancel_invoice_record(db, invoice)
        except HTTPException as exc:
            raise LedgerDeletionBlocked("invoice", invoice.id, label, exc) from exc
        if is_purchase:
            counts.purchase_invoices += 1
        else:
            counts.sales_invoices += 1
    db.flush()

    # 4. Challans and quotations still open, the reopened ones included.
    for challan in _open_challans(db, ledger.id, company_id, after_invoices=False).order_by(DeliveryChallan.id).all():
        label = f"Delivery challan {challan.challan_number}"
        stock_check.document = ("delivery_challan", challan.id, label)
        try:
            cancel_challan(db, challan)
        except HTTPException as exc:
            raise LedgerDeletionBlocked("delivery_challan", challan.id, label, exc) from exc
        counts.delivery_challans += 1
    for quotation in _open_quotations(db, ledger.id, company_id, after_invoices=False).order_by(Quotation.id).all():
        label = f"{document_label(quotation.document_type)} {quotation.quotation_number}"
        try:
            cancel_quotation(db, quotation)
        except HTTPException as exc:
            raise LedgerDeletionBlocked("quotation", quotation.id, label, exc) from exc
        counts.quotations += 1
    return counts
