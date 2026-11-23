"""Every transaction PDF prints on A4, A5 and 80mm and 58mm thermal rolls.

The page size is read back from WeasyPrint's laid-out document, and every box on
every page is checked to stay inside the page width: a table that runs past the
edge of A5, or a line that runs past the edge of a roll, is cut off silently when
printed. The worst case is an invoice with 40 items, long unbroken names, CGST +
SGST, discounts, TCS, round off, two bank accounts, the pay QR, a logo and long
terms.

The report routes (A4 and A5 only) are covered in test_report_pdf_paper.py.
"""

from __future__ import annotations

import base64
from io import BytesIO
import shutil
import subprocess
from datetime import date, datetime
from decimal import Decimal

import pytest
import weasyprint

from src.models.buyer import Buyer
from src.models.company import CompanyProfile
from src.models.company_account import CompanyAccount
from src.models.credit_note import CreditNote, CreditNoteItem
from src.models.delivery_challan import DeliveryChallan, DeliveryChallanItem
from src.models.invoice import Invoice, InvoiceItem
from src.models.payment import Payment, PaymentInvoiceAllocation
from src.models.product import Product
from src.models.quotation import Quotation, QuotationItem
from src.services import pdf_paper
from src.services.pdf_paper import page_css, render_pdf, resolve_paper
from src.services.pdf_templates import (
    _build_credit_note_html,
    _build_multi_copy_delivery_challan_html,
    _build_multi_copy_invoice_html,
    _build_quotation_html,
)
from src.services.pdf_templates.builders import _build_pdf_pay_qr_card_html
from src.services.pdf_templates.thermal_template import (
    build_thermal_copies,
    thermal_challan_doc,
    thermal_credit_note_doc,
    thermal_invoice_doc,
    thermal_quotation_doc,
    thermal_receipt_doc,
)
from src.services.upi import render_qr_png_data_uri

PX_PER_MM = 96 / 25.4
SHEETS_MM = {"a4": (210, 297), "a5": (148, 210)}
ROLLS_MM = {"thermal80": 80, "thermal58": 58}

# A 1x1 PNG is enough to exercise the logo's box.
LOGO = base64.b64encode(
    bytes.fromhex(
        "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c4890000000d4944415478da63f8ffff3f0005fe02fea7d6a4a90000000049454e44ae426082"
    )
).decode()
QR = render_qr_png_data_uri("https://app.example.com/s/token?src=qr")
LONG_NAME = "Supercalifragilisticexpialidocious" * 3


# ---------------------------------------------------------------------------
# Records
# ---------------------------------------------------------------------------

def _items(count: int, *, interstate: bool, cls=InvoiceItem) -> list:
    items = []
    for i in range(count):
        taxable = Decimal("123456.78") if i % 7 == 0 else Decimal("2800.00")
        tax = (taxable * Decimal("0.18")).quantize(Decimal("0.01"))
        kwargs = dict(
            product_id=i % 3 + 1,
            quantity=Decimal("12") if i % 2 else Decimal("2.5"),
            unit_price=Decimal("98765.43"),
            gst_rate=Decimal("18") if i % 2 else Decimal("12"),
            taxable_amount=taxable,
            tax_amount=tax,
            line_total=taxable + tax,
        )
        if cls is not CreditNoteItem:
            kwargs.update(
                hsn_sac="84713010",
                description="Serial-tracked; 30 character desc" if i % 4 == 0 else None,
                discount_type="percentage" if i % 5 == 0 else None,
                discount_value=Decimal("10") if i % 5 == 0 else None,
                cgst_amount=Decimal("0") if interstate else tax / 2,
                sgst_amount=Decimal("0") if interstate else tax / 2,
                igst_amount=tax if interstate else Decimal("0"),
            )
        items.append(cls(**kwargs))
    return items


def _products() -> list[Product]:
    return [
        Product(id=1, name=LONG_NAME, sku="SKU-" + "X" * 20, hsn_sac="84713010", unit="Pieces", allow_decimal=True),
        Product(id=2, name="Mechanical Keyboard with an unusually long marketing name", sku="KB-1", hsn_sac="84716060", unit="Box"),
        Product(id=3, name="USB-C cable", sku="USB-1", hsn_sac="85444290", unit="Pieces", allow_decimal=True),
    ]


def _totals(items) -> dict:
    taxable = sum((item.taxable_amount for item in items), Decimal("0"))
    tax = sum((item.tax_amount for item in items), Decimal("0"))
    return {"taxable": taxable, "tax": tax}


