"""One thermal-roll layout (80mm and 58mm) for every transaction document.

A thermal receipt printer has a fixed print width and no page length, so the A4
table layout does not shrink onto it. Each document is instead adapted into a
``ThermalDoc`` and printed as a single column: the company block, the title and
meta lines, the party, one short block per item (with the HSN code and tax rate a
GST invoice needs), a GST summary by rate, the totals and the amount in words.

Thermal heads print grey as a dither, so the style is black only: no
backgrounds, no grey text, dashed rules between sections.

``render_pdf`` in ``src.services.pdf_paper`` sets the page size: this module
only sets the width it lays out for.
"""

from __future__ import annotations

from collections import OrderedDict
from dataclasses import dataclass, field
from decimal import Decimal

from src.core.currency import resolve_currency_code
from src.core.validation import GST_STATE_NAMES
from src.models.delivery_challan import STATUS_CANCELLED as CHALLAN_CANCELLED
from src.models.quotation import DOCUMENT_PROFORMA, STATUS_CANCELLED
from src.services.gst_tax_service import india_today, invoice_is_interstate, to_india_date
from src.services.invoice_discounts import invoice_discount_amount, item_discount_amount
from src.services.pdf_paper import page_css, thermal_width_mm

from .builders import (
    _amount_in_words_indian,
    _e,
    _fmt_currency,
    _fmt_rate,
    _pdf_display_quantity,
    _pdf_display_unit,
    _pdf_unit_price,
    invoice_cancellation_note,
    tcs_label,
)
from .purchase_template import _extract_pan_from_gstin, _is_interstate_supply
from .credit_note_template import CREDIT_NOTE_TYPE_LABELS, DEBIT_NOTE_TYPE_LABELS
from .quotation_template import NOT_A_TAX_INVOICE_NOTE


@dataclass
class ThermalItem:
    name: str
    # Description, discount and serials, one per line.
    sub_lines: list[str] = field(default_factory=list)
    hsn: str = ""
    rate: float | None = None
    qty: str = ""
    unit: str = ""
    price: float | None = None
    amount: float | None = None


@dataclass
class ThermalDoc:
    title: str
    copy_label: str = ""
    # A status stamped under the title: "Cancelled on ...", "Expired on ...".
    mark: str = ""
    company_name: str = ""
    company_lines: list[str] = field(default_factory=list)
    logo_uri: str = ""
    meta: list[tuple[str, str]] = field(default_factory=list)
    party_label: str = "Bill to"
    party_name: str = ""
    party_lines: list[str] = field(default_factory=list)
    ship_lines: list[str] = field(default_factory=list)
    items: list[ThermalItem] = field(default_factory=list)
    show_prices: bool = True
    interstate: bool = False
    # (rate, taxable, IGST or CGST, SGST)
    tax_rows: list[tuple[float, float, float, float]] = field(default_factory=list)
    totals: list[tuple[str, float]] = field(default_factory=list)
    grand_label: str = "Total"
    grand_total: float | None = None
    currency: str = "INR"
    amount_in_words: bool = True
    # (heading, already-escaped HTML) printed above the total, e.g. a receipt's allocations
    lead_blocks: list[tuple[str, str]] = field(default_factory=list)
    # (heading, already-escaped HTML) printed below the total
    blocks: list[tuple[str, str]] = field(default_factory=list)
    qr_uri: str = ""
    qr_caption: str = ""
    footer: str = ""


# ---------------------------------------------------------------------------
# The layout
# ---------------------------------------------------------------------------

def _money(value: float | None, currency: str) -> str:
    return _fmt_currency(float(value or 0), currency)


def _item_html(index: int, item: ThermalItem, doc: ThermalDoc) -> str:
    tags = " · ".join(
        part
        for part in (
            f"HSN {_e(item.hsn)}" if item.hsn else "",
            f"GST {_fmt_rate(item.rate)}%" if item.rate is not None and doc.show_prices else "",
        )
        if part
    )
    subs = "".join(f'<div class="small">{_e(line)}</div>' for line in item.sub_lines if line)
    if doc.show_prices:
        calc = f"{_e(item.qty)} {_e(item.unit)} × {_money(item.price, doc.currency)}"
        line = (
            f'<table class="row"><tr><td class="small">{calc}</td>'
            f'<td class="r b">{_money(item.amount, doc.currency)}</td></tr></table>'
        )
    else:
        line = (
            '<table class="row"><tr><td class="small">Qty</td>'
            f'<td class="r b">{_e(item.qty)} {_e(item.unit)}</td></tr></table>'
        )
    return (
        f'<div class="item"><div class="b">{index}. {_e(item.name)}</div>{subs}'
        + (f'<div class="small">{tags}</div>' if tags else "")
        + line
        + "</div>"
    )


