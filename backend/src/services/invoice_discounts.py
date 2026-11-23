"""Discount amount derivation for reporting.

Invoices do not store discount *amounts* — :mod:`src.services.invoice_processor`
computes them at write time and persists only ``discount_type`` and
``discount_value``, with ``taxable_amount`` already net of any line discount.
Reports that need a "Discount Given" figure therefore have to recover it.

Normally this module recovers discounts by *inverting* the write path's
algebra instead of replaying the calculation. For inclusive item discounts,
however, intrastate GST splitting can move the stored taxable base by a paisa.
Those item discounts are reconstructed from their stored discount parameters
and the original pre-discount base; invoice-level discounts remain inverted
from the final document totals.

The derivation is coupled to ``InvoiceProcessor.calculate_totals`` and
``InvoiceProcessor._apply_totals``.  If the discount write path changes, the
figures here go silently wrong — see ``tests/services/test_invoice_discounts.py``,
which round-trips against the processor to catch exactly that.
"""

from dataclasses import dataclass
from decimal import Decimal

from sqlalchemy.orm import Session

from src.models.invoice import Invoice, InvoiceItem
from src.services.gst_tax_service import invoice_is_interstate, money as _money


@dataclass
class InvoiceDiscountSummary:
    """Discount amounts for one invoice, all positive Decimals.

    Amounts stay ``Decimal`` rather than ``float`` (unlike
    :class:`~src.services.invoice_payments.InvoicePaymentSummary`) because
    reports sum these across every invoice in a period; float accumulation
    drifts. Convert at the schema boundary.
    """

    invoice_id: int
    item_discount_total: Decimal
    invoice_discount_amount: Decimal
    total_discount: Decimal


def _dec(value) -> Decimal:
    """Coerce a DB value to Decimal.

    Numeric columns come back as Decimal on Postgres but float on SQLite (the
    test engine), so route through ``str`` to avoid binary float artefacts.
    """
    return Decimal(str(value or 0))


def _pre_discount_taxable(item: InvoiceItem, *, tax_inclusive: bool) -> Decimal:
    """Reconstruct a line's taxable amount *before* its discount was applied.

    Mirrors ``InvoiceProcessor.calculate_totals`` exactly, including its
    intermediate rounding — the tax-inclusive branch rounds ``line_total``
    first and *then* divides, so collapsing the two steps would drift a paisa.
    """
    quantity = _dec(item.quantity)
    unit_price = _dec(item.unit_price)
    gst_rate = _dec(item.gst_rate)

    if tax_inclusive:
        line_total = _money(unit_price * quantity)
        return _money(line_total / (1 + gst_rate / Decimal("100")))
    return _money(unit_price * quantity)


def item_discount_amount(item: InvoiceItem, *, tax_inclusive: bool) -> Decimal:
    """Recover one line's discount amount from its stored taxable amount."""
    pre_discount_taxable = _pre_discount_taxable(item, tax_inclusive=tax_inclusive)
    if tax_inclusive and item.discount_type in ("net", "percentage"):
        # An inclusive intrastate line can have its taxable base shifted by
        # one paisa to preserve the entered gross price with equal GST halves.
        # Inverting that stored base would misreport the actual line discount.
        # Recover the amount from the original pre-discount taxable base and
        # the persisted discount parameters instead.
        value = _dec(item.discount_value)
        if value <= 0:
            return Decimal("0.00")
        if item.discount_type == "percentage":
            discount = _money(pre_discount_taxable * value / Decimal("100"))
        else:
            discount = _money(value)
        return min(discount, pre_discount_taxable)

    discount = pre_discount_taxable - _dec(item.taxable_amount)
    # A stored taxable above the reconstruction would mean the write path
    # changed shape; clamp rather than report a negative discount.
    if discount <= 0:
        return Decimal("0.00")
    return _money(discount)


def _item_discount_totals(db: Session, invoice_ids: list[int], tax_inclusive_by_invoice: dict[int, bool]) -> dict[int, Decimal]:
    """Sum per-line discounts for each invoice.

    Only lines carrying a ``discount_type`` are fetched: an undiscounted line
    stores its pre-discount taxable unchanged, so it contributes exactly zero
    and reconstructing it would be pure rounding risk for no gain.
    """
    if not invoice_ids:
        return {}

    items = (
        db.query(InvoiceItem)
        .filter(
            InvoiceItem.invoice_id.in_(invoice_ids),
            InvoiceItem.discount_type.isnot(None),
        )
        .all()
    )

    totals: dict[int, Decimal] = {}
    for item in items:
        tax_inclusive = tax_inclusive_by_invoice.get(item.invoice_id, False)
        discount = item_discount_amount(item, tax_inclusive=tax_inclusive)
        if discount <= 0:
            continue
        totals[item.invoice_id] = totals.get(item.invoice_id, Decimal("0")) + discount

    return {invoice_id: _money(total) for invoice_id, total in totals.items()}