def _company_snapshot() -> dict:
    return dict(
        company_name="Respawn Technologies Private Limited " + "Z" * 30,
        company_address="Unit 5, Pinnacle Tech Park, 5th Floor, Bannerghatta Road, Bengaluru 560 029",
        company_gst="29AAABB1234C1Z5",
        company_phone="9876543210",
        company_email="accounts@respawn.in",
        company_website="https://www.respawn.in",
        company_currency_code="INR",
        company_logo_data=LOGO,
        company_logo_mime_type="image/png",
        company_additional_info="FSSAI 12345678901234\nMSME UDYAM-KR-03-0000000",
        company_terms_text="\n".join(f"{n}. Goods once sold will not be taken back or exchanged under any circumstances whatsoever." for n in range(1, 9)),
    )


def make_invoice(count: int = 40, *, interstate: bool = False, voucher_type: str = "sales") -> Invoice:
    items = _items(count, interstate=interstate)
    t = _totals(items)
    discount = Decimal("1000.00")
    tcs = Decimal("123.45")
    round_off = Decimal("0.32")
    return Invoice(
        id=1,
        voucher_type=voucher_type,
        invoice_number="INV-2026-0000118",
        supplier_invoice_number="SUP/99/2026-27/000123" if voucher_type == "purchase" else None,
        invoice_date=datetime(2026, 9, 2),
        due_date=datetime(2026, 10, 2),
        place_of_supply="07" if interstate else "29",
        status="active",
        tax_inclusive=False,
        ledger_name="Vertex Systems and Allied Distribution Services LLP",
        ledger_address="56 Lavelle Road, Bengaluru 560 001, Karnataka, India",
        ledger_gst="07AABPI6543L1Z9" if interstate else "29AABVS2109K1Z8",
        ledger_phone="9845001008",
        shipping_address="Warehouse 12, KIADB Industrial Area, Hoskote 562 114",
        shipping_address_label="Hoskote warehouse",
        reference_notes="PO-" + "7" * 60,
        items=items,
        taxable_amount=t["taxable"],
        total_tax_amount=t["tax"],
        cgst_amount=Decimal("0") if interstate else t["tax"] / 2,
        sgst_amount=Decimal("0") if interstate else t["tax"] / 2,
        igst_amount=t["tax"] if interstate else Decimal("0"),
        discount_type="flat",
        discount_value=discount,
        tcs_amount=tcs,
        tcs_rate=Decimal("1"),
        tcs_section_ref="394(1)",
        apply_round_off=True,
        round_off_amount=round_off,
        total_amount=t["taxable"] + t["tax"] - discount + tcs + round_off,
        **_company_snapshot(),
    )


@pytest.mark.parametrize("paper", ["a4", "a5", "thermal80", "thermal58"])
def test_invoice_pdf_preserves_hindi_customer_and_product_names(paper):
    pypdf = pytest.importorskip("pypdf")
    if not shutil.which("fc-match"):
        pytest.skip("fontconfig is needed to check for the Hindi PDF font")
    family = subprocess.run(
        ["fc-match", "--format=%{family}", "Noto Sans Devanagari"],
        check=True, capture_output=True, text=True,
    ).stdout
    if "Noto Sans Devanagari" not in family:
        pytest.skip("install fonts-noto-core to exercise Hindi PDF rendering")

    invoice = make_invoice(1)
    invoice.ledger_name = 'चावल वाले "राम" & Co'
    products = _products()
    products[0].name = "Basmati Chawal चावल"
    if pdf_paper.is_thermal(paper):
        html = build_thermal_copies([thermal_invoice_doc(invoice, products)], paper)
    else:
        html = _build_multi_copy_invoice_html(invoice, products, [], copies=1, paper=paper)
    pdf = render_pdf(html, paper)
    text = "\n".join(page.extract_text() for page in pypdf.PdfReader(BytesIO(pdf)).pages)
    assert text.count("चावल") >= 2, text
    assert "राम" in text, text
    assert "Basmati Chawal" in text, text


def _accounts() -> list[CompanyAccount]:
    return [
        CompanyAccount(
            id=n, account_type="bank", display_name=f"Bank {n}", bank_name="HDFC Bank",
            branch_name="Koramangala Branch", account_name="Respawn Technologies Pvt Ltd",
            account_number="50200012345678", ifsc_code="HDFC0001234",
        )
        for n in (1, 2)
    ]