def _tax_summary_html(doc: ThermalDoc, narrow: bool) -> str:
    if not doc.tax_rows or not doc.show_prices:
        return ""
    cur = doc.currency
    if doc.interstate:
        head = "<tr><th>GST%</th><th class='r'>Taxable</th><th class='r'>IGST</th></tr>"
        body = "".join(
            f"<tr><td>{_fmt_rate(rate)}</td><td class='r'>{_money(taxable, cur)}</td>"
            f"<td class='r'>{_money(igst, cur)}</td></tr>"
            for rate, taxable, igst, _ in doc.tax_rows
        )
    elif narrow:
        # 48mm of print width has no room for four columns; CGST and SGST are equal.
        head = "<tr><th>GST%</th><th class='r'>Taxable</th><th class='r'>CGST=SGST</th></tr>"
        body = "".join(
            f"<tr><td>{_fmt_rate(rate)}</td><td class='r'>{_money(taxable, cur)}</td>"
            f"<td class='r'>{_money(cgst, cur)}</td></tr>"
            for rate, taxable, cgst, _ in doc.tax_rows
        )
    else:
        head = (
            "<tr><th>GST%</th><th class='r'>Taxable</th>"
            "<th class='r'>CGST</th><th class='r'>SGST</th></tr>"
        )
        body = "".join(
            f"<tr><td>{_fmt_rate(rate)}</td><td class='r'>{_money(taxable, cur)}</td>"
            f"<td class='r'>{_money(cgst, cur)}</td><td class='r'>{_money(sgst, cur)}</td></tr>"
            for rate, taxable, cgst, sgst in doc.tax_rows
        )
    return f'<div class="hr"></div><div class="lbl">GST summary</div><table class="tax">{head}{body}</table>'


