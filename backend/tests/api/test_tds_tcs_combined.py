"""A sales invoice that carries TCS (#769) and is settled by a receipt with TDS (#768).

remaining = total (incl. TCS) - credit notes (incl. their TCS share) - cash - TDS.
"""

from decimal import Decimal

import pytest

from src.models.company import CompanyProfile
from src.models.tax_withholding_section import TaxWithholdingSection
from src.services.tds_allocations import section_base
from tests.api.tds_helpers import ledger_balance, post_voucher, statement
from tests.api.test_tcs_invoices import SCRAP_2025, _seed_sections

SELLER_GSTIN = "29AAAAA0000A1Z5"
BUYER_GSTIN = "29ABCDE1234F1ZW"
PROFESSIONAL_FEES = "Professional fees and other specified sums"


def _ok(response, status=200):
    assert response.status_code == status, response.text
    return response.json()


@pytest.fixture
def company(client, db_session):
    _seed_sections(db_session)
    assert client.get("/api/company/").status_code == 200
    profile = db_session.query(CompanyProfile).first()
    profile.gst = SELLER_GSTIN
    profile.enable_tcs = True
    db_session.commit()
    return profile


def _section_id(db, section_ref, nature=None):
    query = db.query(TaxWithholdingSection.id).filter(TaxWithholdingSection.section_ref == section_ref)
    if nature:
        query = query.filter(TaxWithholdingSection.nature == nature)
    return query.scalar()


def _tcs_invoice(client, db_session, *, quantity=1, unit_price=100000):
    ledger = _ok(client.post("/api/ledgers/", json={
        "name": "Scrap Buyer", "address": "Bengaluru", "gst": BUYER_GSTIN, "pan": "ABCDE1234F",
        "party_type": "company", "phone_number": "9999999999",
    }))["id"]
    product = _ok(client.post("/api/products/", json={
        "sku": "SCRAP-TDS", "name": "Scrap", "price": unit_price, "gst_rate": 18,
        "hsn_sac": "7204", "maintain_inventory": False,
    }))["id"]
    invoice = _ok(client.post("/api/invoices/", json={
        "ledger_id": ledger, "voucher_type": "sales", "invoice_date": "2026-05-10",
        "items": [{"product_id": product, "quantity": quantity, "unit_price": unit_price}],
        "tcs_section_id": _section_id(db_session, SCRAP_2025),
    }))
    return ledger, invoice


def _tds_section(db_session):
    return _section_id(db_session, "393(1) Sl. No. 6(iii)", PROFESSIONAL_FEES)


def test_cash_plus_tds_settles_a_tcs_invoice_and_zeroes_the_ledger(client, db_session, company):
    ledger, invoice = _tcs_invoice(client, db_session)
    # 1,00,000 + 18% GST = 1,18,000; TCS 2% of that = 2,360; total 1,20,360.
    assert invoice["tcs_amount"] == 2360
    assert invoice["total_amount"] == 120360

    # The customer keeps back 10% TDS on the pre-GST 1,00,000 and pays the rest.
    response = post_voucher(client, ledger, 110360, [{
        "invoice_id": invoice["id"], "allocated_amount": 110360,
        "tds_amount": 10000, "tds_section_id": _tds_section(db_session),
    }], "2026-05-20T10:00:00")
    receipt = _ok(response)
    allocation = receipt["invoice_allocations"][0]
    assert allocation["tds_base_amount"] == 100000

    stored = _ok(client.get(f"/api/invoices/{invoice['id']}"))
    assert stored["remaining_amount"] == 0
    assert stored["payment_status"] == "paid"
    assert stored["paid_amount"] == 110360
    assert stored["tds_amount"] == 10000
    assert stored["tcs_amount"] == 2360

    assert ledger_balance(client, ledger) == 0
    assert statement(client, ledger)["closing_balance"] == 0


def test_tds_cannot_settle_more_than_the_tcs_invoice_total(client, db_session, company):
    ledger, invoice = _tcs_invoice(client, db_session)
    response = post_voucher(client, ledger, 110360.01, [{
        "invoice_id": invoice["id"], "allocated_amount": 110360.01,
        "tds_amount": 10000, "tds_section_id": _tds_section(db_session),
    }], "2026-05-20T10:00:00")
    assert response.status_code == 400
    assert "TDS" in response.json()["detail"]


def test_credit_note_cash_and_tds_together_settle_a_tcs_invoice(client, db_session, company):
    ledger, invoice = _tcs_invoice(client, db_session, quantity=3, unit_price=10000)
    # 30,000 + 5,400 GST = 35,400; TCS 2% = 708; total 36,108.
    assert invoice["total_amount"] == 36108

    note = _ok(client.post("/api/credit-notes/", json={
        "ledger_id": ledger, "invoice_ids": [invoice["id"]], "credit_note_type": "return",
        "direction": "outward", "credit_note_date": "2026-05-12",
        "items": [{"invoice_id": invoice["id"], "invoice_item_id": invoice["items"][0]["id"], "quantity": 1}],
    }), 201)
    assert note["tcs_amount"] == 236
    assert note["total_amount"] == 12036

    after_note = _ok(client.get(f"/api/invoices/{invoice['id']}"))
    assert after_note["remaining_amount"] == 24072

    # TDS on the 20,000 still billed; the rest in cash.
    response = post_voucher(client, ledger, 22072, [{
        "invoice_id": invoice["id"], "allocated_amount": 22072,
        "tds_amount": 2000, "tds_section_id": _tds_section(db_session),
    }], "2026-05-20T10:00:00")
    _ok(response)

    stored = _ok(client.get(f"/api/invoices/{invoice['id']}"))
    assert stored["remaining_amount"] == 0
    assert stored["payment_status"] == "paid"
    assert ledger_balance(client, ledger) == 0
    assert statement(client, ledger)["closing_balance"] == 0


def test_gross_base_tds_leaves_out_the_tcs(client, db_session, company):
    """No seeded TDS section is on the gross bill, but if one were, TCS is not part of it."""
    _, invoice = _tcs_invoice(client, db_session)
    section = TaxWithholdingSection(kind="tds", base="gross")

    class _Invoice:
        total_amount = invoice["total_amount"]
        tcs_amount = invoice["tcs_amount"]
        taxable_amount = invoice["taxable_amount"]

    assert section_base(section, _Invoice()) == Decimal("118000.00")
