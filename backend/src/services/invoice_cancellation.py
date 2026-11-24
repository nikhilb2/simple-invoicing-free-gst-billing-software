"""Cancelling an invoice: the checks and the stock, serial, quotation and challan moves.

Shared by the invoice cancel route and the ledger delete that cancels a party's
invoices (#1050), so both reverse an invoice the same way. It flushes but never
commits; the caller owns the transaction and rolls back on any HTTPException.
"""

from __future__ import annotations

from datetime import datetime

from fastapi import HTTPException
from sqlalchemy.orm import Session

from src.models.invoice import Invoice
from src.services.delivery_challan import lock_source_challan, reopen_challan_after_invoice_cancelled
from src.services.invoice_payments import invoice_has_tds_allocated, payment_allocated_to_invoice
from src.services.invoice_processor import InvoiceProcessor, invoice_has_credit_notes
from src.services.quotation import lock_invoice_for_status_change, reopen_after_invoice_cancelled


def cancel_invoice_record(db: Session, invoice: Invoice) -> Invoice:
    """Cancel ``invoice`` and return it as locked and re-read. Raises HTTPException if refused."""
    # Before any stock moves: conversion takes the challan and quotation rows
    # first as well.
    source_challan = lock_source_challan(db, invoice)
    invoice, source_quotation = lock_invoice_for_status_change(db, invoice)
    if invoice.status == "cancelled":
        raise HTTPException(status_code=400, detail="Invoice is already cancelled")
    # An active credit note has already returned part of the stock and
    # is still filed and counted; reversing the full invoice quantities
    # here would double-return the noted part and orphan the note.
    if invoice_has_credit_notes(db, invoice.id):
        raise HTTPException(
            status_code=400,
            detail="This invoice has credit notes against it — cancel them first",
        )
    # TDS settled on it would otherwise stay in the TDS report and the
    # ledger with no invoice behind it.
    if invoice_has_tds_allocated(db, invoice.id):
        side = "receipt" if invoice.voucher_type == "sales" else "payment"
        raise HTTPException(
            status_code=400,
            detail=f"TDS is recorded against this invoice. Remove the TDS from the {side} first, then cancel the invoice.",
        )
    # A receipt/payment still allocated here would be left pointing at a
    # cancelled invoice: it couldn't be saved again, and the allocation
    # couldn't be removed from the page either (#792).
    allocated_payment = payment_allocated_to_invoice(db, invoice.id)
    if allocated_payment is not None:
        side = "receipt" if allocated_payment.voucher_type == "receipt" else "payment"
        voucher_number = allocated_payment.payment_number or allocated_payment.id
        raise HTTPException(
            status_code=400,
            detail=f"Remove this invoice from {side} {voucher_number} first",
        )
    processor = InvoiceProcessor(db)
    # Serials first: cancelling a purchase whose units are already sold is
    # refused, and that message is more useful than a stock shortfall.
    processor.reverse_serials(invoice)
    processor.reverse_inventory(invoice)
    invoice.status = "cancelled"
    invoice.cancelled_at = datetime.utcnow()
    reopen_after_invoice_cancelled(source_quotation)
    # The challan's goods are out on it again, now the invoice's are back.
    reopen_challan_after_invoice_cancelled(db, source_challan, invoice)
    return invoice