def make_credit_note(count: int = 8, *, interstate: bool = False) -> tuple:
    invoice = make_invoice(1, interstate=interstate)
    items = _items(count, interstate=interstate, cls=CreditNoteItem)
    for item in items:
        item.invoice_id = invoice.id
        item.invoice_item = InvoiceItem(hsn_sac="84713010")
    t = _totals(items)
    note = CreditNote(
        credit_note_number="CN/26/0007",
        credit_note_type="return",
        direction="outward",
        reason="Damaged in transit",
        status="active",
        taxable_amount=t["taxable"],
        cgst_amount=Decimal("0") if interstate else t["tax"] / 2,
        sgst_amount=Decimal("0") if interstate else t["tax"] / 2,
        igst_amount=t["tax"] if interstate else Decimal("0"),
        total_amount=t["taxable"] + t["tax"],
        created_at=datetime(2026, 9, 5),
        items=items,
    )
    ledger = Buyer(name="Vertex Systems", address="56 Lavelle Road", gst=invoice.ledger_gst, phone_number="9")
    return note, [invoice], _products(), None, ledger


def make_challan(count: int = 12) -> DeliveryChallan:
    items = [
        DeliveryChallanItem(
            product_id=i % 3 + 1, quantity=Decimal("3"), unit_price=Decimal("2400"), gst_rate=Decimal("18"),
            hsn_sac="85176200", taxable_amount=Decimal("7200"), tax_amount=Decimal("1296"), line_total=Decimal("8496"),
            description="Sent on approval" if i % 3 == 0 else None,
        )
        for i in range(count)
    ]
    snapshot = _company_snapshot()
    snapshot.pop("company_email")
    snapshot.pop("company_website")
    snapshot.pop("company_terms_text")
    return DeliveryChallan(
        id=1, challan_number="DC-2026-0001", challan_date=datetime(2026, 9, 3), status="open",
        purpose="job_work", place_of_supply="29",
        ledger_name="Vertex Systems", ledger_address="56 Lavelle Road", ledger_gst="29AABVS2109K1Z8",
        ledger_phone="9845001008", taxable_amount=Decimal("7200") * count, reference_notes="Sent on approval",
        terms_text="1. Return within 15 days", items=items, **snapshot,
    )


def make_quotation(count: int = 12, *, document_type: str = "quotation") -> Quotation:
    invoice = make_invoice(count)
    items = [
        QuotationItem(
            product_id=item.product_id, quantity=item.quantity, unit_price=item.unit_price, gst_rate=item.gst_rate,
            hsn_sac=item.hsn_sac, taxable_amount=item.taxable_amount, tax_amount=item.tax_amount,
            cgst_amount=item.cgst_amount, sgst_amount=item.sgst_amount, igst_amount=item.igst_amount,
            line_total=item.line_total, description=item.description,
        )
        for item in invoice.items
    ]
    return Quotation(
        id=1, quotation_number="QT-2026-0001", document_type=document_type, status="open",
        quotation_date=date(2026, 9, 1), valid_until=date(2099, 9, 30),
        ledger_name=invoice.ledger_name, ledger_address=invoice.ledger_address, ledger_gst=invoice.ledger_gst,
        ledger_phone=invoice.ledger_phone, tax_inclusive=False, items=items,
        taxable_amount=invoice.taxable_amount, total_tax_amount=invoice.total_tax_amount,
        cgst_amount=invoice.cgst_amount, sgst_amount=invoice.sgst_amount, igst_amount=Decimal("0"),
        apply_round_off=False, round_off_amount=Decimal("0"),
        total_amount=invoice.taxable_amount + invoice.total_tax_amount,
        **_company_snapshot(),
    )


def make_payment(allocations: int = 6) -> tuple[Payment, CompanyProfile]:
    company = CompanyProfile(
        id=1, name="Respawn Technologies", address="Unit 5, Pinnacle Tech Park", gst="29AAABB1234C1Z5",
        phone_number="9876543210", email="accounts@respawn.in", currency_code="INR",
    )
    payment = Payment(
        id=1, payment_number="RCPT-2026-0001", voucher_type="receipt", status="active", amount=Decimal("250000"),
        mode="bank", reference="UTR" + "9" * 30, notes="Against September invoices",
        date=datetime(2026, 9, 10, 14, 30),
    )
    payment.ledger = Buyer(name="Vertex Systems", address="56 Lavelle Road", gst="29AABVS2109K1Z8", phone_number="9")
    payment.account = CompanyAccount(display_name="HDFC Current", account_type="bank", bank_name="HDFC Bank")
    payment.invoice_allocations = [
        PaymentInvoiceAllocation(
            invoice_id=n, allocated_amount=Decimal("41666.67"),
            invoice=Invoice(id=n, invoice_number=f"INV-2026-{n:04d}", invoice_date=datetime(2026, 9, n)),
        )
        for n in range(1, allocations + 1)
    ]
    return payment, company


