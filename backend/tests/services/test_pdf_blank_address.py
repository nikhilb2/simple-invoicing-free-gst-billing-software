"""A business or customer with no address prints no address line on A4/A5 documents.

Regression: the sheet templates printed the placeholder "Address not provided"
under the seller's or the party's name when the address was empty. A business
can start with only its name and a customer needs only a name, so the line is
left out instead, as the thermal templates already do.
"""

import pytest

from src.services.pdf_templates import (
    _build_credit_note_html,
    _build_delivery_challan_html,
    _build_invoice_html,
    _build_quotation_html,
)
from tests.services.test_pdf_paper import _products, make_challan, make_credit_note, make_invoice, make_quotation

SELLER_ADDRESS = "Unit 5, Pinnacle Tech Park, 5th Floor, Bannerghatta Road, Bengaluru 560 029"
PARTY_ADDRESS = "56 Lavelle Road"
BLANK_ADDRESSES = [None, "", "   ", " \n\t "]


def render(kind: str, paper: str, *, seller_address: str | None, party_address: str | None) -> str:
    if kind in ("sales", "purchase"):
        invoice = make_invoice(1, voucher_type=kind)
        invoice.company_address = seller_address
        invoice.ledger_address = party_address
        return _build_invoice_html(invoice, _products(), [], paper=paper)
    if kind in ("quotation", "proforma"):
        quotation = make_quotation(1, document_type=kind)
        quotation.company_address = seller_address
        quotation.ledger_address = party_address
        return _build_quotation_html(quotation, _products(), [], paper=paper)
    if kind == "credit_note":
        note, invoices, products, company, ledger = make_credit_note(1)
        invoices[0].company_address = seller_address
        invoices[0].ledger_address = party_address
        ledger.address = party_address
        return _build_credit_note_html(note, invoices, products, company, ledger, paper=paper)
    challan = make_challan(1)
    challan.company_address = seller_address
    challan.ledger_address = party_address
    return _build_delivery_challan_html(challan, _products(), paper=paper)


KINDS = ["sales", "purchase", "quotation", "proforma", "credit_note", "delivery_challan"]


@pytest.mark.parametrize("paper", ["a4", "a5"])
@pytest.mark.parametrize("kind", KINDS)
@pytest.mark.parametrize("blank", BLANK_ADDRESSES)
def test_blank_seller_address_prints_no_address_line(kind, paper, blank):
    html = render(kind, paper, seller_address=blank, party_address=PARTY_ADDRESS)
    assert "Address not provided" not in html
    assert "<p></p>" not in html
    assert f"<p>{PARTY_ADDRESS}</p>" in html
    if blank:
        assert f"<p>{blank}</p>" not in html


@pytest.mark.parametrize("paper", ["a4", "a5"])
@pytest.mark.parametrize("kind", KINDS)
@pytest.mark.parametrize("blank", BLANK_ADDRESSES)
def test_blank_party_address_prints_no_address_line(kind, paper, blank):
    html = render(kind, paper, seller_address=SELLER_ADDRESS, party_address=blank)
    assert "Address not provided" not in html
    assert "<p></p>" not in html
    assert f"<p>{SELLER_ADDRESS}</p>" in html
    if blank:
        assert f"<p>{blank}</p>" not in html


@pytest.mark.parametrize("kind", KINDS)
def test_addresses_are_printed_trimmed_and_escaped(kind):
    html = render(kind, "a4", seller_address="  1 Market Road  ", party_address="Shop 4 & 5, Main Bazaar ")
    assert "<p>1 Market Road</p>" in html
    assert "<p>Shop 4 &amp; 5, Main Bazaar</p>" in html
    assert "Address not provided" not in html