def _build_thermal_html(doc: ThermalDoc, width_mm: int) -> str:
    """One copy of ``doc`` as HTML laid out ``width_mm`` wide."""
    narrow = width_mm < 70
    side_mm = 5 if narrow else 4  # 58mm prints about 48mm wide, 80mm about 72mm
    base_pt = 8 if narrow else 9
    qr_mm = 26 if narrow else 30  # 26mm is still above the ~25mm a QR needs to scan
    cur = doc.currency

    head = []
    if doc.logo_uri:
        head.append(f'<img class="logo" src="{_e(doc.logo_uri)}" alt="" />')
    head.append(f'<div class="co">{_e(doc.company_name)}</div>')
    head += [f'<div class="c small">{_e(line)}</div>' for line in doc.company_lines if line]

    meta = "".join(
        f'<tr><td class="mk">{_e(key)}</td><td class="mv">{_e(value)}</td></tr>' for key, value in doc.meta if value
    )

    party = ""
    if doc.party_name:
        party = (
            f'<div class="hr"></div><div class="lbl">{_e(doc.party_label)}</div>'
            f'<div class="b">{_e(doc.party_name)}</div>'
            + "".join(f'<div class="small">{_e(line)}</div>' for line in doc.party_lines if line)
        )
        if any(doc.ship_lines):
            party += '<div class="lbl gap">Ship to</div>' + "".join(
                f'<div class="small">{_e(line)}</div>' for line in doc.ship_lines if line
            )

    items = "".join(_item_html(i, item, doc) for i, item in enumerate(doc.items, start=1))
    if items:
        items = f'<div class="hr"></div>{items}'

    grand = ""
    if doc.grand_total is not None:
        totals = "".join(
            f'<tr><td>{_e(label)}</td><td class="r">{_money(value, cur)}</td></tr>'
            for label, value in doc.totals
        )
        words = _amount_in_words_indian(float(doc.grand_total), cur) if doc.amount_in_words else ""
        grand = (
            '<div class="hr"></div>'
            + (f'<table class="kv">{totals}</table><div class="hr2"></div>' if totals else "")
            + f'<table class="kv grand"><tr><td>{_e(doc.grand_label)}</td>'
            f'<td class="r">{_money(doc.grand_total, cur)}</td></tr></table>'
            + (f'<div class="small c">{_e(words)}</div>' if words else "")
        )

    def section(pairs) -> str:
        return "".join(
            f'<div class="hr"></div><div class="lbl">{_e(heading)}</div><div class="small">{body}</div>'
            for heading, body in pairs
            if body
        )

    lead_blocks = section(doc.lead_blocks)
    blocks = section(doc.blocks)
    qr = ""
    if doc.qr_uri:
        qr = (
            f'<div class="hr"></div><div class="c"><img class="qr" src="{_e(doc.qr_uri)}" alt="" />'
            f'<div class="small">{_e(doc.qr_caption)}</div></div>'
        )

    return f"""<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<style>
  {page_css("thermal80")}
  * {{ margin: 0; padding: 0; box-sizing: border-box; }}
  html, body {{ color: #000; background: #fff; }}
  body {{
    font-family: 'DejaVu Sans', Arial, 'Noto Sans', 'Noto Sans Devanagari', sans-serif;
    font-size: {base_pt}pt;
    line-height: 1.3;
    padding: 3mm {side_mm}mm 5mm;
    overflow-wrap: anywhere;
  }}
  .c {{ text-align: center; }}
  .r {{ text-align: right; white-space: nowrap; }}
  /* A meta value (several invoice numbers, a long UTR) wraps rather than run off the roll. */
  .mk {{ white-space: nowrap; padding-right: 2mm; }}
  .mv {{ text-align: right; }}
  .b {{ font-weight: 700; }}
  .small {{ font-size: {base_pt - 1}pt; }}
  .logo {{ display: block; margin: 0 auto 1.5mm; max-width: {30 if narrow else 40}mm; max-height: 16mm; }}
  .co {{ text-align: center; font-weight: 700; font-size: {base_pt + 3}pt; line-height: 1.15; margin-bottom: .8mm; }}
  .title {{ text-align: center; font-weight: 700; font-size: {base_pt + 2}pt; letter-spacing: .06em; text-transform: uppercase; }}
  .copy {{ text-align: center; font-size: {base_pt - 1}pt; }}
  .mark {{ text-align: center; font-weight: 700; border: 1px solid #000; margin-top: 1mm; padding: .5mm; }}
  .hr {{ border-top: 1px dashed #000; margin: 2mm 0; }}
  .hr2 {{ border-top: 1.5px solid #000; margin: 1.5mm 0; }}
  .lbl {{ font-size: {base_pt - 1}pt; font-weight: 700; text-transform: uppercase; letter-spacing: .05em; margin-bottom: .5mm; }}
  .lbl.gap {{ margin-top: 1.5mm; }}
  table {{ width: 100%; border-collapse: collapse; }}
  .meta {{ margin-top: 1mm; }}
  .kv td {{ padding: .2mm 0; vertical-align: top; }}
  .grand td {{ font-weight: 700; font-size: {base_pt + 4}pt; }}
  .item {{ padding: 1mm 0; border-bottom: 1px dotted #000; break-inside: avoid; }}
  .item:last-child {{ border-bottom: 0; }}
  .row td {{ padding-top: .3mm; vertical-align: bottom; }}
  .tax {{ font-size: {base_pt - 1}pt; }}
  .tax th {{ text-align: left; border-bottom: 1px solid #000; font-weight: 700; padding-bottom: .4mm; }}
  .tax th.r {{ text-align: right; }}
  .tax td {{ padding: .3mm 0; }}
  .qr {{ width: {qr_mm}mm; height: {qr_mm}mm; display: block; margin: 0 auto 1mm; image-rendering: pixelated; }}
  .foot {{ text-align: center; margin-top: 3mm; font-size: {base_pt - 1}pt; }}
</style>
</head>
<body>
{"".join(head)}
<div class="hr"></div>
<div class="title">{_e(doc.title)}</div>
{f'<div class="copy">{_e(doc.copy_label)}</div>' if doc.copy_label else ""}
{f'<div class="mark">{_e(doc.mark)}</div>' if doc.mark else ""}
<table class="kv small meta">{meta}</table>
{party}
{items}
{_tax_summary_html(doc, narrow)}
{lead_blocks}
{grand}
{blocks}
{qr}
<div class="foot">{_e(doc.footer)}</div>
</body>
</html>"""


def build_thermal_copies(docs: list[ThermalDoc], paper: str) -> list[str]:
    """One HTML string per copy, for ``render_pdf`` to print as one roll page each."""
    width_mm = thermal_width_mm(paper)
    return [_build_thermal_html(doc, width_mm) for doc in docs]


# ---------------------------------------------------------------------------
# Adapters: one per document type, each reading the record the A4 template reads
# ---------------------------------------------------------------------------

def _fmt_date(value) -> str:
    return value.strftime("%d %b %Y") if value else ""


def _join(parts) -> str:
    return " · ".join(part for part in parts if part)


def _company_lines(address, gst, phone, email=None, website=None, additional_info=None) -> list[str]:
    pan = _extract_pan_from_gstin(gst)
    lines = [address or ""]
    if additional_info:
        lines += [line for line in additional_info.split("\n") if line.strip()]
    lines += [
        _join([f"GSTIN {gst}" if gst else "", f"PAN {pan}" if pan else ""]),
        _join([f"Ph {phone}" if phone else "", email or ""]),
        website or "",
    ]
    return lines