# ---------------------------------------------------------------------------
# What each document renders to, per paper
# ---------------------------------------------------------------------------

def invoice_html(paper: str, *, count: int = 40, interstate: bool = False, copies: int = 1, show_sku: bool = True,
                 voucher_type: str = "sales"):
    invoice = make_invoice(count, interstate=interstate, voucher_type=voucher_type)
    if pdf_paper.is_thermal(paper):
        docs = [
            thermal_invoice_doc(invoice, _products(), bank_accounts=_accounts(), copy_label=f"Copy {n}",
                                serials={1: [f"IMEI{n:015d}" for n in range(6)]}, qr_uri=QR)
            for n in range(1, copies + 1)
        ]
        return build_thermal_copies(docs, paper)
    return _build_multi_copy_invoice_html(
        invoice, _products(), _accounts(), copies, show_sku=show_sku,
        serials={1: [f"IMEI{n:015d}" for n in range(6)]},
        pay_qr_html=_build_pdf_pay_qr_card_html("https://app.example.com/s/token", QR), paper=paper,
    )


def credit_note_html(paper: str, *, interstate: bool = False):
    note, invoices, products, company, ledger = make_credit_note(interstate=interstate)
    if pdf_paper.is_thermal(paper):
        return build_thermal_copies([thermal_credit_note_doc(note, invoices, products, company, ledger)], paper)
    return _build_credit_note_html(note, invoices, products, company, ledger, paper=paper)


def challan_html(paper: str, *, copies: int = 1):
    from src.services.pdf_templates.delivery_challan_template import CHALLAN_COPY_LABELS

    challan = make_challan()
    if pdf_paper.is_thermal(paper):
        return build_thermal_copies(
            [thermal_challan_doc(challan, _products(), copy_label=CHALLAN_COPY_LABELS[i]) for i in range(copies)],
            paper,
        )
    return _build_multi_copy_delivery_challan_html(challan, _products(), copies, paper=paper)


def quotation_html(paper: str, *, document_type: str = "quotation"):
    quotation = make_quotation(document_type=document_type)
    if pdf_paper.is_thermal(paper):
        return build_thermal_copies([thermal_quotation_doc(quotation, _products(), _accounts())], paper)
    return _build_quotation_html(quotation, _products(), _accounts(), paper=paper)


def receipt_html(paper: str):
    from src.api.routes.payments import _build_receipt_html

    payment, company = make_payment()
    if pdf_paper.is_thermal(paper):
        return build_thermal_copies([thermal_receipt_doc(payment, company)], paper)
    return _build_receipt_html(payment, company, {}, paper=paper)


DOCUMENTS = {
    "sales_invoice": invoice_html,
    "sales_invoice_interstate": lambda paper: invoice_html(paper, interstate=True),
    "sales_invoice_no_sku": lambda paper: invoice_html(paper, show_sku=False),
    "purchase_bill": lambda paper: invoice_html(paper, voucher_type="purchase"),
    "credit_note": credit_note_html,
    "credit_note_interstate": lambda paper: credit_note_html(paper, interstate=True),
    "delivery_challan": challan_html,
    "quotation": quotation_html,
    "proforma": lambda paper: quotation_html(paper, document_type="proforma"),
    "payment_receipt": receipt_html,
}
PAPERS = ["a4", "a5", "thermal80", "thermal58"]


def _pages(pdf: bytes) -> list[tuple[float, float]]:
    """Each page's (width, height) in mm, read back from the PDF's MediaBoxes.

    WeasyPrint packs the page objects into compressed object streams, so every
    stream is inflated before searching.
    """
    import re
    import zlib

    text = pdf
    for match in re.finditer(rb"stream\r?\n", pdf):
        try:
            text += zlib.decompressobj().decompress(pdf[match.end():])
        except zlib.error:
            continue
    boxes = re.findall(rb"/MediaBox\s*\[\s*([\d.\s]+?)\s*\]", text)
    return [tuple(float(v) * 25.4 / 72 for v in box.split()[2:4]) for box in boxes]


def _documents(html, paper: str):
    """The laid-out WeasyPrint documents ``render_pdf`` prints, for box inspection."""
    if pdf_paper.is_thermal(paper):
        return [pdf_paper._render_roll(h, pdf_paper.thermal_width_mm(paper)) for h in html]
    return [weasyprint.HTML(string=html, url_fetcher=pdf_paper.safe_url_fetcher).render()]


