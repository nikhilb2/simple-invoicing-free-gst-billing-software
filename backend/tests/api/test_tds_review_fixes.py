"""Regression tests for the review of #768 / #770."""

from io import BytesIO
from unittest.mock import AsyncMock, patch

import pytest

from src.models.company import CompanyProfile
from src.models.invoice import Invoice
from src.models.payment import PaymentInvoiceAllocation
from tests.api.tds_helpers import (
    add_sections,
    create_invoice,
    create_ledger,
    enable_purchase_tds,
    get_invoice,
    ledger_balance,
    post_voucher,
    set_company_pan,
)


@pytest.fixture
def sections(db_session):
    return add_sections(db_session)


def _tds(invoice_id, cash, tds, section_id):
    return {"invoice_id": invoice_id, "allocated_amount": cash, "tds_amount": tds, "tds_section_id": section_id}


def _suggest(client, invoice_id, section_id):
    response = client.get("/api/tds/suggestion", params={"invoice_id": invoice_id, "section_id": section_id})
    assert response.status_code == 200, response.text
    return response.json()


# --- 1. On a receipt the rate follows OUR PAN, not the customer's ---------------

def test_receipt_rate_ignores_a_customer_without_pan(client, db_session, sections):
    set_company_pan(client, db_session, "AAACM1234M")  # a company
    customer = create_ledger(client, "No PAN Customer", party_type="company")
    invoice = create_invoice(client, customer, 100000, "2026-05-10")
    body = _suggest(client, invoice["id"], sections["prof"].id)
    assert body["rate"] == 10
    assert body["amount"] == 10000
    response = post_voucher(
        client, customer, 108000, [_tds(invoice["id"], 108000, 10000, sections["prof"].id)], "2026-05-20T10:00:00",
    )
    assert response.status_code == 200, response.text
    assert response.json()["invoice_allocations"][0]["tds_rate"] == 10


def test_receipt_rate_uses_the_no_pan_rate_when_our_business_has_no_pan(client, db_session, sections):
    set_company_pan(client, db_session, None)
    customer = create_ledger(client, "Acme", pan="AAACA1234A", party_type="company")
    invoice = create_invoice(client, customer, 100000, "2026-05-10")
    body = _suggest(client, invoice["id"], sections["prof"].id)
    assert body["has_pan"] is False
    assert body["rate"] == 20
    assert "Your business has no PAN" in body["reason"]
    assert "397(2)" in body["reason"]


def test_receipt_contractor_rate_follows_our_holder_type(client, db_session, sections):
    # An individual customer does not make the rate 1%: we are a company, so 2%.
    set_company_pan(client, db_session, "AAACM1234M")
    customer = create_ledger(client, "Ravi", pan="ABCPK1234D", party_type="individual")
    invoice = create_invoice(client, customer, 50000, "2026-05-10")
    body = _suggest(client, invoice["id"], sections["contractor"].id)
    assert body["rate"] == 2
    assert body["amount"] == 1000
    assert "not an individual or HUF" in body["reason"]


def test_receipt_contractor_rate_is_one_percent_for_an_individual_business(client, db_session, sections):
    # The 4th character of our PAN is P: an individual proprietor gets 1%,
    # even when the customer is a company.
    set_company_pan(client, db_session, "ABCPS1234K")
    customer = create_ledger(client, "BigCo", pan="AAACB1234B", party_type="company")
    invoice = create_invoice(client, customer, 50000, "2026-05-10")
    assert _suggest(client, invoice["id"], sections["contractor"].id)["rate"] == 1
    response = post_voucher(
        client, customer, 58500, [_tds(invoice["id"], 58500, 500, sections["contractor"].id)], "2026-05-20T10:00:00",
    )
    assert response.status_code == 200, response.text
    assert response.json()["invoice_allocations"][0]["tds_rate"] == 1


def test_huf_pan_counts_as_huf(client, db_session, sections):
    set_company_pan(client, db_session, "ABCHS1234K")
    customer = create_ledger(client, "BigCo", pan="AAACB1234B", party_type="company")
    invoice = create_invoice(client, customer, 50000, "2026-05-10")
    assert _suggest(client, invoice["id"], sections["contractor"].id)["rate"] == 1


