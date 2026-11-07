"""TCS line on the documents a customer receives: PDF, share page and email."""

from datetime import date, datetime
from decimal import Decimal

import pytest

from src.api.routes import email as email_routes
from src.models.invoice import Invoice, InvoiceItem
from src.models.product import Product
from src.services.pdf_templates import (
    _build_credit_note_html,
    _build_invoice_html,
    _build_multi_copy_invoice_html,
    _build_quotation_html,
)
from src.services.pdf_templates.builders import tcs_label
from tests.services.test_credit_note_pdf_template import make_note
from tests.services.test_quotation_pdf_template import make_quotation

LABEL = "TCS @ 2% (s.394(1) Sl. No. 4)"
PRODUCT = Product(id=5, name="Scrap", sku="SC-1", hsn_sac="7204", price=100000, gst_rate=18)


def make_invoice(tcs: bool) -> Invoice:
    item = InvoiceItem(
        product_id=5, hsn_sac="7204", quantity=1, unit_price=100000, gst_rate=18,
        taxable_amount=100000, tax_amount=18000, cgst_amount=9000, sgst_amount=9000,
        igst_amount=0, line_total=118000,
    )
    return Invoice(
        id=1, invoice_number="INV-1", invoice_date=datetime(2026, 6, 1),
        company_name="Mofna Traders", company_gst="27AAAAA0000A1Z2", company_currency_code="INR",
        ledger_name="Acme", ledger_address="9 Buyer Lane", ledger_gst="27BBBBB0000B1ZT",
        taxable_amount=100000, total_tax_amount=18000, cgst_amount=9000, sgst_amount=9000,
        igst_amount=0, round_off_amount=0, apply_round_off=False,
        tcs_section_ref="394(1) Sl. No. 4" if tcs else None,
        tcs_rate=Decimal("2.000") if tcs else None,
        tcs_amount=Decimal("2360.00") if tcs else Decimal("0"),
        total_amount=120360 if tcs else 118000, items=[item],
    )


@pytest.mark.parametrize(
    "rate, ref, expected",
    [
        (Decimal("2.000"), "394(1) Sl. No. 4", LABEL),
        (Decimal("0.5"), None, "TCS @ 0.5%"),
        (Decimal("1.25"), "206C(1H)", "TCS @ 1.25% (s.206C(1H))"),
    ],
)
def test_tcs_label(rate, ref, expected):
    assert tcs_label(rate, ref) == expected


def test_invoice_pdf_shows_tcs_above_total():
    html = _build_invoice_html(make_invoice(True), [PRODUCT])
    assert LABEL in html
    assert "2,360.00" in html
    assert html.index(LABEL) < html.index("Total due")


def test_invoice_pdf_without_tcs_has_no_tcs():
    assert "TCS" not in _build_invoice_html(make_invoice(False), [PRODUCT])


def test_share_page_invoice_shows_tcs():
    html = _build_multi_copy_invoice_html(make_invoice(True), [PRODUCT], [], 1)
    assert LABEL in html and "2,360.00" in html
    assert "TCS" not in _build_multi_copy_invoice_html(make_invoice(False), [PRODUCT], [], 1)


def test_credit_note_shows_tcs_reversed():
    note, invoices, products, ledger = make_note()
    note.tcs_amount = Decimal("2360.00")
    html = _build_credit_note_html(note, invoices, products, None, ledger)
    assert "TCS reversed" in html and "2,360.00" in html
    assert html.index("TCS reversed") < html.index("Total credit")


def test_credit_note_without_tcs_has_no_tcs():
    note, invoices, products, ledger = make_note()
    note.tcs_amount = Decimal("0")
    assert "TCS" not in _build_credit_note_html(note, invoices, products, None, ledger)


def _quotation_html(**overrides):
    return _build_quotation_html(make_quotation(**overrides), [PRODUCT], [], today=date(2026, 6, 15))


def test_quotation_shows_tcs():
    html = _quotation_html(
        tcs_section_ref="394(1) Sl. No. 4", tcs_rate=Decimal("2.000"), tcs_amount=Decimal("2360.00")
    )
    assert LABEL in html and "2,360.00" in html


def test_quotation_without_tcs_has_no_tcs():
    assert "TCS" not in _quotation_html(tcs_amount=Decimal("0"))


def _email(**extra):
    return email_routes._jinja_env.get_template("invoice_email.html").render(
        company_name="Mofna", invoice_number="INV-1", invoice_date="01 Jun 2026",
        buyer_name="Acme", total_amount="1,20,360.00", items_count=1, currency="₹", **extra,
    )


def test_email_shows_tcs_line():
    html = _email(tcs_label=LABEL, tcs_amount="2,360.00")
    assert LABEL in html and "₹2,360.00" in html


def test_email_without_tcs_has_no_tcs():
    assert "TCS" not in _email()