def _overflows(document, tolerance_px: float = 0.5) -> list[str]:
    """Every box whose right edge passes the page's right edge."""
    found = []
    for number, page in enumerate(document.pages, start=1):
        limit = page.width + tolerance_px
        stack = [page._page_box]
        while stack:
            box = stack.pop()
            right = getattr(box, "position_x", 0) + (box.margin_width() if hasattr(box, "margin_width") else 0)
            if right > limit:
                text = getattr(box, "text", "") or type(box).__name__
                found.append(f"page {number}: {text[:40]!r} ends at {right / PX_PER_MM:.1f}mm")
            stack.extend(getattr(box, "children", []) or [])
    return found


# ---------------------------------------------------------------------------
# The paper module
# ---------------------------------------------------------------------------

def test_page_css_keeps_each_templates_a4_margin():
    assert page_css("a4") == "@page { size: A4; margin: 15mm 18mm; }"
    assert page_css("a4", a4_margin="12mm 14mm") == "@page { size: A4; margin: 12mm 14mm; }"
    assert page_css("a5") == "@page { size: A5; margin: 8mm; }"
    assert page_css("a5", landscape=True, a5_margin="11mm 8mm 9mm") == "@page { size: A5 landscape; margin: 11mm 8mm 9mm; }"
    # A roll's size is set by render_pdf, after the content is measured.
    assert "size" not in page_css("thermal80")


@pytest.mark.parametrize(
    ("requested", "default", "report", "expected"),
    [
        ("a5", "thermal80", False, "a5"),
        (None, "thermal58", False, "thermal58"),
        (None, None, False, "a4"),
        (None, "bogus", False, "a4"),
        ("bogus", "a5", False, "a5"),
        # A report can never go on a roll: a thermal default falls back to A4.
        (None, "thermal80", True, "a4"),
        (None, "a5", True, "a5"),
        ("thermal80", "a5", True, "a5"),
    ],
)
def test_resolve_paper_prefers_the_request_then_the_company_then_a4(requested, default, report, expected):
    company = CompanyProfile(default_pdf_paper=default) if default else None
    assert resolve_paper(requested, company, report=report) == expected


# ---------------------------------------------------------------------------
# Page sizes
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("paper", PAPERS)
@pytest.mark.parametrize("name", sorted(DOCUMENTS))
def test_every_transaction_document_prints_on_every_paper(name, paper):
    pdf = render_pdf(DOCUMENTS[name](paper), paper)
    pages = _pages(pdf)
    assert pages, "no pages"
    for width, height in pages:
        if paper in SHEETS_MM:
            assert (round(width), round(height)) == SHEETS_MM[paper]
        else:
            assert round(width) == ROLLS_MM[paper]
    if paper in ROLLS_MM:
        assert len(pages) == 1, "one copy is one length of roll"


def test_a4_keeps_its_page_rule_and_columns():
    html = invoice_html("a4")
    assert "@page { size: A4; margin: 15mm 18mm; }" in html
    assert "Total Tax" in html
    assert "A5" not in html


@pytest.mark.parametrize("paper", ["a4", "a5"])
@pytest.mark.parametrize("due_date", [datetime(2026, 12, 5), None])
def test_sheet_invoice_prints_due_date_only_when_set(paper, due_date):
    invoice = make_invoice(1)
    invoice.due_date = due_date
    html = _build_multi_copy_invoice_html(invoice, _products(), [], copies=2, paper=paper)

    assert html.count("Date: 02 Sep 2026") == 2
    if due_date:
        assert html.count("Due date: 05 Dec 2026") == 2
    else:
        assert "Due date:" not in html


def test_a5_drops_the_total_tax_column():
    html = invoice_html("a5")
    assert "@page { size: A5; margin: 8mm; }" in html
    assert "Total Tax" not in html
    header_cells = html.split("<thead>")[1].split("</thead>")[0].count("<th")
    assert html.count('<col style="width:') == header_cells


HSN_CODES = ("84713010", "84716060", "85444290", "85176200")


@pytest.mark.parametrize(
    "name",
    ["sales_invoice", "sales_invoice_interstate", "sales_invoice_no_sku", "purchase_bill",
     "credit_note", "delivery_challan", "quotation"],
)
def test_a5_never_breaks_an_hsn_code(name):
    document = _documents(DOCUMENTS[name]("a5"), "a5")[0]
    texts = [box.text for page in document.pages for box in _walk(page._page_box) if getattr(box, "text", None)]
    assert any(text in HSN_CODES for text in texts), "no HSN code printed"
    fragments = [
        text for text in texts
        if len(text) >= 3 and text.isdigit() and text not in HSN_CODES and any(text in code for code in HSN_CODES)
    ]
    assert fragments == []