def test_payment_rate_still_follows_the_supplier(client, db_session, sections):
    set_company_pan(client, db_session, "ABCPS1234K")  # we are an individual...
    enable_purchase_tds(db_session, client=client)
    supplier = create_ledger(client, "BuildCo", pan="AABCB1234C", party_type="company")
    bill = create_invoice(client, supplier, 50000, "2026-06-15", voucher_type="purchase")
    # ...but on a payment the supplier is the deductee: a company, so 2%.
    assert _suggest(client, bill["id"], sections["contractor"].id)["rate"] == 2


# --- 2. Editing a supplier payment after purchase TDS is turned off -------------

def _payment_with_tds(client, db_session, sections):
    enable_purchase_tds(db_session, client=client)
    supplier = create_ledger(client, "BuildCo", pan="AABCB1234C", party_type="company")
    bill = create_invoice(client, supplier, 50000, "2026-06-15", voucher_type="purchase")
    response = post_voucher(
        client, supplier, 58000, [_tds(bill["id"], 58000, 1000, sections["contractor"].id)],
        "2026-06-20T10:00:00", voucher_type="payment",
    )
    assert response.status_code == 200, response.text
    company = db_session.query(CompanyProfile).first()
    company.enable_purchase_tds = False
    db_session.commit()
    return supplier, bill, response.json()


def test_unchanged_tds_can_be_resent_after_the_setting_is_off(client, db_session, sections):
    _, bill, payment = _payment_with_tds(client, db_session, sections)
    response = client.put(f"/api/payments/{payment['id']}", json={
        "voucher_type": "payment",
        "amount": 58000,
        "date": "2026-06-20T10:00:00",
        "notes": "edited",
        "invoice_allocations": [_tds(bill["id"], 58000, 1000, sections["contractor"].id)],
    })
    assert response.status_code == 200, response.text
    assert response.json()["notes"] == "edited"
    assert response.json()["invoice_allocations"][0]["tds_amount"] == 1000


def test_changed_tds_is_refused_while_the_setting_is_off(client, db_session, sections):
    _, bill, payment = _payment_with_tds(client, db_session, sections)
    response = client.put(f"/api/payments/{payment['id']}", json={
        "voucher_type": "payment",
        "amount": 58000,
        "date": "2026-06-20T10:00:00",
        "invoice_allocations": [_tds(bill["id"], 58000, 900, sections["contractor"].id)],
    })
    assert response.status_code == 400
    assert "turned off" in response.json()["detail"]


def test_tds_can_be_removed_while_the_setting_is_off(client, db_session, sections):
    _, bill, payment = _payment_with_tds(client, db_session, sections)
    response = client.put(f"/api/payments/{payment['id']}", json={
        "voucher_type": "payment",
        "amount": 58000,
        "date": "2026-06-20T10:00:00",
        "invoice_allocations": [{"invoice_id": bill["id"], "allocated_amount": 58000}],
    })
    assert response.status_code == 200, response.text
    assert get_invoice(client, bill["id"])["remaining_amount"] == 1000


def test_new_payment_tds_is_refused_while_the_setting_is_off(client, db_session, sections):
    supplier, _, _ = _payment_with_tds(client, db_session, sections)
    bill = create_invoice(client, supplier, 50000, "2026-06-16", voucher_type="purchase")
    response = post_voucher(
        client, supplier, 58000, [_tds(bill["id"], 58000, 1000, sections["contractor"].id)],
        "2026-06-21T10:00:00", voucher_type="payment",
    )
    assert response.status_code == 400


# --- 3. An invoice with TDS cannot be cancelled ----------------------------------

def test_cancelling_an_invoice_with_tds_is_blocked(client, db_session, sections):
    set_company_pan(client, db_session, "AAACM1234M")
    customer = create_ledger(client, "Acme", pan="AAACA1234A", party_type="company")
    invoice = create_invoice(client, customer, 100000, "2026-05-10")
    response = post_voucher(
        client, customer, 108000, [_tds(invoice["id"], 108000, 10000, sections["prof"].id)], "2026-05-20T10:00:00",
    )
    assert response.status_code == 200, response.text
    receipt = response.json()

    response = client.delete(f"/api/invoices/{invoice['id']}")
    assert response.status_code == 400
    assert "Remove the TDS from the receipt first" in response.json()["detail"]
    assert get_invoice(client, invoice["id"])["status"] == "active"

    # Once the TDS is removed from the receipt, the invoice can be cancelled.
    response = client.put(f"/api/payments/{receipt['id']}", json={
        "voucher_type": "receipt",
        "amount": 108000,
        "date": "2026-05-20T10:00:00",
        "invoice_allocations": [{"invoice_id": invoice["id"], "allocated_amount": 108000}],
    })
    assert response.status_code == 200, response.text
    assert client.delete(f"/api/invoices/{invoice['id']}").status_code == 200


