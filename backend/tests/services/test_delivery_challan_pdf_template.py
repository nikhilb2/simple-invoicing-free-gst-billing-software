"""What a delivery challan prints, and what it must never print.

A challan is not a bill: no tax amounts, no payment wording, no bank or UPI details.
It must carry the Rule 55 particulars and the copy labels.
"""

import re
from datetime import date, datetime

import pytest

from src.models.delivery_challan import DeliveryChallan, DeliveryChallanItem
from src.models.product import Product
from src.services.pdf_templates import (
    _build_delivery_challan_html,
    _build_multi_copy_delivery_challan_html,
)
from src.services.pdf_templates.delivery_challan_template import CHALLAN_COPY_LABELS

BANNED = [
    "Tax Invoice",
    "Bill to",
    "Billed by",
    "Due",
    "Balance",
    "Paid",
    "Amount payable",
    "CGST",
    "SGST",
    "IGST",
    "GST charged",
    "Total tax",
    "UPI",
    "Pay online",
    "pay-qr",
    "Scan to",
    "Bank",
    "IFSC",
    "IRN",
]


def make_challan(**overrides) -> DeliveryChallan:
    item = DeliveryChallanItem(
        product_id=5,
        hsn_sac="84713010",
        quantity=10,
        unit_price=100,
        gst_rate=18,
        taxable_amount=1000,
        tax_amount=180,
        cgst_amount=90,
        sgst_amount=90,
        igst_amount=0,
        line_total=1180,
        description="Black, boxed",
    )
    fields = dict(
        id=1,
        challan_number="DC-2026-001",
        status="open",
        purpose="job_work",
        challan_date=date(2026, 11, 15),
        company_name="Mofna Traders",
        company_address="1 Market Road, Pune",
        company_gst="27AAAAA0000A1Z2",
        company_phone="9000000000",
        company_currency_code="INR",
        company_bank_name="State Bank",
        company_account_number="1234567890",
        company_ifsc_code="SBIN0001234",
        ledger_name="Acme & Sons",
        ledger_address="9 Buyer Lane, Bengaluru",
        ledger_gst="29AADCB2230M1ZP",
        ledger_phone="9111111111",
        place_of_supply="29",
        taxable_amount=1000,
        total_tax_amount=180,
        cgst_amount=0,
        sgst_amount=0,
        igst_amount=180,
        total_amount=1180,
        items=[item],
    )
    fields.update(overrides)
    return DeliveryChallan(**fields)


PRODUCT = Product(id=5, name="Widget", sku="WID-1", hsn_sac="84713010", price=100, gst_rate=18, unit="Pieces")


def render(challan=None, **kwargs) -> str:
    return _build_delivery_challan_html(challan or make_challan(), [PRODUCT], **kwargs)


def visible_text(html: str) -> str:
    """What the reader sees: the stylesheet's class names are not on the page."""
    return re.sub(r"<[^>]+>", " ", html.split("</head>")[1])


def test_title_and_rule_55_particulars():
    text = visible_text(render())
    assert "Delivery Challan" in text
    assert "DC-2026-001" in text
    assert "15 Nov 2026" in text
    assert "Mofna Traders" in text and "1 Market Road, Pune" in text
    assert "GSTIN: 27AAAAA0000A1Z2" in text
    assert "Acme &amp; Sons" in text and "9 Buyer Lane, Bengaluru" in text
    assert "GSTIN: 29AADCB2230M1ZP" in text
    assert "Place of supply: Karnataka (29)" in text
    assert "Purpose: Job work" in text
    for heading in ("Description of goods", "HSN/SAC", "Qty", "Unit", "Taxable value"):
        assert heading in text
    assert "84713010" in text and "Widget" in text and "Black, boxed" in text
    assert "₹1,000.00" in text


def test_total_value_is_the_taxable_amount_with_words():
    text = visible_text(render())
    assert "Total value" in text
    assert "₹1,000.00" in text
    assert "One Thousand" in text
    assert "1,180" not in text


@pytest.mark.parametrize("banned", BANNED)
def test_never_prints_bill_wording_or_tax(banned):
    assert banned not in visible_text(render())


def test_never_prints_any_tax_amount():
    text = visible_text(render())
    for amount in ("180.00", "90.00", "1,180.00"):
        assert amount not in text


def test_signature_blocks():
    text = visible_text(render())
    assert "Received by" in text
    assert "For Mofna Traders" in text
    assert "Authorised signatory" in text


def test_unregistered_consignee_and_missing_consignor_gstin():
    text = visible_text(render(make_challan(ledger_gst=None, company_gst=None)))
    assert "Unregistered" in text
    assert "GSTIN" not in text


def test_place_of_supply_omitted_when_unset():
    assert "Place of supply" not in visible_text(render(make_challan(place_of_supply=None)))


def test_ship_to_block_only_when_a_shipping_address_is_set():
    assert "Ship to" not in visible_text(render())
    text = visible_text(render(make_challan(shipping_address="Plot 4, MIDC", shipping_address_label="Warehouse")))
    assert "Ship to" in text and "Plot 4, MIDC" in text and "Warehouse" in text


def test_notes_and_terms_print_when_set_and_not_otherwise():
    plain = visible_text(render())
    assert "Notes" not in plain and "Terms" not in plain
    text = visible_text(render(make_challan(reference_notes="Fragile goods", terms_text="Return within 30 days\nNo exchange")))
    assert "Fragile goods" in text
    assert "Terms &amp; Conditions" in text
    assert "Return within 30 days" in text and "No exchange" in text


def test_cancelled_challan_is_marked():
    assert "CANCELLED" not in render()
    cancelled = make_challan(status="cancelled", cancelled_at=datetime(2026, 11, 16, 10, 0))
    assert "CANCELLED on 16 Nov 2026" in visible_text(render(cancelled))


def test_text_is_escaped():
    text = render(make_challan(reference_notes="<script>alert(1)</script>"))
    assert "<script>" not in text
    assert "&lt;script&gt;" in text


def test_sku_follows_show_sku():
    assert "WID-1" in visible_text(render(show_sku=True))
    assert "WID-1" not in visible_text(render(show_sku=False))


def test_non_inr_challan_has_no_amount_in_words():
    text = visible_text(render(make_challan(company_currency_code="USD")))
    assert "$1,000.00" in text
    assert "Thousand" not in text


def test_missing_product_does_not_break_the_page():
    html = _build_delivery_challan_html(make_challan(), [])
    assert "Product #5" in html


def test_single_copy_is_labelled_original_for_the_consignee():
    text = visible_text(_build_multi_copy_delivery_challan_html(make_challan(), [PRODUCT], 1))
    assert "Original for consignee" in text
    assert "Duplicate" not in text and "Triplicate" not in text


def test_three_copies_carry_the_three_labels_one_page_each():
    html = _build_multi_copy_delivery_challan_html(make_challan(), [PRODUCT], 3)
    text = visible_text(html)
    for label in CHALLAN_COPY_LABELS:
        assert text.count(label) == 1
    assert text.count("Delivery Challan") == 3
    assert html.count("break-after: page") == 2
    assert html.count("<html>") == 1 and html.count("</body>") == 1


@pytest.mark.parametrize("copies, expected", [(0, 1), (-2, 1), (2, 2), (7, 3)])
def test_copies_are_clamped_to_one_to_three(copies, expected):
    text = visible_text(_build_multi_copy_delivery_challan_html(make_challan(), [PRODUCT], copies))
    assert text.count("Delivery Challan") == expected