def _walk(box):
    stack = [box]
    while stack:
        current = stack.pop()
        yield current
        stack.extend(getattr(current, "children", []) or [])


# ---------------------------------------------------------------------------
# Thermal rolls
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("paper", ["thermal80", "thermal58"])
def test_each_copy_is_one_page_of_its_own_length(paper):
    pages = _pages(render_pdf(invoice_html(paper, count=5, copies=3), paper))
    assert len(pages) == 3
    assert all(round(width) == ROLLS_MM[paper] for width, _ in pages)

    challan_pages = _pages(render_pdf(challan_html(paper, copies=2), paper))
    assert len(challan_pages) == 2


@pytest.mark.parametrize("paper", ["thermal80", "thermal58"])
def test_the_roll_grows_with_the_items(paper):
    short = _pages(render_pdf(invoice_html(paper, count=2), paper))[0][1]
    long = _pages(render_pdf(invoice_html(paper, count=30), paper))[0][1]
    assert long > short + 100  # 28 more items are well over 10cm of roll
    assert short < 1000


def test_the_measured_length_fits_the_content():
    """The second layout is exactly as tall as the first one's content (plus 1mm)."""
    html = invoice_html("thermal80", count=10)[0]
    document = pdf_paper._render_roll(html, 80)
    assert len(document.pages) == 1
    page = document.pages[0]
    root = page._page_box.children[0]
    content_mm = (root.position_y + root.margin_height()) / PX_PER_MM
    assert 0 < page.height / PX_PER_MM - content_mm <= 1.1


def test_thermal_is_black_only():
    import re

    html = invoice_html("thermal80", count=3)[0]
    style = html.split("<style>")[1].split("</style>")[0]
    colours = set(re.findall(r"#[0-9a-fA-F]{3,6}\b", style))
    assert colours == {"#000", "#fff"}, colours
    assert "background: #fff" in style  # the only background is the paper


def test_thermal_invoice_keeps_what_a_gst_invoice_needs():
    html = invoice_html("thermal80", count=3)[0]
    assert "HSN 84713010" in html
    assert "GST 12%" in html and "GST 18%" in html
    assert "GSTIN 29AABVS2109K1Z8" in html
    assert "CGST" in html and "SGST" in html
    assert "Round off" in html and "TCS @ 1%" in html and "Discount" in html
    assert "Rupees" in html


def test_thermal_interstate_credit_note_puts_tax_in_igst():
    html = credit_note_html("thermal80", interstate=True)[0]
    assert "IGST" in html and "CGST" not in html


def test_thermal_challan_is_at_taxable_value_with_no_gst_summary():
    html = challan_html("thermal80")[0]
    assert "GST summary" not in html
    assert "Total value" in html
    assert "₹8,496.00" not in html  # the line total with tax never prints


def test_thermal_purchase_bill_names_the_supplier():
    html = invoice_html("thermal80", count=2, voucher_type="purchase")[0]
    assert "Purchase Bill" in html and ">Supplier<" in html
    assert "SUP/99/2026-27/000123" in html


def test_thermal_receipt_lists_allocations_not_items():
    html = receipt_html("thermal58")[0]
    assert "INV-2026-0001" in html
    assert "Amount received" in html
    assert "HSN" not in html


def test_thermal_receipt_keeps_allocations_apart_from_the_amount():
    """The allocations are their own section above the total, not lines that seem to add up to it."""
    payment, company = make_payment(allocations=2)
    payment.invoice_allocations[0].tds_amount = Decimal("1000")
    payment.invoice_allocations[0].tds_section_ref = "194J"
    doc = thermal_receipt_doc(payment, company)
    assert doc.totals == []
    ((heading, body),) = doc.lead_blocks
    assert heading == "Allocated to invoices"
    assert "INV-2026-0001" in body and "INV-2026-0002" in body
    assert "TDS deducted (s.194J)" in body
    assert "Total allocated" in body and "₹83,333.34" in body
    html = build_thermal_copies([doc], "thermal80")[0]
    # Allocations, then the solid-rule-free total: nothing sits between the rule and the amount.
    assert html.index("Allocated to invoices") < html.index("Amount received")
    assert 'class="hr2"' not in html


def test_thermal_purchase_bill_never_prints_a_pay_qr():
    invoice = make_invoice(2, voucher_type="purchase")
    doc = thermal_invoice_doc(invoice, _products(), qr_uri=QR)
    assert doc.qr_uri == "" and doc.qr_caption == ""
    html = build_thermal_copies([doc], "thermal80")[0]
    assert "Scan to view" not in html and 'class="qr"' not in html
    # A sale keeps it.
    sale = thermal_invoice_doc(make_invoice(2), _products(), qr_uri=QR)
    assert sale.qr_uri == QR and sale.qr_caption


