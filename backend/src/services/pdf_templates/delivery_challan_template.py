"""Delivery challan HTML template.

A delivery challan lists goods sent to a buyer. It is not a bill, so it has its own
template rather than branches in ``_build_invoice_html``, which is how "Tax Invoice"
would slip onto it. It prints the particulars Rule 55 of the CGST Rules asks for:
number, date, consignor and consignee name, address and GSTIN, place of supply,
HSN, description, quantity and taxable value, plus the three copy labels
(original for the consignee, duplicate for the transporter, triplicate for the consignor).

The tax amounts are stored on a challan (the e-way bill and the invoice made from it
need them) but never printed, and nothing here asks the buyer to pay.
``tests/services/test_delivery_challan_pdf_template.py`` enforces this.
"""

from src.core.validation import GST_STATE_NAMES
from src.models.delivery_challan import STATUS_CANCELLED
from src.models.product import Product
from src.services.gst_tax_service import to_india_date

from .builders import (
    _address_html,
    _amount_in_words_indian,
    _e,
    _fmt_currency,
    _pdf_display_quantity,
    _pdf_display_unit,
    document_paper_css,
)

CHALLAN_COPY_LABELS = ("Original for consignee", "Duplicate for transporter", "Triplicate for consignor")
MAX_CHALLAN_COPIES = 3


def _fmt_date(value) -> str:
    return value.strftime("%d %b %Y") if value else "N/A"


def _join(parts: list[str]) -> str:
    return " &middot; ".join(part for part in parts if part)


def _place_of_supply(code: str | None) -> str:
    if not code:
        return ""
    name = GST_STATE_NAMES.get(code)
    return f"{name} ({code})" if name else code


