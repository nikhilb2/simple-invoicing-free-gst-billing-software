"""The parts of a sales document that invoices and quotations must compute alike.

A quotation that converts to an invoice has to arrive at the same figures, so this
arithmetic exists once. ``InvoiceProcessor.apply_payload`` and
:mod:`src.services.quotation` both call it. Line totals are shared the same way,
through ``InvoiceProcessor.calculate_totals``.

:mod:`src.services.invoice_discounts` inverts the discount and round-off arithmetic
below for reporting, so any change here must be mirrored there.

``total_amount = taxable + tax - discount + tcs + round-off``. TCS (#769) is added after
the invoice discount and before the round-off, and never touches the GST figures.

A document's ``discount_mode`` (#1154) says which way it takes the bill discount.
'before_tax' (every new document) shares it over the lines' taxable values first, with
:func:`share_bill_discount`, so GST is charged on the discounted amount and the
``discount`` term above is 0. 'after_tax' (documents saved before #1154) takes it off
taxable + tax at the end, as it always did.
"""

from decimal import Decimal, ROUND_HALF_UP

from fastapi import HTTPException

from src.core.document_limits import MONEY_LIMIT
from src.models.company import CompanyProfile
from src.services.gst_tax_service import assign_item_tax_split, money as _money
from src.services.invoice_discounts import _split_by_weight
from src.services.pdf_templates.builders import _fmt_currency
from src.services.tcs import TcsCharge, tcs_amount_for, tcs_base


def require_money_fits(subject: str, *amounts: Decimal) -> None:
    """Check NUMERIC(10, 2) after accounting for rounding at storage."""
    if any(abs(amount) >= Decimal(MONEY_LIMIT) - Decimal("0.005") for amount in amounts):
        raise HTTPException(
            status_code=400,
            detail=f"{subject} is too large. Amounts must stay below {MONEY_LIMIT:,} after rounding.",
        )


def snapshot_company_fields(document, company: CompanyProfile | None) -> None:
    """Copy the seller's details onto a document, as they stand today."""
    document.company_name = company.name if company else None
    document.company_address = company.address if company else None
    document.company_gst = company.gst if company else None
    document.company_phone = company.phone_number if company else None
    document.company_email = company.email if company else None
    document.company_website = company.website if company else None
    document.company_currency_code = company.currency_code if company else None
    document.company_bank_name = company.bank_name if company else None
    document.company_branch_name = company.branch_name if company else None
    document.company_account_name = company.account_name if company else None
    document.company_account_number = company.account_number if company else None
    document.company_ifsc_code = company.ifsc_code if company else None
    # Company branding fields
    document.company_logo_data = company.logo_data if company else None
    document.company_logo_mime_type = company.logo_mime_type if company else None
    document.company_additional_info = company.additional_company_info if company else None
    # Snapshot terms & conditions as formatted text
    terms = (company.terms or []) if company else []
    document.company_terms_text = "\n".join(f"{t.serial_number}. {t.content}" for t in terms) if terms else None


def _apply_tcs(document, net_total: Decimal, gross_total: Decimal, tcs: TcsCharge | None) -> Decimal:
    """Store the document's TCS copy and return the amount to add to its total."""
    if tcs is None:
        if hasattr(document, "tcs_amount"):
            document.tcs_section_id = None
            document.tcs_section_ref = None
            document.tcs_rate = None
            document.tcs_base_amount = 0
            document.tcs_amount = 0
        return Decimal("0")

    taxable_total = Decimal(str(document.taxable_amount or 0))
    base = tcs_base(net_total, gross_total, taxable_total, tcs.base_kind)
    amount = tcs.amount if tcs.amount is not None else tcs_amount_for(base, tcs.rate)
    document.tcs_section_id = tcs.section_id
    document.tcs_section_ref = tcs.section_ref
    document.tcs_rate = float(tcs.rate)
    document.tcs_base_amount = float(base)
    document.tcs_amount = float(amount)
    return amount


DISCOUNT_MODES = ("before_tax", "after_tax")
NEW_DOCUMENT_MODE_ERROR = "New documents take the discount before GST."


def resolve_discount_mode(stored: str | None, requested: str | None, *, creating: bool) -> str:
    """The mode a save writes: always 'before_tax' for a new document (#1154).

    An edit that leaves the mode out keeps the stored one, and may switch an
    'after_tax' document to 'before_tax'. Nothing ever goes back to 'after_tax'.
    A row not yet written has no stored mode and is new, so 'before_tax'.
    """
    if creating:
        if requested == "after_tax":
            raise HTTPException(status_code=422, detail=NEW_DOCUMENT_MODE_ERROR)
        return "before_tax"
    if requested is None:
        return stored or "before_tax"
    if requested == "after_tax" and stored != "after_tax":
        raise HTTPException(
            status_code=422,
            detail="This document takes the discount before GST. It can't go back to after GST.",
        )
    return requested