def _party_lines(address, gst, phone) -> list[str]:
    return [address or "", _join([f"GSTIN {gst}" if gst else "", f"Ph {phone}" if phone else ""])]


def _logo_uri(data, mime_type) -> str:
    return f"data:{mime_type};base64,{data}" if data and mime_type else ""


def _place_of_supply(code: str | None) -> str:
    return f"{GST_STATE_NAMES.get(code, code)} ({code})" if code else ""


def _tax_rows(items, interstate: bool) -> list[tuple[float, float, float, float]]:
    """Taxable value and tax by GST rate. A row without its own split follows ``interstate``."""
    by_rate: OrderedDict[float, list[float]] = OrderedDict()
    for item in items:
        rate = float(item.gst_rate or 0)
        tax = float(item.tax_amount or 0)
        igst = float(getattr(item, "igst_amount", 0) or 0)
        cgst = float(getattr(item, "cgst_amount", 0) or 0)
        sgst = float(getattr(item, "sgst_amount", 0) or 0)
        if not (igst or cgst or sgst):
            if interstate:
                igst = tax
            else:
                cgst = tax / 2
                sgst = tax - cgst
        row = by_rate.setdefault(rate, [0.0, 0.0, 0.0])
        row[0] += float(item.taxable_amount or 0)
        row[1] += igst if interstate else cgst
        row[2] += 0.0 if interstate else sgst
    return [(rate, *values) for rate, values in sorted(by_rate.items())]


def _gst_totals(doc_row, interstate: bool) -> list[tuple[str, float]]:
    totals = [("Taxable value", float(doc_row.taxable_amount or 0))]
    if interstate:
        totals.append(("IGST", float(doc_row.igst_amount or 0)))
    else:
        totals += [("CGST", float(doc_row.cgst_amount or 0)), ("SGST", float(doc_row.sgst_amount or 0))]
    return totals


def _adjustment_totals(doc_row, currency: str) -> list[tuple[str, float]]:
    """Invoice-level discount, TCS and round off, in the order the A4 totals box prints them."""
    totals: list[tuple[str, float]] = []
    if doc_row.discount_type and float(doc_row.discount_value or 0) > 0:
        label = "Discount"
        if doc_row.discount_type == "percentage":
            label += f" ({_fmt_rate(float(doc_row.discount_value))}%)"
        totals.append((label, -float(invoice_discount_amount(doc_row))))
    tcs = float(getattr(doc_row, "tcs_amount", 0) or 0)
    if tcs:
        totals.append((tcs_label(getattr(doc_row, "tcs_rate", None), getattr(doc_row, "tcs_section_ref", None)), tcs))
    round_off = float(doc_row.round_off_amount or 0)
    if doc_row.apply_round_off and round_off:
        totals.append(("Round off", round_off))
    return totals


def _item_discount_line(item, currency: str, tax_inclusive: bool) -> str:
    raw = float(item.discount_value or 0)
    if not item.discount_type or raw <= 0:
        return ""
    amount = float(item_discount_amount(item, tax_inclusive=tax_inclusive))
    if item.discount_type == "percentage":
        return f"Disc: {_fmt_rate(raw)}% (-{_fmt_currency(amount, currency)})"
    return f"Disc: {_fmt_currency(amount, currency)} off"


def _line_items(doc_row, products, *, currency: str, serials=None, taxable_only=False, discounts=True):
    product_map = {product.id: product for product in products}
    tax_inclusive = bool(getattr(doc_row, "tax_inclusive", False))
    serials = serials or {}
    items = []
    for item in doc_row.items or []:
        prod = product_map.get(item.product_id)
        sub_lines = [item.description or ""]
        if discounts:
            sub_lines.append(_item_discount_line(item, currency, tax_inclusive))
        if serials.get(item.product_id):
            sub_lines.append("IMEI/SN: " + ", ".join(serials[item.product_id]))
        items.append(
            ThermalItem(
                name=prod.name if prod else f"Product #{item.product_id}",
                sub_lines=sub_lines,
                hsn=item.hsn_sac or (prod.hsn_sac if prod else None) or "",
                rate=float(item.gst_rate or 0),
                qty=_pdf_display_quantity(item.quantity, getattr(prod, "allow_decimal", None) if prod else None),
                unit=_pdf_display_unit(getattr(prod, "unit", None) if prod else None),
                price=float(item.unit_price or 0) if taxable_only else _pdf_unit_price(item, tax_inclusive=tax_inclusive),
                amount=float((item.taxable_amount if taxable_only else item.line_total) or 0),
            )
        )
    return items