def _build_delivery_challan_html(
    challan,
    products: list[Product],
    *,
    copy_label: str = CHALLAN_COPY_LABELS[0],
    show_sku: bool = True,
    paper: str = "a4",
) -> str:
    """Generate HTML for one copy of a delivery challan, for A4 or A5 ``paper``."""
    page_rule, paper_css = document_paper_css(paper)
    currency = challan.company_currency_code or "INR"
    product_map = {product.id: product for product in products}
    cancelled = challan.status == STATUS_CANCELLED

    item_rows = ""
    for idx, item in enumerate(challan.items or [], start=1):
        prod = product_map.get(item.product_id)
        name = _e(prod.name) if prod else f"Product #{item.product_id}"
        if show_sku and prod and prod.sku:
            name += f' <span class="muted-text">({_e(prod.sku)})</span>'
        description = _e(item.description)
        product_cell = f'{name}<br><span class="muted-text">{description}</span>' if description else name
        hsn = _e(item.hsn_sac or (prod.hsn_sac if prod else None) or "N/A")
        unit = _e(_pdf_display_unit(getattr(prod, "unit", None) if prod else None))
        quantity = _pdf_display_quantity(item.quantity, getattr(prod, "allow_decimal", None) if prod else None)
        item_rows += f"""
        <tr>
          <td>{idx}</td>
          <td>{product_cell}</td>
          <td class="nowrap">{hsn}</td>
          <td class="right">{quantity}</td>
          <td>{unit}</td>
          <td class="right">{_fmt_currency(float(item.unit_price or 0), currency)}</td>
          <td class="right">{_fmt_currency(float(item.taxable_amount or 0), currency)}</td>
        </tr>"""

    logo_html = ""
    if challan.company_logo_data and challan.company_logo_mime_type:
        logo_html = (
            '<div class="sheet__logo">'
            f'<img src="data:{_e(challan.company_logo_mime_type)};base64,{_e(challan.company_logo_data)}" '
            'alt="Company logo" class="sheet__logo-img" />'
            "</div>"
        )
    info_html = ""
    if challan.company_additional_info:
        lines = "<br>".join(_e(line) for line in challan.company_additional_info.split("\n"))
        info_html = f'<div class="sheet__company-info">{lines}</div>'

    consignor_gstin = f"GSTIN: {_e(challan.company_gst)}" if challan.company_gst else ""
    consignor_phone = f"Phone: {_e(challan.company_phone)}" if challan.company_phone else ""
    consignee_gstin = f"GSTIN: {_e(challan.ledger_gst)}" if challan.ledger_gst else "Unregistered"
    consignee_phone = f"Phone: {_e(challan.ledger_phone)}" if challan.ledger_phone else ""

    place = _place_of_supply(challan.place_of_supply)
    place_html = f"<p>Place of supply: {_e(place)}</p>" if place else ""

    ship_to_html = ""
    if challan.shipping_address:
        ship_label = f"<h4>{_e(challan.shipping_address_label)}</h4>" if challan.shipping_address_label else ""
        ship_to_html = f"""
    <div class="sheet__party">
      <p class="eyebrow">Ship to</p>
      {ship_label}
      <p>{_e(challan.shipping_address)}</p>
    </div>"""

    notes_html = ""
    if challan.reference_notes:
        notes_html = f"""
  <section class="sheet__note">
    <p class="eyebrow">Notes</p>
    <p>{_e(challan.reference_notes)}</p>
  </section>"""

    terms_html = ""
    if challan.terms_text:
        terms_items = "".join(
            f'<div class="sheet__terms-item">{_e(line)}</div>'
            for line in challan.terms_text.split("\n")
            if line.strip()
        )
        if terms_items:
            terms_html = f"""
  <section class="sheet__terms">
    <p class="eyebrow">Terms &amp; Conditions</p>
    {terms_items}
  </section>"""

    mark_html = ""
    if cancelled:
        mark_html = f'<div class="sheet__mark">CANCELLED on {_fmt_date(to_india_date(challan.cancelled_at))}</div>'

    total_value = float(challan.taxable_amount or 0)
    words_html = (
        f'<p class="sheet__amount-words">{_amount_in_words_indian(total_value, currency)}</p>'
        if currency == "INR"
        else ""
    )
    company_name = _e(challan.company_name) or "Company"

    return f"""<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<style>
  {page_rule}
  * {{ margin: 0; padding: 0; box-sizing: border-box; }}
  body {{
    font-family: -apple-system, 'Segoe UI', Roboto, Helvetica, Arial, 'Noto Sans', 'Noto Sans Devanagari', sans-serif;
    font-size: 10px;
    color: #1f2937;
    line-height: 1.5;
  }}
  .eyebrow {{
    font-size: 8px;
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: 0.08em;
    color: #6b7280;
    margin-bottom: 2px;
  }}
  .sheet__copy {{
    text-align: right;
    font-size: 9px;
    font-weight: 600;
    color: #4b5563;
    margin-bottom: 4px;
  }}
  .sheet__title {{
    text-align: center;
    font-size: 18px;
    font-weight: 700;
    letter-spacing: 0.06em;
    text-transform: uppercase;
    white-space: nowrap;
    padding-bottom: 10px;
    border-bottom: 2px solid #e5e7eb;
    margin-bottom: 12px;
  }}
  .sheet__mark {{
    text-align: center;
    font-size: 12px;
    font-weight: 700;
    letter-spacing: 0.08em;
    color: #b91c1c;
    border: 2px solid #b91c1c;
    border-radius: 6px;
    padding: 6px;
    margin-bottom: 16px;
  }}
  .sheet__header {{
    display: flex;
    justify-content: space-between;
    align-items: flex-start;
    padding-bottom: 16px;
    border-bottom: 2px solid #e5e7eb;
    margin-bottom: 16px;
  }}
  .sheet__header h3 {{
    font-size: 16px;
    font-weight: 700;
    margin-bottom: 4px;
  }}
  .sheet__header p {{
    font-size: 9px;
    color: #6b7280;
    margin-bottom: 1px;
  }}
  .sheet__meta {{
    text-align: right;
  }}
  .sheet__meta h2 {{
    font-size: 14px;
    font-weight: 700;
    margin-bottom: 2px;
  }}
  .sheet__parties {{
    display: flex;
    gap: 12px;
    margin-bottom: 16px;
  }}
  .sheet__party {{
    flex: 1;
    background: #f9fafb;
    border: 1px solid #e5e7eb;
    border-radius: 6px;
    padding: 12px 14px;
  }}
  .sheet__party h4 {{
    font-size: 12px;
    font-weight: 600;
    margin-bottom: 2px;
  }}
  .sheet__party p {{
    font-size: 9px;
    color: #4b5563;
    margin-bottom: 1px;
  }}
  .sheet__note {{
    border: 1px dashed #d1d5db;
    border-radius: 6px;
    padding: 10px 14px;
    margin-bottom: 14px;
    background: #f9fafb;
    font-size: 9px;
    color: #374151;
  }}
  .sheet__table {{
    width: 100%;
    border-collapse: collapse;
    table-layout: fixed;
    margin-bottom: 16px;
    font-size: 8px;
  }}
  .sheet__table thead th {{
    background: #f3f4f6;
    color: #374151;
    font-weight: 600;
    font-size: 7px;
    text-transform: uppercase;
    letter-spacing: 0.04em;
    padding: 5px 4px;
    border-bottom: 2px solid #d1d5db;
    text-align: left;
  }}
  .sheet__table th.right, .sheet__table td.right {{
    text-align: right;
  }}
  .sheet__table tbody td {{
    padding: 5px 4px;
    border-bottom: 1px solid #e5e7eb;
    overflow-wrap: anywhere;
  }}
  .sheet__table td.nowrap {{
    overflow-wrap: normal;
    white-space: nowrap;
  }}
  .sheet__table tbody tr {{
    break-inside: avoid;
    page-break-inside: avoid;
  }}
  .sheet__totals {{
    margin-left: auto;
    width: 230px;
    text-align: right;
    break-inside: avoid;
    page-break-inside: avoid;
  }}
  .sheet__total-value {{
    font-size: 18px;
    font-weight: 700;
    margin: 4px 0;
  }}
  .sheet__amount-words {{
    font-size: 8px;
    font-style: italic;
    color: #374151;
  }}
  .muted-text {{
    font-size: 8px;
    color: #9ca3af;
  }}
  .sheet__logo {{
    margin-bottom: 8px;
  }}
  .sheet__logo-img {{
    max-width: 180px;
    max-height: 80px;
    object-fit: contain;
  }}
  .sheet__company-info {{
    font-size: 9px;
    color: #4b5563;
    margin-bottom: 6px;
  }}
  .sheet__terms {{
    border-top: 1px solid #e5e7eb;
    margin-top: 16px;
    padding-top: 10px;
    font-size: 9px;
    color: #4b5563;
    break-inside: avoid;
    page-break-inside: avoid;
  }}
  .sheet__signatures {{
    display: flex;
    justify-content: space-between;
    gap: 40px;
    margin-top: 48px;
    break-inside: avoid;
    page-break-inside: avoid;
  }}
  .sheet__signature {{
    flex: 1;
    font-size: 9px;
    color: #374151;
  }}
  .sheet__signature--right {{
    text-align: right;
  }}
  .sheet__signature-space {{
    height: 40px;
  }}
  .sheet__signature-line {{
    border-top: 1px solid #9ca3af;
    padding-top: 3px;
    margin-bottom: 8px;
  }}
{paper_css}</style>
</head>
<body>
<div class="sheet">
  <div class="sheet__copy">{_e(copy_label)}</div>
  <div class="sheet__title">Delivery Challan</div>
  {mark_html}
  <header class="sheet__header">
    <div>
      <p class="eyebrow">Consignor</p>
      {logo_html}
      {info_html}
      <h3>{_e(challan.company_name) or 'Company not set'}</h3>
      {_address_html(challan.company_address)}
      <p>{_join([consignor_gstin, consignor_phone])}</p>
    </div>
    <div class="sheet__meta">
      <h2>{_e(challan.challan_number)}</h2>
      <p>Challan date: {_fmt_date(challan.challan_date)}</p>
      {place_html}
      <p>Purpose: {_e(challan.purpose_label)}</p>
    </div>
  </header>

  <div class="sheet__parties">
    <div class="sheet__party">
      <p class="eyebrow">Consignee</p>
      <h4>{_e(challan.ledger_name) or 'Unknown ledger'}</h4>
      {_address_html(challan.ledger_address)}
      <p>{_join([consignee_gstin, consignee_phone])}</p>
    </div>{ship_to_html}
  </div>

  {notes_html}

  <section>
    <table class="sheet__table">
      <colgroup>
        <col style="width: 5%">
        <col style="width: 37%">
        <col style="width: 12%">
        <col style="width: 10%">
        <col style="width: 9%">
        <col style="width: 13%">
        <col style="width: 14%">
      </colgroup>
      <thead>
        <tr>
          <th>#</th>
          <th>Description of goods</th>
          <th>HSN/SAC</th>
          <th class="right">Qty</th>
          <th>Unit</th>
          <th class="right">Rate</th>
          <th class="right">Taxable value</th>
        </tr>
      </thead>
      <tbody>
        {item_rows}
      </tbody>
    </table>
  </section>

  <section class="sheet__totals">
    <p class="eyebrow">Total value</p>
    <p class="sheet__total-value">{_fmt_currency(total_value, currency)}</p>
    {words_html}
  </section>

  {terms_html}

  <section class="sheet__signatures">
    <div class="sheet__signature">
      <div class="sheet__signature-space"></div>
      <p class="sheet__signature-line">Received by (signature)</p>
      <p>Name:</p>
      <p>Date:</p>
    </div>
    <div class="sheet__signature sheet__signature--right">
      <p>For {company_name}</p>
      <div class="sheet__signature-space"></div>
      <p class="sheet__signature-line">Authorised signatory</p>
    </div>
  </section>
</div>
</body>
</html>"""