def test_cancelling_a_bill_with_tds_is_blocked(client, db_session, sections):
    _, bill, _ = _payment_with_tds(client, db_session, sections)
    response = client.delete(f"/api/invoices/{bill['id']}")
    assert response.status_code == 400
    assert "Remove the TDS from the payment first" in response.json()["detail"]


def test_report_ignores_tds_on_a_cancelled_invoice(client, db_session, sections):
    _, bill, _ = _payment_with_tds(client, db_session, sections)
    assert len(client.get("/api/tds/payable", params={"tax_year": 2026}).json()["rows"]) == 1
    # Older data, cancelled before the guard existed.
    db_session.get(Invoice, bill["id"]).status = "cancelled"
    db_session.commit()
    assert client.get("/api/tds/payable", params={"tax_year": 2026}).json()["rows"] == []


# --- 4. Purchase of goods stores the excess as the base --------------------------

def test_goods_tds_stores_the_excess_as_the_base(client, db_session, sections):
    enable_purchase_tds(db_session, client=client)
    seller = create_ledger(client, "Steel Traders", pan="AAFCS1234E", party_type="company")
    create_invoice(client, seller, 4900000, "2026-05-01", voucher_type="purchase", gst_rate=0)
    bill = create_invoice(client, seller, 200000, "2026-06-01", voucher_type="purchase", gst_rate=0)
    response = post_voucher(
        client, seller, 199900, [_tds(bill["id"], 199900, 100, sections["goods"].id)],
        "2026-06-05T10:00:00", voucher_type="payment",
    )
    assert response.status_code == 200, response.text
    allocation = response.json()["invoice_allocations"][0]
    assert allocation["tds_base_amount"] == 100000
    assert allocation["tds_rate"] == 0.1

    row = client.get("/api/tds/payable", params={"tax_year": 2026}).json()["rows"][0]
    assert row["base_amount"] == 100000
    assert round(row["base_amount"] * row["rate"] / 100, 2) == row["tds_amount"]
    db_session.expire_all()
    assert float(db_session.query(PaymentInvoiceAllocation).one().tds_base_amount) == 100000


# --- 6. The emailed purchase bill PDF carries the TDS block ----------------------

def test_emailed_purchase_bill_gets_the_settlement_block(client, db_session, sections):
    _, bill, _ = _payment_with_tds(client, db_session, sections)
    captured = {}

    def fake_pdf(*args, **kwargs):
        captured.update(kwargs)
        return BytesIO(b"%PDF-1.4")

    with patch("src.api.routes.email._build_invoice_pdf", side_effect=fake_pdf), \
            patch("src.api.routes.email.send_email", new=AsyncMock()):
        response = client.post(f"/api/email/invoice/{bill['id']}", json={"to": "supplier@example.com"})
    assert response.status_code == 200, response.text
    assert captured["settlement"] == {"paid_amount": 58000.0, "tds_amount": 1000.0, "remaining_amount": 0.0}


def test_emailed_sales_invoice_has_no_settlement_block(client, db_session, sections):
    customer = create_ledger(client, "Acme", pan="AAACA1234A", party_type="company")
    invoice = create_invoice(client, customer, 1000, "2026-05-10")
    captured = {}

    def fake_pdf(*args, **kwargs):
        captured.update(kwargs)
        return BytesIO(b"%PDF-1.4")

    with patch("src.api.routes.email._build_invoice_pdf", side_effect=fake_pdf), \
            patch("src.api.routes.email.send_email", new=AsyncMock()):
        response = client.post(f"/api/email/invoice/{invoice['id']}", json={"to": "buyer@example.com"})
    assert response.status_code == 200, response.text
    assert captured["settlement"] is None


def test_purchase_bill_pdf_html_from_the_email_builder_shows_tds(client, db_session, sections):
    from src.api.routes.invoices import _build_invoice_html

    _, bill, _ = _payment_with_tds(client, db_session, sections)
    invoice = db_session.get(Invoice, bill["id"])
    html = _build_invoice_html(
        invoice, [], [], settlement={"paid_amount": 58000.0, "tds_amount": 1000.0, "remaining_amount": 0.0},
    )
    assert "TDS deducted:" in html
    assert "Paid to supplier:" in html
    assert ledger_balance(client, invoice.ledger_id) == 0