def _lines_html(text: str | None) -> str:
    return "<br>".join(_e(line) for line in (text or "").split("\n") if line.strip())


def _bank_accounts_html(accounts) -> str:
    return "<br>".join(
        _join([
            _e(account.bank_name or getattr(account, "display_name", None) or ""),
            f"A/c <b>{_e(account.account_number)}</b>" if account.account_number else "",
            f"IFSC <b>{_e(account.ifsc_code)}</b>" if account.ifsc_code else "",
        ])
        for account in accounts
    )


def thermal_invoice_doc(
    invoice,
    products,
    *,
    bank_accounts=(),
    copy_label: str = "",
    serials=None,
    qr_uri: str = "",
    settlement: dict[str, float] | None = None,
) -> ThermalDoc:
    """A sales invoice, or a purchase bill with the supplier as the party."""
    purchase = invoice.voucher_type == "purchase"
    cancelled = getattr(invoice, "status", None) == "cancelled"
    currency = resolve_currency_code(invoice.company_currency_code)
    place_of_supply = getattr(invoice, "place_of_supply", None)
    if purchase:
        interstate = _is_interstate_supply(invoice.company_gst, invoice.ledger_gst)
    else:
        interstate = (
            invoice_is_interstate(invoice) if place_of_supply
            else _is_interstate_supply(invoice.company_gst, invoice.ledger_gst)
        )

    meta = [
        ("No.", invoice.invoice_number or f"#{invoice.id}"),
        ("Date", _fmt_date(invoice.invoice_date or invoice.created_at)),
    ]
    if purchase:
        meta.append(("Supplier bill", invoice.supplier_invoice_number or ""))
    else:
        meta.append(("Due", _fmt_date(getattr(invoice, "due_date", None))))
        meta.append(("Place of supply", _place_of_supply(place_of_supply)))
        source_challan = getattr(invoice, "source_challan", None)
        if source_challan is not None:
            meta.append(("Challan", source_challan.challan_number or ""))

    blocks: list[tuple[str, str]] = []
    if invoice.reference_notes:
        blocks.append(("Reference notes", _e(invoice.reference_notes)))
    if not purchase and bank_accounts:
        blocks.append(("Bank details", _bank_accounts_html(bank_accounts)))
    if settlement and float(settlement.get("tds_amount") or 0) > 0:
        blocks.append((
            "Settlement",
            "<br>".join([
                f"Paid to supplier: {_fmt_currency(float(settlement.get('paid_amount') or 0), currency)}",
                f"TDS deducted: {_fmt_currency(float(settlement['tds_amount']), currency)}",
                f"Balance: {_fmt_currency(float(settlement.get('remaining_amount') or 0), currency)}",
            ]),
        ))
    if not purchase and invoice.company_terms_text:
        blocks.append(("Terms & conditions", _lines_html(invoice.company_terms_text)))

    company_name = invoice.company_name or ""
    if purchase:
        title = "Purchase Bill"
    else:
        title = "Tax Invoice" if invoice.ledger_gst else "Sales Invoice"
    return ThermalDoc(
        title=title,
        copy_label=copy_label,
        mark=invoice_cancellation_note(invoice),
        company_name=company_name,
        company_lines=_company_lines(
            invoice.company_address,
            invoice.company_gst,
            invoice.company_phone,
            invoice.company_email,
            invoice.company_website,
            invoice.company_additional_info,
        ),
        logo_uri=_logo_uri(invoice.company_logo_data, invoice.company_logo_mime_type),
        meta=meta,
        party_label="Supplier" if purchase else "Bill to",
        party_name=invoice.ledger_name or "",
        party_lines=_party_lines(invoice.ledger_address, invoice.ledger_gst, invoice.ledger_phone),
        ship_lines=(
            [invoice.shipping_address_label or "", invoice.shipping_address]
            if invoice.shipping_address and not purchase
            else []
        ),
        items=_line_items(invoice, products, currency=currency, serials=serials),
        interstate=interstate,
        tax_rows=_tax_rows(invoice.items or [], interstate),
        totals=_gst_totals(invoice, interstate) + _adjustment_totals(invoice, currency),
        grand_label="Cancelled invoice total" if cancelled else "Total",
        grand_total=float(invoice.total_amount or 0),
        currency=currency,
        blocks=blocks,
        # A purchase bill is ours to pay, not the supplier's: never a pay QR, as on A4.
        qr_uri="" if purchase or cancelled else qr_uri,
        qr_caption="Scan to view and pay online" if qr_uri and not purchase and not cancelled else "",
        footer=f"{'Received' if purchase else 'Authorised'} by {company_name}",
    )


