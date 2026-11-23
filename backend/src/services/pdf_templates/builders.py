"""Helper functions for PDF template building."""

from html import escape
from src.core.currency import resolve_currency_code
from decimal import Decimal, ROUND_HALF_UP

from src.models.company_account import CompanyAccount
from src.models.invoice import Invoice, InvoiceItem
from src.services.gst_tax_service import to_india_date
from src.services.invoice_discounts import invoice_discount_amount, item_discount_amount
from src.services.pdf_paper import page_css


def _money(value: Decimal) -> Decimal:
    return value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def _e(text: str | None) -> str:
    """Escape HTML special characters."""
    return escape(text or "")


def invoice_cancellation_note(invoice: Invoice) -> str:
    """Show the recorded cancellation date; old records may have no timestamp."""
    if getattr(invoice, "status", None) != "cancelled":
        return ""
    day = to_india_date(getattr(invoice, "cancelled_at", None))
    return f"Cancelled on {day.strftime('%d %b %Y')} (IST)" if day else "Cancelled"


def invoice_cancellation_html(invoice: Invoice) -> str:
    note = invoice_cancellation_note(invoice)
    if not note:
        return ""
    return (
        '<div style="border: 2px solid; padding: 8px; margin: 8px 0; '
        'text-align: center; font-weight: 700; text-transform: uppercase;">'
        f'{_e(note)}</div>'
    )