def test_no_pay_qr_is_drawn_for_a_thermal_purchase_bill(client, db_session, monkeypatch):
    """The share URL may exist (QR switched on), but no QR image is rendered for a purchase."""
    from src.services import share_documents
    from tests.api.tds_helpers import create_invoice, create_ledger

    drawn = []
    monkeypatch.setattr(share_documents, "render_qr_png_data_uri", lambda text: drawn.append(text) or QR)
    bill = create_invoice(client, create_ledger(client, "Supplier"), 1000, "2026-05-10", voucher_type="purchase")
    company_id = db_session.get(Invoice, bill["id"]).company_id

    html = share_documents.build_invoice_html(
        db_session, company_id, bill["id"], share_url="https://app.example.com/s/t?src=qr", paper="thermal80"
    )
    assert drawn == []
    assert "Scan to view" not in html[0]

    sale = create_invoice(client, create_ledger(client, "Buyer"), 1000, "2026-05-10")
    share_documents.build_invoice_html(
        db_session, company_id, sale["id"], share_url="https://app.example.com/s/t?src=qr", paper="thermal80"
    )
    assert drawn == ["https://app.example.com/s/t?src=qr"]


def test_thermal_note_cites_each_invoice_with_its_date_and_the_type():
    html = credit_note_html("thermal80")[0]
    assert "INV-2026-0000118 (02 Sep 2026)" in html
    assert "Sales return" in html

    note, invoices, products, company, ledger = make_credit_note()
    note.direction = "inward"
    note.supplier_credit_note_number = "SCN-77"
    note.supplier_credit_note_date = date(2026, 9, 4)
    invoices[0].supplier_invoice_number = "SUP-9"
    doc = thermal_credit_note_doc(note, invoices, products, company, ledger)
    meta = dict(doc.meta)
    assert doc.title == "Debit Note"
    assert meta["Type"] == "Purchase return"
    assert meta["Against"] == "SUP-9 (02 Sep 2026)"
    assert meta["Supplier's note"] == "SCN-77 (04 Sep 2026)"


@pytest.mark.parametrize("paper", ["thermal80", "thermal58"])
def test_a_note_against_several_invoices_wraps_inside_the_roll(paper):
    note, invoices, products, company, ledger = make_credit_note(count=2)
    invoices += [
        Invoice(id=n, invoice_number=f"INV-2026-{n:07d}", invoice_date=datetime(2026, 9, n), **_company_snapshot())
        for n in range(2, 6)
    ]
    html = build_thermal_copies([thermal_credit_note_doc(note, invoices, products, company, ledger)], paper)
    assert "INV-2026-0000005 (05 Sep 2026)" in html[0]
    for document in _documents(html, paper):
        assert _overflows(document) == []


def test_thermal_challan_prints_no_tax_rate_and_words_only_for_inr():
    html = challan_html("thermal80")[0]
    assert "GST 18%" not in html and "GST " not in html.split("<body>")[1]
    assert "Rupees" in html

    challan = make_challan()
    challan.company_currency_code = "USD"
    doc = thermal_challan_doc(challan, _products())
    assert all(item.rate is None for item in doc.items)
    usd = build_thermal_copies([doc], "thermal80")[0]
    assert "Only" not in usd


# ---------------------------------------------------------------------------
# Nothing runs off the page
# ---------------------------------------------------------------------------

def test_the_overflow_check_catches_a_line_that_runs_off_the_page():
    html = f"<style>{page_css('a5')}</style><p style='white-space: nowrap'>{'0123456789' * 40}</p>"
    assert _overflows(_documents(html, "a5")[0])
    roll = f"<style>{page_css('thermal58')}</style><p style='white-space: nowrap'>{'₹1,23,456.00 ' * 6}</p>"
    assert _overflows(_documents([roll], "thermal58")[0])


@pytest.mark.parametrize("paper", ["a5", "thermal80", "thermal58"])
@pytest.mark.parametrize(
    "build",
    [
        lambda paper: invoice_html(paper),
        lambda paper: invoice_html(paper, interstate=True),
        lambda paper: invoice_html(paper, show_sku=False),
        lambda paper: invoice_html(paper, voucher_type="purchase"),
    ],
    ids=["intrastate_sku", "interstate_sku", "intrastate_no_sku", "purchase"],
)
def test_the_worst_case_invoice_stays_inside_the_page(build, paper):
    for document in _documents(build(paper), paper):
        assert _overflows(document) == []