def thermal_credit_note_doc(credit_note, invoices, products, company, ledger) -> ThermalDoc:
    """A credit note, or a debit note when the note is inward.

    The seller and party come from the first referenced invoice's snapshot, falling
    back to the profile, exactly as the A4 template does.
    """
    inward = credit_note.direction == "inward"
    first = invoices[0] if invoices else None

    def pick(invoice_attr: str, fallback):
        return (getattr(first, invoice_attr, None) if first else None) or fallback

    currency = pick("company_currency_code", company.currency_code if company else None) or "INR"
    seller_name = pick("company_name", company.name if company else None) or ""
    seller_gst = pick("company_gst", company.gst if company else None)
    party_gst = pick("ledger_gst", ledger.gst if ledger else None)

    # The note's own tax heads decide the split; credit note items carry no split.
    if float(credit_note.igst_amount or 0) > 0:
        interstate = True
    elif float(credit_note.cgst_amount or 0) + float(credit_note.sgst_amount or 0) > 0:
        interstate = False
    else:
        interstate = _is_interstate_supply(seller_gst, ledger.gst if ledger else party_gst)

    product_map = {product.id: product for product in products}
    is_discount = credit_note.credit_note_type == "discount"
    items = []
    for item in credit_note.items or []:
        prod = product_map.get(item.product_id)
        name = prod.name if prod else f"Product #{item.product_id}"
        invoice_item = item.invoice_item
        items.append(
            ThermalItem(
                name=f"Discount on {name}" if is_discount else name,
                hsn=(invoice_item.hsn_sac if invoice_item else None) or (prod.hsn_sac if prod else None) or "",
                rate=float(item.gst_rate or 0),
                qty=_pdf_display_quantity(item.quantity, getattr(prod, "allow_decimal", None) if prod else None),
                unit=_pdf_display_unit(getattr(prod, "unit", None) if prod else None),
                price=float(item.unit_price or 0),
                amount=float(item.line_total or 0),
            )
        )

    def reference(invoice) -> str:
        # A debit note cites the supplier's invoice number, as on A4.
        number = (invoice.supplier_invoice_number if inward else None) or invoice.invoice_number
        return number or f"#{invoice.id}"

    type_labels = DEBIT_NOTE_TYPE_LABELS if inward else CREDIT_NOTE_TYPE_LABELS
    label = "Debit Note" if inward else "Credit Note"
    # Each invoice with its date, as on A4: rule 53(1A) asks for both.
    meta = [
        ("No.", credit_note.credit_note_number or ""),
        ("Date", _fmt_date(getattr(credit_note, "credit_note_date", None) or credit_note.created_at)),
        ("Type", type_labels.get(credit_note.credit_note_type, label.capitalize())),
        ("Against", ", ".join(
            f"{reference(invoice)} ({_fmt_date(invoice.invoice_date) or 'N/A'})" for invoice in invoices
        )),
    ]
    if inward and credit_note.supplier_credit_note_number:
        supplier_date = credit_note.supplier_credit_note_date
        meta.append((
            "Supplier's note",
            credit_note.supplier_credit_note_number + (f" ({_fmt_date(supplier_date)})" if supplier_date else ""),
        ))

    totals = _gst_totals(credit_note, interstate)
    tcs = float(getattr(credit_note, "tcs_amount", 0) or 0)
    if tcs:
        totals.append(("TCS reversed", tcs))

    cancelled = credit_note.status == "cancelled"
    return ThermalDoc(
        title=label,
        mark=f"Cancelled on {_fmt_date(to_india_date(credit_note.cancelled_at))}" if cancelled else "",
        company_name=seller_name,
        company_lines=_company_lines(
            pick("company_address", company.address if company else None),
            seller_gst,
            pick("company_phone", company.phone_number if company else None),
            pick("company_email", company.email if company else None),
            pick("company_website", company.website if company else None),
        ),
        logo_uri=_logo_uri(
            pick("company_logo_data", company.logo_data if company else None),
            pick("company_logo_mime_type", company.logo_mime_type if company else None),
        ),
        meta=meta,
        party_label="Issued to",
        party_name=pick("ledger_name", ledger.name if ledger else None) or "",
        party_lines=_party_lines(
            pick("ledger_address", ledger.address if ledger else None),
            party_gst,
            pick("ledger_phone", ledger.phone_number if ledger else None),
        ),
        items=items,
        interstate=interstate,
        # Credit note items have no CGST/SGST/IGST columns, so the rows follow the note.
        tax_rows=_tax_rows(credit_note.items or [], interstate),
        totals=totals,
        grand_label=f"Total {'debit' if inward else 'credit'}",
        grand_total=float(credit_note.total_amount or 0),
        currency=currency,
        blocks=[("Reason", _e(credit_note.reason or ""))],
        footer=f"Authorised by {seller_name}",
    )