def _fmt_inr(value: float, currency: str = "INR") -> str:
    """Format a money value using Indian (lakh/crore) digit grouping for INR.

    e.g. 1234567.5 -> "₹12,34,567.50". The minus sign, when present, goes in
    front of the ₹ symbol rather than between it and the digits. Non-INR
    currency codes fall back to a plain "<amount> <code>" string (Western
    grouping) so this stays a drop-in formatter for callers that pass through
    whatever currency the company is configured with.
    """
    try:
        if currency == "INR":
            # Round to 2 decimal places first so float precision cannot drop a rupee.
            # (e.g. 6490.999999999999 must become ₹6,491.00, not ₹6,490.00)
            d = Decimal(str(value)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
            neg = d < 0
            d = abs(d)
            integer_part = int(d)
            decimal_part = f"{d - Decimal(integer_part):.2f}"[1:]  # ".xx"
            s = str(integer_part)
            if len(s) > 3:
                last3 = s[-3:]
                rest = s[:-3]
                groups = []
                while rest:
                    groups.append(rest[-2:])
                    rest = rest[:-2]
                groups.reverse()
                s = ",".join(groups) + "," + last3
            result = f"₹{s}{decimal_part}"
            return f"-{result}" if neg else result
        return f"{value:,.2f} {currency}"
    except Exception:
        return f"{value:,.2f}"


def _fmt_currency(value: float, currency_code: str | None = None) -> str:
    """Format a currency value with the appropriate symbol.

    INR uses Indian (lakh/crore) digit grouping via ``_fmt_inr``; other
    currencies keep Western (thousands) grouping. Either way, a negative
    amount's minus sign is printed in front of the symbol (``-$500.00``),
    not between the symbol and the digits (``$-500.00``).
    """
    code = resolve_currency_code(currency_code)
    try:
        if code == "INR":
            return _fmt_inr(value, "INR")
        symbol = "€" if code == "EUR" else "£" if code == "GBP" else "$"
        neg = value < 0
        formatted = f"{symbol}{abs(value):,.2f}"
        return f"-{formatted}" if neg else formatted
    except Exception:
        return f"{value:,.2f}"


def _fmt_rate(value: float) -> str:
    """Format a percentage rate without trailing zeros."""
    return f"{value:.2f}".rstrip("0").rstrip(".")


def _build_item_discount_html(item: InvoiceItem, currency: str | None, *, tax_inclusive: bool) -> str:
    """Muted sub-line under a product naming its discount and the amount it took off."""
    raw_value = float(item.discount_value or 0)
    if not item.discount_type or raw_value <= 0:
        return ""
    amount = float(item_discount_amount(item, tax_inclusive=tax_inclusive))
    if item.discount_type == "percentage":
        label = f"Disc: {_fmt_rate(raw_value)}% (-{_fmt_currency(amount, currency)})"
    else:
        label = f"Disc: {_fmt_currency(amount, currency)} off"
    return f"<br><span class=\"muted-text\">{label}</span>"


def tcs_label(rate, section_ref: str | None) -> str:
    """Wording for the TCS line, e.g. ``TCS @ 2% (s.394(1) Sl. No. 4)``."""
    label = "TCS"
    if rate is not None and float(rate) > 0:
        label += f" @ {_fmt_rate(float(rate))}%"
    if section_ref:
        label += f" (s.{section_ref})"
    return label


def _build_tcs_html(doc, currency: str | None) -> str:
    """Totals-box line for tax collected at source; empty when the document has none."""
    amount = float(getattr(doc, "tcs_amount", 0) or 0)
    if amount == 0:
        return ""
    label = _e(tcs_label(getattr(doc, "tcs_rate", None), getattr(doc, "tcs_section_ref", None)))
    return f"<p>{label}: {_fmt_currency(amount, currency)}</p>"


def _build_invoice_discount_html(invoice: Invoice, currency: str | None) -> str:
    """Totals-box line naming the invoice-level discount and the amount it took off."""
    raw_value = float(invoice.discount_value or 0)
    if not invoice.discount_type or raw_value <= 0:
        return ""
    amount = _fmt_currency(float(invoice_discount_amount(invoice)), currency)
    if invoice.discount_type == "percentage":
        return f"<p>Discount ({_fmt_rate(raw_value)}%): -{amount}</p>"
    return f"<p>Discount: -{amount}</p>"


def _amount_in_words_indian(amount: float, currency_code: str | None = None) -> str:
    """Convert a monetary amount to words using the Indian numbering system (crores/lakhs)."""
    _ONES = ['', 'One', 'Two', 'Three', 'Four', 'Five', 'Six', 'Seven',
             'Eight', 'Nine', 'Ten', 'Eleven', 'Twelve', 'Thirteen',
             'Fourteen', 'Fifteen', 'Sixteen', 'Seventeen', 'Eighteen', 'Nineteen']
    _TENS = ['', '', 'Twenty', 'Thirty', 'Forty', 'Fifty', 'Sixty', 'Seventy', 'Eighty', 'Ninety']

    def _two(n: int) -> str:
        if n < 20:
            return _ONES[n]
        return _TENS[n // 10] + (' ' + _ONES[n % 10] if n % 10 else '')

    def _three(n: int) -> str:
        if n == 0:
            return ''
        if n < 100:
            return _two(n)
        return _ONES[n // 100] + ' Hundred' + (' ' + _two(n % 100) if n % 100 else '')

    try:
        amount = round(amount, 2)
        rupees = int(amount)
        paise = round((amount - rupees) * 100)
        currency_label = 'Rupees' if not currency_code or currency_code == 'INR' else currency_code

        if rupees == 0 and paise == 0:
            return f'Zero {currency_label} Only'

        parts: list[str] = []
        n = rupees
        crores = n // 10_000_000
        n %= 10_000_000
        lakhs = n // 100_000
        n %= 100_000
        thousands = n // 1000
        remainder = n % 1000

        if crores:
            parts.append(_three(crores) + ' Crore')
        if lakhs:
            parts.append(_two(lakhs) + ' Lakh')
        if thousands:
            parts.append(_two(thousands) + ' Thousand')
        if remainder:
            parts.append(_three(remainder))

        rupee_words = ' '.join(parts) if parts else 'Zero'
        result = f'{rupee_words} {currency_label}'
        if paise:
            if not currency_code or currency_code == 'INR':
                result += f' and {_two(paise)} Paise'
            else:
                result += f' and {paise:02d}/100'
        return result + ' Only'
    except Exception:
        return ''


def _pdf_unit_price_including_tax(item: InvoiceItem) -> float:
    """Calculate unit price including tax from a line item."""
    quantity = Decimal(str(item.quantity or 0))
    if quantity <= 0:
        return float(item.unit_price or 0)

    line_total = Decimal(str(item.line_total or 0))
    return float(_money(line_total / quantity))


def _pdf_unit_price(item: InvoiceItem, *, tax_inclusive: bool) -> float:
    """Return the unit price for PDF display, respecting the tax-inclusive preference.

    When *tax_inclusive* is True the unit price includes tax (line_total / quantity).
    When *tax_inclusive* is False the unit price is displayed without tax
    (the stored unit_price).
    """
    if tax_inclusive:
        return _pdf_unit_price_including_tax(item)
    return float(item.unit_price or 0)


def _pdf_display_unit(unit: str | None) -> str:
    """Format unit display for PDF, abbreviating common units."""
    normalized_unit = (unit or "Pieces").strip()
    if not normalized_unit:
        normalized_unit = "Pieces"
    if normalized_unit.lower() == "pieces":
        return "Pcs"
    return normalized_unit


def _pdf_display_quantity(quantity: float | Decimal | int | None, allow_decimal: bool | None) -> str:
    """Format quantity display, handling decimal vs integer display."""
    value = Decimal(str(quantity or 0))
    if not allow_decimal and value == value.to_integral_value():
        return str(int(value))

    as_text = format(value, "f").rstrip("0").rstrip(".")
    return as_text or "0"


def _build_pdf_tax_header_cells(interstate_supply: bool, compact: bool = False) -> str:
    """Build tax header cells for invoice table based on interstate/intrastate supply.

    ``compact`` (A5) leaves out "Total Tax": it only repeats IGST, or CGST + SGST,
    and without it the amounts fit the narrower page.
    """
    total = "" if compact else '<th class="right">Total Tax</th>'
    if interstate_supply:
        return '<th class="right">IGST %</th><th class="right">IGST Amt</th>' + total
    return (
        '<th class="right">SGST %</th>'
        '<th class="right">SGST Amt</th>'
        '<th class="right">CGST %</th>'
        '<th class="right">CGST Amt</th>'
        + total
    )


def _colgroup(widths: list[int]) -> str:
    return "<colgroup>" + "".join(f'<col style="width: {w}%;" />' for w in widths) + "</colgroup>"


# A5 column widths. There is no "Total Tax" column, and HSN/SAC gets 11%: at A5
# width anything narrower breaks an 8-digit code in two.
# Key: (interstate, show_sku). Columns: #, item, [sku], hsn, qty, unit, price,
# the tax cells, amount.
_COMPACT_COLUMN_WIDTHS: dict[tuple[bool, bool], list[int]] = {
    (True, True): [4, 22, 9, 11, 6, 6, 13, 6, 11, 12],
    (True, False): [4, 31, 11, 6, 6, 13, 6, 11, 12],
    (False, True): [3, 15, 8, 11, 5, 5, 11, 5, 9, 5, 9, 14],
    (False, False): [3, 23, 11, 5, 5, 11, 5, 9, 5, 9, 14],
}


def _build_pdf_table_colgroup(interstate_supply: bool, show_sku: bool = True, compact: bool = False) -> str:
    """Build table column group for invoice PDF based on tax type and SKU visibility.

    HSN/SAC stays at 8% or wider in every layout: anything narrower breaks an
    8-digit HSN code across two lines at the table's 8px font size. ``compact`` is
    the A5 layout, which has no "Total Tax" column.
    """
    if compact:
        return _colgroup(_COMPACT_COLUMN_WIDTHS[(interstate_supply, show_sku)])
    if interstate_supply:
        if show_sku:
            return (
                '<colgroup>'
                '<col style="width: 4%;" />'
                '<col style="width: 20%;" />'
                '<col style="width: 7%;" />'
                '<col style="width: 8%;" />'
                '<col style="width: 6%;" />'
                '<col style="width: 6%;" />'
                '<col style="width: 12%;" />'
                '<col style="width: 7%;" />'
                '<col style="width: 10%;" />'
                '<col style="width: 10%;" />'
                '<col style="width: 10%;" />'
                '</colgroup>'
            )
        return (
            '<colgroup>'
            '<col style="width: 4%;" />'
            '<col style="width: 27%;" />'
            '<col style="width: 8%;" />'
            '<col style="width: 6%;" />'
            '<col style="width: 6%;" />'
            '<col style="width: 12%;" />'
            '<col style="width: 7%;" />'
            '<col style="width: 10%;" />'
            '<col style="width: 10%;" />'
            '<col style="width: 10%;" />'
            '</colgroup>'
        )
    if show_sku:
        return (
            '<colgroup>'
            '<col style="width: 3%;" />'
            '<col style="width: 15%;" />'
            '<col style="width: 6%;" />'
            '<col style="width: 8%;" />'
            '<col style="width: 5%;" />'
            '<col style="width: 5%;" />'
            '<col style="width: 10%;" />'
            '<col style="width: 6%;" />'
            '<col style="width: 8%;" />'
            '<col style="width: 6%;" />'
            '<col style="width: 8%;" />'
            '<col style="width: 8%;" />'
            '<col style="width: 12%;" />'
            '</colgroup>'
        )
    return (
        '<colgroup>'
        '<col style="width: 3%;" />'
        '<col style="width: 21%;" />'
        '<col style="width: 8%;" />'
        '<col style="width: 5%;" />'
        '<col style="width: 5%;" />'
        '<col style="width: 10%;" />'
        '<col style="width: 6%;" />'
        '<col style="width: 8%;" />'
        '<col style="width: 6%;" />'
        '<col style="width: 8%;" />'
        '<col style="width: 8%;" />'
        '<col style="width: 12%;" />'
        '</colgroup>'
    )


def _build_pdf_tax_row_cells(item: InvoiceItem, currency: str, interstate_supply: bool, compact: bool = False) -> str:
    """Build tax cells for a single invoice line item.

    ``compact`` (A5) leaves out the "Total Tax" cell, matching the header.
    """
    total_cell = "" if compact else f'<td class="right">{_fmt_currency(float(item.tax_amount or 0), currency)}</td>'
    gst_rate = float(item.gst_rate or 0)
    tax_amount = float(item.tax_amount or 0)

    if interstate_supply:
        igst_amount = float(item.igst_amount or 0)
        if tax_amount > 0 and igst_amount == 0:
            igst_amount = tax_amount
        igst_rate = gst_rate if igst_amount > 0 else 0
        return (
            f'<td class="right">{_fmt_rate(igst_rate)}%</td>'
            f'<td class="right">{_fmt_currency(igst_amount, currency)}</td>'
            + total_cell
        )

    sgst_amount = float(item.sgst_amount or 0)
    cgst_amount = float(item.cgst_amount or 0)
    if tax_amount > 0 and sgst_amount == 0 and cgst_amount == 0:
        cgst_amount = float(_money(Decimal(str(tax_amount)) / Decimal("2")))
        sgst_amount = float(_money(Decimal(str(tax_amount)) - Decimal(str(cgst_amount))))

    split_rate = gst_rate / 2 if (tax_amount > 0 or sgst_amount > 0 or cgst_amount > 0) else 0
    return (
        f'<td class="right">{_fmt_rate(split_rate)}%</td>'
        f'<td class="right">{_fmt_currency(sgst_amount, currency)}</td>'
        f'<td class="right">{_fmt_rate(split_rate)}%</td>'
        f'<td class="right">{_fmt_currency(cgst_amount, currency)}</td>'
        + total_cell
    )


def _build_pdf_tax_breakup_rows(invoice: Invoice, currency: str) -> str:
    """Build tax breakup summary rows for invoice footer."""
    cgst = float(invoice.cgst_amount or 0)
    sgst = float(invoice.sgst_amount or 0)
    igst = float(invoice.igst_amount or 0)

    # GST display rule for PDFs: show either IGST or CGST+SGST.
    if igst > 0:
        return f"<p>IGST: {_fmt_currency(igst, currency)}</p>"
    return (
        f"<p>CGST: {_fmt_currency(cgst, currency)}</p>"
        f"<p>SGST: {_fmt_currency(sgst, currency)}</p>"
    )


def _build_pdf_pay_qr_card_html(share_url: str, qr_data_uri: str) -> str:
    """The "Pay online" card: a QR of this document's own share page.

    124px is roughly 33mm on A4 -- above the ~25-30mm floor a printed QR needs to
    stay scannable, which 108px would sit right on top of.
    """
    if not share_url or not qr_data_uri:
        return ""

    # `pay-qr` is the shared hook: the invoice stylesheet docks it into the payment
    # panel beside the bank accounts, and the statement stylesheet -- which knows
    # nothing about bank accounts -- styles it on its own.
    return (
        '<div class="pay-qr">'
        '<p class="pay-qr__title">Pay online</p>'
        f'<img class="pay-qr__img" src="{_e(qr_data_uri)}" alt="Scan to pay online" />'
        '<p class="pay-qr__hint">Scan to view this document and pay by UPI</p>'
        "</div>"
    )


def _build_pdf_payment_details_html(
    invoice_bank_accounts: list[CompanyAccount],
    pay_qr_html: str = "",
) -> str:
    """Build bank payment details section for invoice PDF."""
    if not invoice_bank_accounts and not pay_qr_html:
        # The customer's copy has nothing to say about this; the app tells the owner instead.
        return ""

    accounts = "".join(
        '<div class="invoice-sheet__bank-account">'
        '<table class="invoice-sheet__bank-rows">'
        f"<tr><th>Bank</th><td>{_e(account.bank_name) or 'N/A'}</td></tr>"
        f"<tr><th>Branch</th><td>{_e(account.branch_name) or 'N/A'}</td></tr>"
        f"<tr><th>Account name</th><td>{_e(account.account_name) or 'N/A'}</td></tr>"
        f"<tr><th>A/C no.</th><td class=\"invoice-sheet__bank-key\">{_e(account.account_number) or 'N/A'}</td></tr>"
        f"<tr><th>IFSC</th><td class=\"invoice-sheet__bank-key\">{_e(account.ifsc_code) or 'N/A'}</td></tr>"
        "</table>"
        "</div>"
        for account in invoice_bank_accounts
    )
    if not accounts:
        return f'<div class="invoice-sheet__pay-panel invoice-sheet__pay-panel--qr-only">{pay_qr_html}</div>'

    # The QR docks on the right so the account details a customer might type by hand
    # are read first; the accounts stack beside it, filling the height the QR sets.
    return (
        '<div class="invoice-sheet__pay-panel">'
        f'<div class="invoice-sheet__pay-accounts">{accounts}</div>'
        f"{pay_qr_html}"
        "</div>"
    )


# ---------------------------------------------------------------------------
# A5 layout for the transaction documents
# ---------------------------------------------------------------------------

# The invoice, purchase bill, credit note, delivery challan and quotation share
# one stylesheet shape (``invoice-sheet__*`` or ``sheet__*``), so one override
# serves all five. It is appended after the template's own styles and wins on
# source order. It is not the A4 layout scaled down: that would print the item
# table at about 4pt. The table builders also drop the "Total Tax" column on A5
# (their ``compact`` flag), which is what makes the CGST + SGST table fit.
A5_DOCUMENT_CSS = """
  body { font-size: 9px; }
  .invoice-title, .sheet__title { font-size: 13px; padding-bottom: 5px; margin-bottom: 8px; }
  .invoice-sheet__header, .sheet__header { padding-bottom: 8px; margin-bottom: 8px; gap: 8px; }
  .invoice-sheet__header h3, .sheet__header h3 { font-size: 13px; }
  .invoice-sheet__meta h2, .sheet__meta h2, .invoice-sheet__titleblock h2 { font-size: 11px; }
  .invoice-sheet__logo-img, .invoice-sheet__purchase-logo-img, .sheet__logo-img { max-width: 110px; max-height: 46px; }
  .invoice-sheet__billto, .sheet__party { padding: 6px 8px; }
  .invoice-sheet__addresses, .sheet__parties { flex-direction: column; gap: 6px; margin-bottom: 8px; }
  .invoice-sheet__reference-notes, .sheet__note { padding: 6px 8px; margin-bottom: 8px; }
  .invoice-sheet__table, .sheet__table { margin-bottom: 8px; font-size: 7.5px; }
  .invoice-sheet__table thead th, .sheet__table thead th { padding: 3px 2px; font-size: 6.5px; letter-spacing: 0; }
  .invoice-sheet__table tbody td, .sheet__table tbody td { padding: 3px 2px; }
  /* Amounts stay on one line. Text cells still break anywhere, but only when a
     word does not fit: the HSN column is wide enough for an 8-digit code. */
  .invoice-sheet__table tbody td.right, .sheet__table tbody td.right { white-space: nowrap; }
  .invoice-sheet__table tbody td:first-child, .sheet__table tbody td:first-child { white-space: nowrap; }
  .sheet__table tbody td.nowrap { white-space: nowrap; }
  .invoice-sheet__footer, .sheet__footer { gap: 10px; }
  .invoice-sheet__totals, .sheet__totals { flex-basis: 165px; }
  .invoice-sheet__total-value, .sheet__total-value { font-size: 14px !important; }
  .pay-qr { flex-basis: 104px; padding: 5px; }
  /* About 26mm: still above the ~25mm a printed QR needs to scan. */
  .pay-qr__img { width: 100px; height: 100px; }
  .invoice-sheet__pay-accounts { padding: 6px 7px; }
  .invoice-sheet__bank-rows th, .sheet__bank-rows th { width: 46px; }
  .invoice-sheet__terms, .sheet__terms { margin-top: 8px; padding-top: 6px; }
"""


def document_paper_css(paper: str) -> tuple[str, str]:
    """``(page_rule, a5_override)`` for an invoice-family template.

    The page rule replaces the template's hardcoded ``@page``; the override is
    empty except on A5. Thermal never reaches these templates: it has a layout of
    its own in ``thermal_template``.
    """
    if paper == "a5":
        return page_css("a5"), A5_DOCUMENT_CSS
    return page_css("a4"), ""