@pytest.mark.parametrize("paper", ["a5", "thermal80", "thermal58"])
@pytest.mark.parametrize("name", ["credit_note", "delivery_challan", "quotation", "proforma", "payment_receipt"])
def test_other_documents_stay_inside_the_page(name, paper):
    for document in _documents(DOCUMENTS[name](paper), paper):
        assert _overflows(document) == []


# ---------------------------------------------------------------------------
# Routes and the company setting
# ---------------------------------------------------------------------------

COMPANY = {
    "name": "Paper Co",
    "address": "1 Road",
    "gst": "27ABCDE1234F1Z0",
    "phone_number": "",
    "currency_code": "INR",
    "email": "",
    "website": "",
}


def _pdf_sizes(response) -> list[tuple[float, float]]:
    assert response.status_code == 200, response.text
    assert response.headers["content-type"] == "application/pdf"
    return _pages(response.content)


def _set_default_paper(client, paper: str | None):
    body = dict(COMPANY)
    if paper is not None:
        body["default_pdf_paper"] = paper
    response = client.put("/api/company/", json=body)
    assert response.status_code == 200, response.text
    return response.json()


def test_company_default_paper_is_a4_and_can_be_changed(client):
    assert client.get("/api/company/").json()["default_pdf_paper"] == "a4"
    assert _set_default_paper(client, "thermal58")["default_pdf_paper"] == "thermal58"
    # Leaving it out of an update keeps it.
    assert _set_default_paper(client, None)["default_pdf_paper"] == "thermal58"
    assert client.get("/api/company/").json()["default_pdf_paper"] == "thermal58"


def test_company_default_paper_rejects_an_unknown_paper(client):
    response = client.put("/api/company/", json={**COMPANY, "default_pdf_paper": "letter"})
    assert response.status_code == 422


def test_invoice_pdf_route_takes_paper_and_falls_back_to_the_company_default(client):
    from tests.api.tds_helpers import create_invoice, create_ledger

    invoice = create_invoice(client, create_ledger(client, "Buyer"), 1000, "2026-05-10")
    url = f"/api/invoices/{invoice['id']}/pdf"

    assert [tuple(map(round, size)) for size in _pdf_sizes(client.get(url))] == [(210, 297)]
    assert [tuple(map(round, size)) for size in _pdf_sizes(client.get(url, params={"paper": "a5"}))] == [(148, 210)]
    rolls = _pdf_sizes(client.get(url, params={"paper": "thermal58", "copies": 2}))
    assert len(rolls) == 2 and all(round(width) == 58 for width, _ in rolls)
    assert client.get(url, params={"paper": "letter"}).status_code == 422

    _set_default_paper(client, "thermal80")
    assert [round(width) for width, _ in _pdf_sizes(client.get(url))] == [80]
    # A request still wins over the default.
    assert [tuple(map(round, size)) for size in _pdf_sizes(client.get(url, params={"paper": "a4"}))] == [(210, 297)]


def test_a_thermal_company_default_prints_reports_on_a4(client):
    _set_default_paper(client, "thermal80")
    response = client.get("/api/ledgers/day-book/pdf", params={"from_date": "2026-05-01", "to_date": "2026-05-31"})
    assert {tuple(map(round, size)) for size in _pdf_sizes(response)} == {(210, 297)}
    # A roll cannot be asked for either.
    response = client.get(
        "/api/ledgers/day-book/pdf",
        params={"from_date": "2026-05-01", "to_date": "2026-05-31", "paper": "thermal80"},
    )
    assert response.status_code == 422


@pytest.mark.parametrize("paper", PAPERS)
def test_receipt_pdf_route_takes_paper(client, paper):
    from tests.api.tds_helpers import create_account, create_invoice, create_ledger, post_voucher

    ledger = create_ledger(client, "Buyer")
    invoice = create_invoice(client, ledger, 1000, "2026-05-10")
    response = post_voucher(client, ledger, 500, [{"invoice_id": invoice["id"], "allocated_amount": 500}],
                            "2026-05-12", account_id=create_account(client))
    assert response.status_code in (200, 201), response.text
    payment = response.json()
    sizes = _pdf_sizes(client.get(f"/api/payments/{payment['id']}/pdf", params={"paper": paper}))
    expected_width = SHEETS_MM[paper][0] if paper in SHEETS_MM else ROLLS_MM[paper]
    assert [round(width) for width, _ in sizes][:1] == [expected_width]