def thermal_challan_doc(challan, products, *, copy_label: str = "", show_sku: bool = True) -> ThermalDoc:
    """A delivery challan: lines and total at taxable value and no GST summary, as on A4."""
    currency = challan.company_currency_code or "INR"
    items = _line_items(challan, products, currency=currency, taxable_only=True, discounts=False)
    # A challan is not a tax document: no rate on any line, as on A4.
    for item in items:
        item.rate = None
    if show_sku:
        product_map = {product.id: product for product in products}
        for item, line in zip(items, challan.items or []):
            prod = product_map.get(line.product_id)
            if prod and prod.sku:
                item.name = f"{item.name} ({prod.sku})"
    blocks = []
    if challan.reference_notes:
        blocks.append(("Notes", _e(challan.reference_notes)))
    if challan.terms_text:
        blocks.append(("Terms & conditions", _lines_html(challan.terms_text)))
    blocks.append(("Received by", "Signature:<br><br>Name:<br>Date:"))
    company_name = challan.company_name or ""
    return ThermalDoc(
        title="Delivery Challan",
        copy_label=copy_label,
        mark=f"Cancelled on {_fmt_date(to_india_date(challan.cancelled_at))}" if challan.status == CHALLAN_CANCELLED else "",
        company_name=company_name,
        company_lines=_company_lines(
            challan.company_address,
            challan.company_gst,
            challan.company_phone,
            additional_info=challan.company_additional_info,
        ),
        logo_uri=_logo_uri(challan.company_logo_data, challan.company_logo_mime_type),
        meta=[
            ("No.", challan.challan_number or ""),
            ("Date", _fmt_date(challan.challan_date)),
            ("Place of supply", _place_of_supply(challan.place_of_supply)),
            ("Purpose", challan.purpose_label or ""),
        ],
        party_label="Consignee",
        party_name=challan.ledger_name or "",
        party_lines=[
            challan.ledger_address or "",
            _join([
                f"GSTIN {challan.ledger_gst}" if challan.ledger_gst else "Unregistered",
                f"Ph {challan.ledger_phone}" if challan.ledger_phone else "",
            ]),
        ],
        ship_lines=(
            [challan.shipping_address_label or "", challan.shipping_address] if challan.shipping_address else []
        ),
        items=items,
        grand_label="Total value",
        grand_total=float(challan.taxable_amount or 0),
        currency=currency,
        amount_in_words=currency == "INR",
        blocks=blocks,
        footer=f"For {company_name} · Authorised signatory",
    )


def thermal_quotation_doc(quotation, products, bank_accounts=(), *, today=None) -> ThermalDoc:
    """A quotation or proforma invoice, with the fixed "not a tax invoice" note."""
    today = today or india_today()
    is_proforma = quotation.document_type == DOCUMENT_PROFORMA
    title = "Proforma Invoice" if is_proforma else "Quotation"
    currency = resolve_currency_code(quotation.company_currency_code)
    interstate = _is_interstate_supply(quotation.company_gst, quotation.ledger_gst)

    mark = ""
    if quotation.status == STATUS_CANCELLED:
        mark = f"Cancelled on {_fmt_date(to_india_date(quotation.cancelled_at))}"
    elif quotation.is_expired_on(today):
        mark = f"Expired on {_fmt_date(quotation.valid_until)}"

    blocks = []
    if quotation.reference_notes:
        blocks.append(("Reference", _e(quotation.reference_notes)))
    if is_proforma:
        if bank_accounts:
            blocks.append(("Bank details", _bank_accounts_html(bank_accounts)))
        elif quotation.company_bank_name or quotation.company_account_number:
            blocks.append(("Bank details", _join([
                _e(quotation.company_bank_name or ""),
                f"A/c <b>{_e(quotation.company_account_number)}</b>" if quotation.company_account_number else "",
                f"IFSC <b>{_e(quotation.company_ifsc_code)}</b>" if quotation.company_ifsc_code else "",
            ])))
    if quotation.company_terms_text:
        blocks.append(("Terms & conditions", _lines_html(quotation.company_terms_text)))
    validity = ""
    if quotation.valid_until and not is_proforma:
        verb = "were" if quotation.is_expired_on(today) else "are"
        validity = f" Prices {verb} valid until {_fmt_date(quotation.valid_until)}."
    blocks.append(("Not a tax invoice", _e(NOT_A_TAX_INVOICE_NOTE + validity)))

    company_name = quotation.company_name or ""
    return ThermalDoc(
        title=title,
        mark=mark,
        company_name=company_name,
        company_lines=_company_lines(
            quotation.company_address,
            quotation.company_gst,
            quotation.company_phone,
            quotation.company_email,
            quotation.company_website,
            quotation.company_additional_info,
        ),
        logo_uri=_logo_uri(quotation.company_logo_data, quotation.company_logo_mime_type),
        meta=[
            ("No.", quotation.quotation_number or ""),
            ("Date", _fmt_date(quotation.quotation_date)),
            ("Valid until", _fmt_date(quotation.valid_until)),
        ],
        party_label="Proforma for" if is_proforma else "Quotation for",
        party_name=quotation.ledger_name or "",
        party_lines=_party_lines(quotation.ledger_address, quotation.ledger_gst, quotation.ledger_phone),
        ship_lines=(
            [quotation.shipping_address_label or "", quotation.shipping_address]
            if quotation.shipping_address
            else []
        ),
        items=_line_items(quotation, products, currency=currency),
        interstate=interstate,
        tax_rows=_tax_rows(quotation.items or [], interstate),
        totals=_gst_totals(quotation, interstate) + _adjustment_totals(quotation, currency),
        grand_label=f"{title} total",
        grand_total=float(quotation.total_amount or 0),
        currency=currency,
        blocks=blocks,
        footer=f"For {company_name}",
    )