def invoice_discount_amount(invoice: Invoice) -> Decimal:
    """Recover the invoice-level discount by inverting the processor's totals.

    ``_apply_totals`` ends with ``total_amount = raw_total + tcs + round_off`` in
    both the round-off and non-round-off branches (``round_off`` being 0 in the
    latter, ``tcs`` 0 on an invoice without TCS), where ``raw_total`` is already
    net of the invoice discount and ``raw_total`` before the discount is
    ``taxable_amount + total_tax_amount``. Rearranged, the discount falls
    straight out.
    """
    discount = (
        _dec(invoice.taxable_amount)
        + _dec(invoice.total_tax_amount)
        + _dec(getattr(invoice, "tcs_amount", 0))
        + _dec(invoice.round_off_amount)
        - _dec(invoice.total_amount)
    )
    if discount <= 0:
        return Decimal("0.00")
    return _money(discount)


def apportion_invoice_discount(
    line_taxables: list[Decimal],
    *,
    invoice_discount: Decimal,
    invoice_tax: Decimal,
) -> list[Decimal]:
    """Split an invoice-level discount into each line's ex-GST share.

    Item ``taxable_amount`` already nets off *line* discounts but never the
    invoice-level one: ``InvoiceProcessor._apply_totals`` subtracts that from
    ``raw_total`` (taxable + GST) after line and tax totals are fixed, so no
    stored line or tax figure ever reflects it. A per-product revenue or spend
    figure built from line ``taxable_amount`` therefore overstates by the
    invoice discount unless it is apportioned back onto the lines.

    GST treatment: the discount is taken off the GST-*inclusive* raw total, so
    only part of it is a reduction in the ex-GST value of the goods. That part
    is ``invoice_discount * taxable / (taxable + tax)``, where ``taxable`` is
    the sum of ``line_taxables`` and ``tax`` is the invoice's stored total GST.
    The remainder corresponds to GST that was nominally charged but not
    collected; it is not revenue, so it is dropped here (the stored GST figures
    are left as the processor wrote them). This holds for tax-inclusive
    invoices too, since their line ``taxable_amount`` is already ex-GST.

    The ex-GST share is then split across lines pro-rata by line
    ``taxable_amount``. Each share is rounded to paise and the rounding residue
    lands on the largest line, so the shares always sum exactly to the ex-GST
    share and a report's total never drifts from the invoice by a paisa.

    Returns one non-negative Decimal per input line, in the same order.
    """
    taxables = [_dec(value) for value in line_taxables]
    taxable_total = sum(taxables, Decimal("0"))
    discount = _dec(invoice_discount)
    gross = taxable_total + _dec(invoice_tax)

    if discount <= 0 or taxable_total <= 0 or gross <= 0:
        return [Decimal("0.00") for _ in taxables]

    ex_gst_share = _money(min(discount, gross) * taxable_total / gross)
    return _split_by_weight(ex_gst_share, taxables)


def _split_by_weight(amount: Decimal, weights: list[Decimal]) -> list[Decimal]:
    """Split ``amount`` pro-rata by ``weights``, rounded to paise.

    The rounding residue lands on the largest weight (the first, on a tie), so
    the parts always add back to exactly ``amount``. ``amount`` may be negative.
    """
    total = sum(weights, Decimal("0"))
    if not amount or total <= 0:
        return [Decimal("0.00") for _ in weights]
    shares = [_money(amount * weight / total) for weight in weights]
    residue = amount - sum(shares, Decimal("0"))
    if residue:
        largest = max(range(len(weights)), key=lambda index: weights[index])
        shares[largest] = _money(shares[largest] + residue)
    return shares


@dataclass(frozen=True)
class DiscountedLine:
    """One invoice line's taxable value and GST after its share of the invoice discount.

    Returned by :func:`discounted_line_amounts`.
    """

    taxable_amount: Decimal
    tax_amount: Decimal

    @property
    def line_total(self) -> Decimal:
        """What the line billed, GST included (TCS is never part of a line)."""
        return _money(self.taxable_amount + self.tax_amount)