def bill_discount_amount(subtotal: Decimal, discount_type: str | None, discount_value: float | None) -> Decimal:
    """A before-GST bill discount on ``subtotal``: % of it, or the flat amount, to the paisa."""
    if not discount_type or discount_value is None or discount_value <= 0:
        return Decimal("0.00")
    if discount_type == "percentage":
        return _money(subtotal * Decimal(str(discount_value)) / Decimal("100"))
    return _money(Decimal(str(discount_value)))


def share_bill_discount(
    items: list,
    discount_type: str | None,
    discount_value: float | None,
    *,
    interstate_supply: bool,
    currency_code: str | None = None,
) -> Decimal:
    """Take a before-GST bill discount off the lines and work their GST out again (#1154).

    ``items`` are the document's line rows with their taxable value, GST split and
    line total already set (after their own line discounts). The discount comes off
    the subtotal, their taxable values added up, and is shared across them by taxable
    value with :func:`~src.services.invoice_discounts._split_by_weight` (the paisa
    left over goes on the largest line, the first on a tie). Each line's GST is then
    worked out on its taxable value after its share, CGST and SGST each at half the
    rate, as for any line. With "Price already includes GST" too: the share comes off
    the ex-GST value, as a line discount does, and the GST is charged on what is left.

    Sets each line's ``bill_discount_amount`` and returns the discount. A discount
    larger than the subtotal is refused with 400 rather than capped.
    """
    taxables = [_money(Decimal(str(item.taxable_amount or 0))) for item in items]
    subtotal = _money(sum(taxables, Decimal("0")))
    discount = bill_discount_amount(subtotal, discount_type, discount_value)
    if discount > subtotal:
        raise HTTPException(
            status_code=400,
            detail=(
                f"The discount ({_fmt_currency(float(discount), currency_code)}) is more than "
                f"the subtotal ({_fmt_currency(float(subtotal), currency_code)})."
            ),
        )
    shares = _split_by_weight(discount, taxables) if discount else [Decimal("0.00") for _ in items]
    discounted = []
    for item, taxable, share in zip(items, taxables, shares):
        item.bill_discount_amount = float(share)
        if not share:
            continue
        new_taxable = _money(taxable - share)
        tax = _money(new_taxable * Decimal(str(item.gst_rate or 0)) / Decimal("100"))
        item.taxable_amount = float(new_taxable)
        item.tax_amount = float(tax)
        item.line_total = float(_money(new_taxable + tax))
        discounted.append(item)
    # GST on the reduced taxable value; CGST and SGST rounded separately, so equal.
    assign_item_tax_split(discounted, interstate_supply=interstate_supply, tax_inclusive=False)
    return discount


def apply_discount_and_round_off(
    document,
    raw_total: Decimal,
    discount_type: str | None,
    discount_value: float | None,
    *,
    tcs: TcsCharge | None = None,
) -> None:
    """Take a document-level discount off ``raw_total``, add TCS, then round it if asked.

    ``raw_total`` is taxable plus tax. Reads ``document.apply_round_off``,
    ``document.discount_mode`` and ``document.taxable_amount``, and sets the discount
    fields, the TCS fields, ``round_off_amount`` and ``total_amount``. With ``tcs``
    None the TCS fields are cleared and the total is what it was before TCS existed.

    A 'before_tax' document (#1154) has already had its discount shared over the
    lines by :func:`share_bill_discount`, so ``raw_total`` is net of it and nothing
    more comes off here; only the discount fields are stored, as typed.
    """
    gross_total = raw_total
    document.discount_type = discount_type
    document.discount_value = discount_value
    before_tax = getattr(document, "discount_mode", None) == "before_tax"
    if not before_tax and discount_type and discount_value is not None and discount_value > 0:
        if discount_type == "percentage":
            discount_amount = _money(raw_total * Decimal(str(discount_value)) / Decimal("100"))
        else:
            discount_amount = _money(Decimal(str(discount_value)))
        discount_amount = min(discount_amount, raw_total)
        raw_total = _money(raw_total - discount_amount)

    tcs_amount = _apply_tcs(document, raw_total, gross_total, tcs)
    if tcs_amount:
        raw_total = _money(raw_total + tcs_amount)

    if document.apply_round_off:
        rounded_total = raw_total.quantize(Decimal("1"), rounding=ROUND_HALF_UP)
        document.round_off_amount = float(_money(rounded_total - raw_total))
        document.total_amount = float(_money(rounded_total))
    else:
        document.round_off_amount = 0
        document.total_amount = float(raw_total)