def thermal_receipt_doc(payment, company) -> ThermalDoc:
    """A receipt or payment voucher: the amount, how it was paid and what it settled."""
    currency = (company.currency_code or "INR") if company else "INR"
    is_receipt = payment.voucher_type == "receipt"
    ledger = payment.ledger
    # What the money settled, in a section of its own above the amount, as on A4:
    # these lines are not a breakdown of the amount, so they sit apart from it.
    rows = []
    allocated_total = Decimal("0")
    tds_total = Decimal("0")
    for allocation in payment.invoice_allocations:
        invoice = allocation.invoice
        number = invoice.invoice_number if invoice and invoice.invoice_number else f"#{allocation.invoice_id}"
        amount = Decimal(str(allocation.allocated_amount or 0))
        tds = Decimal(str(getattr(allocation, "tds_amount", 0) or 0))
        allocated_total += amount
        tds_total += tds
        rows.append(f'<tr><td>{_e(number)}</td><td class="r">{_money(float(amount), currency)}</td></tr>')
        if tds > 0:
            section = getattr(allocation, "tds_section_ref", None)
            tds_label = "TDS deducted" + (f" (s.{_e(section)})" if section else "")
            rows.append(f'<tr><td>&nbsp;&nbsp;{tds_label}</td><td class="r">{_money(float(tds), currency)}</td></tr>')
    allocations_html = ""
    if rows:
        rows.append(
            f'<tr class="b"><td>Total allocated</td><td class="r">{_money(float(allocated_total), currency)}</td></tr>'
        )
        if tds_total > 0:
            rows.append(
                f'<tr class="b"><td>Total TDS deducted</td><td class="r">{_money(float(tds_total), currency)}</td></tr>'
            )
        allocations_html = f'<table class="kv">{"".join(rows)}</table>'
    account = payment.account
    company_name = company.name if company else "Company"
    dt = payment.date
    return ThermalDoc(
        title="Receipt" if is_receipt else "Payment Voucher",
        mark="Cancelled" if payment.status == "cancelled" else "",
        company_name=company_name,
        company_lines=(
            _company_lines(company.address, company.gst, company.phone_number, company.email) if company else []
        ),
        logo_uri=_logo_uri(company.logo_data, company.logo_mime_type) if company else "",
        meta=[
            ("No.", payment.payment_number or f"#{payment.id}"),
            ("Date", dt.strftime("%d %b %Y %H:%M") if dt else ""),
            ("Mode", (payment.mode or "").title()),
            ("Reference", payment.reference or ""),
        ],
        party_label="Received from" if is_receipt else "Paid to",
        party_name=ledger.name if ledger else "Unknown",
        party_lines=_party_lines(ledger.address, ledger.gst, ledger.phone_number) if ledger else [],
        lead_blocks=[("Allocated to invoices", allocations_html)],
        grand_label="Amount received" if is_receipt else "Amount paid",
        grand_total=float(payment.amount or 0),
        currency=currency,
        blocks=[
            ("Account", _e(account.display_name) if account else "Unallocated"),
            ("Notes", _e(payment.notes or "")),
        ],
        footer=f"Authorised by {company_name}",
    )