def discounted_line_amounts(invoice: Invoice, *, include_round_off: bool = False) -> dict[int, DiscountedLine]:
    """Each line's taxable value and GST net of the invoice-level discount, keyed by item id.

    This is the one place that turns an invoice's stored line figures into what
    each line actually billed. Use it wherever a per-line figure has to agree
    with the invoice's totals: credit notes (what a return may credit, and the
    denominator for reversing TCS) and reports that net credit notes off
    invoice lines.

    ``InvoiceItem.taxable_amount``/``tax_amount`` are net of any *line*
    discount but never of the invoice-level one, which
    ``apply_discount_and_round_off`` takes off the GST-inclusive raw total
    without touching any stored line or tax figure. Here that discount is
    shared back onto the lines:

    * its ex-GST part goes off the lines' taxable values pro-rata by taxable
      value, the same split :func:`apportion_invoice_discount` makes;
    * the rest (the GST the discount took off) goes off the lines' GST pro-rata
      by GST, so each line keeps its own rate.

    Both splits put their rounding residue on the largest line, so the lines
    add up to exactly ``taxable_amount + total_tax_amount - discount``, that is
    ``total_amount - tcs_amount - round_off_amount``. On a discounted intrastate
    invoice a line whose GST comes out at an odd paisa moves that paisa to its taxable
    value, so the GST still splits into equal CGST and SGST halves (as the
    invoice's own lines do) and a credit note reversing it halves exactly. The
    line total is unchanged; otherwise the taxable values match
    :func:`apportion_invoice_discount`'s to the paisa.

    With ``include_round_off`` the invoice's round-off is shared out over the
    lines' taxable values only, pro-rata by taxable value with the residue on
    the largest line (a round-up adds to them, a round-down takes off). It
    never touches GST: round-off is not tax, so each line keeps exactly the
    GST the invoice charged (less any discount share), and on an undiscounted
    invoice the GST is the stored GST to the paisa. The lines then add up to
    exactly ``total_amount - tcs_amount``: everything the buyer was charged
    apart from TCS. Credit notes use this, so a full return credits the whole
    invoice and the buyer's account closes at zero. A report that nets credit
    notes off invoice lines should pass it too, or a full return leaves the
    round-off behind as a residue.

    A line with no taxable value and no GST (a row from before those columns
    existed) carries nothing and takes no share; callers fall back to its
    stored ``line_total``. An invoice with no discount (and, with
    ``include_round_off``, no round-off) returns the stored figures unchanged;
    with no discount the GST is always unchanged.
    """
    items = list(invoice.items)
    taxables = [_dec(item.taxable_amount) for item in items]
    taxes = [_dec(item.tax_amount) for item in items]

    discount = invoice_discount_amount(invoice)
    round_off = _dec(invoice.round_off_amount) if include_round_off else Decimal("0")

    taxable_total = sum(taxables, Decimal("0"))
    gross = taxable_total + sum(taxes, Decimal("0"))
    if (not discount and not round_off) or gross <= 0:
        return {
            item.id: DiscountedLine(_money(taxable), _money(tax))
            for item, taxable, tax in zip(items, taxables, taxes)
        }

    zeros = [Decimal("0.00") for _ in items]
    taxable_shares, tax_shares = zeros, zeros
    if discount:
        taxable_part = _money(min(discount, gross) * taxable_total / gross)
        taxable_shares = _split_by_weight(taxable_part, taxables)
        tax_shares = _split_by_weight(_money(min(discount, gross) - taxable_part), taxes)
    # Round-off is not tax: it goes on the taxable values alone.
    round_off_shares = _split_by_weight(round_off, taxables)
    halves = bool(discount) and not invoice_is_interstate(invoice)
    lines: dict[int, DiscountedLine] = {}
    for item, taxable, tax, taxable_share, tax_share, round_off_share in zip(
        items, taxables, taxes, taxable_shares, tax_shares, round_off_shares
    ):
        line_taxable = _money(taxable - taxable_share + round_off_share)
        line_tax = _money(tax - tax_share)
        if halves and line_tax > 0 and int(line_tax * 100) % 2:
            line_taxable += Decimal("0.01")
            line_tax -= Decimal("0.01")
        lines[item.id] = DiscountedLine(line_taxable, line_tax)
    return lines


def build_invoice_discount_totals(
    db: Session,
    invoices: list[Invoice],
) -> dict[int, InvoiceDiscountSummary]:
    """Derive discount amounts for a batch of invoices, keyed by invoice id.

    Batch-shaped like
    :func:`~src.services.invoice_payments.build_invoice_payment_summaries`: one
    grouped query for the whole set rather than per-invoice lookups.
    """
    if not invoices:
        return {}

    invoice_ids = [invoice.id for invoice in invoices]
    tax_inclusive_by_invoice = {invoice.id: bool(invoice.tax_inclusive) for invoice in invoices}
    item_totals = _item_discount_totals(db, invoice_ids, tax_inclusive_by_invoice)

    summaries: dict[int, InvoiceDiscountSummary] = {}
    for invoice in invoices:
        item_total = item_totals.get(invoice.id, Decimal("0.00"))
        invoice_discount = invoice_discount_amount(invoice)
        summaries[invoice.id] = InvoiceDiscountSummary(
            invoice_id=invoice.id,
            item_discount_total=item_total,
            invoice_discount_amount=invoice_discount,
            total_discount=_money(item_total + invoice_discount),
        )

    return summaries