def _build_multi_copy_delivery_challan_html(
    challan,
    products: list[Product],
    copies: int,
    *,
    show_sku: bool = True,
    paper: str = "a4",
) -> str:
    """One page per copy, joined the way ``_build_multi_copy_invoice_html`` joins them."""
    copies = max(1, min(MAX_CHALLAN_COPIES, copies))
    if copies == 1:
        return _build_delivery_challan_html(challan, products, copy_label=CHALLAN_COPY_LABELS[0], show_sku=show_sku, paper=paper)

    pages = []
    first_html: str | None = None
    for i in range(copies):
        full_html = _build_delivery_challan_html(challan, products, copy_label=CHALLAN_COPY_LABELS[i], show_sku=show_sku, paper=paper)
        if i == 0:
            first_html = full_html
        body_open_end = full_html.index("<body>") + len("<body>")
        body_close_start = full_html.rindex("</body>")
        body_content = full_html[body_open_end:body_close_start].strip()
        page_style = "" if i == copies - 1 else ' style="break-after: page; page-break-after: always;"'
        pages.append(f"<div{page_style}>\n{body_content}\n</div>")

    assert first_html is not None
    body_open_end = first_html.index("<body>") + len("<body>")
    return first_html[:body_open_end] + "\n" + "\n".join(pages) + "\n</body>\n</html>"
