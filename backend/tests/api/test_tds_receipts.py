"""TDS deducted by the customer when receiving payment (#768)."""

import csv
from io import StringIO

import pytest

from src.models.payment import PaymentInvoiceAllocation
from tests.api.tds_helpers import (
    add_sections,
    create_account,
    create_invoice,
    create_ledger,
    get_invoice,
    ledger_balance,
    post_voucher,
    set_company_pan,
    statement,
)


@pytest.fixture
def sections(db_session):
    return add_sections(db_session)


@pytest.fixture(autouse=True)
def company_pan(client, db_session):
    # On a receipt our business is the deductee, so the rate follows our PAN.
    return set_company_pan(client, db_session, "AAACM1234M")


@pytest.fixture
def customer(client):
    return create_ledger(client, "Acme Clients Pvt Ltd", pan="AAACA1234A", party_type="company")


def _tds(invoice_id, cash, tds, section_id):
    return {"invoice_id": invoice_id, "allocated_amount": cash, "tds_amount": tds, "tds_section_id": section_id}


def _example(client, customer, sections, *, account_id=None, when="2026-05-20T10:00:00"):
    """The issue's example: ₹1,00,000 + 18% GST, customer keeps back 10% of ₹1,00,000."""
    invoice = create_invoice(client, customer, 100000, "2026-05-10")
    assert invoice["total_amount"] == 118000
    response = post_voucher(
        client, customer, 108000, [_tds(invoice["id"], 108000, 10000, sections["prof"].id)], when, account_id=account_id,
    )
    assert response.status_code == 200, response.text
    return invoice, response.json()


def test_cash_plus_tds_settles_the_invoice_and_zeroes_the_ledger(client, customer, sections):
    invoice, receipt = _example(client, customer, sections)

    allocation = receipt["invoice_allocations"][0]
    assert receipt["amount"] == 108000
    assert allocation["allocated_amount"] == 108000
    assert allocation["tds_amount"] == 10000
    assert allocation["tds_section_ref"] == "393(1) Sl. No. 6(iii)"
    assert allocation["tds_rate"] == 10
    assert allocation["tds_base_amount"] == 100000

    stored = get_invoice(client, invoice["id"])
    assert stored["payment_status"] == "paid"
    assert stored["remaining_amount"] == 0
    assert stored["paid_amount"] == 108000
    assert stored["tds_amount"] == 10000
    # TDS never touches the GST figures.
    assert stored["taxable_amount"] == 100000
    assert stored["total_tax_amount"] == 18000

    assert ledger_balance(client, customer) == 0
    body = statement(client, customer)
    assert body["closing_balance"] == 0
    tds_lines = [entry for entry in body["entries"] if entry["entry_type"] == "tds"]
    assert len(tds_lines) == 1
    assert tds_lines[0]["credit"] == 10000
    assert tds_lines[0]["debit"] == 0
    assert tds_lines[0]["particulars"].startswith("TDS deducted, s.393(1) Sl. No. 6(iii)")

    dues = client.get("/api/invoices/dues")
    assert dues.status_code == 200, dues.text
    assert invoice["id"] not in [row["id"] for row in dues.json()["items"]]


def test_cash_and_day_book_count_only_the_cash(client, customer, sections):
    account_id = create_account(client)
    _example(client, customer, sections, account_id=account_id)

    payments = client.get("/api/payments/").json()
    assert [p["amount"] for p in payments if p["account_id"] == account_id] == [108000]

    day_book = client.get("/api/ledgers/day-book", params={"from_date": "2026-05-01", "to_date": "2026-05-31"})
    assert day_book.status_code == 200, day_book.text
    receipts = [entry for entry in day_book.json()["entries"] if entry["entry_type"] == "payment"]
    assert sum(entry["credit"] for entry in receipts) == 108000
    assert all(entry["entry_type"] != "tds" for entry in day_book.json()["entries"])


def test_statement_opening_balance_counts_earlier_tds(client, customer, sections):
    _example(client, customer, sections)
    body = statement(client, customer, from_date="2026-06-01", to_date="2026-06-30")
    assert body["opening_balance"] == 0
    assert body["closing_balance"] == 0


def test_tds_that_over_settles_the_invoice_is_rejected(client, customer, sections):
    invoice = create_invoice(client, customer, 100000, "2026-05-10")
    response = post_voucher(
        client, customer, 108000, [_tds(invoice["id"], 108000, 10000.01, sections["prof"].id)], "2026-05-20T10:00:00",
    )
    assert response.status_code == 400
    assert "TDS" in response.json()["detail"]
    assert get_invoice(client, invoice["id"])["payment_status"] == "unpaid"


def test_tds_does_not_count_towards_the_receipt_amount(client, customer, sections):
    invoice = create_invoice(client, customer, 100000, "2026-05-10")
    # Cash allocated above the receipt amount is still rejected...
    response = post_voucher(
        client, customer, 100000, [_tds(invoice["id"], 108000, 10000, sections["prof"].id)], "2026-05-20T10:00:00",
    )
    assert response.status_code == 400
    # ...but the TDS on top of a fully allocated receipt is fine.
    response = post_voucher(
        client, customer, 100000, [_tds(invoice["id"], 100000, 10000, sections["prof"].id)], "2026-05-20T10:00:00",
    )
    assert response.status_code == 200, response.text
    assert get_invoice(client, invoice["id"])["remaining_amount"] == 8000


def test_tds_needs_a_section(client, customer, sections):
    invoice = create_invoice(client, customer, 100000, "2026-05-10")
    response = post_voucher(
        client, customer, 108000, [{"invoice_id": invoice["id"], "allocated_amount": 108000, "tds_amount": 10000}],
        "2026-05-20T10:00:00",
    )
    assert response.status_code == 400
    assert "section" in response.json()["detail"].lower()


def test_a_receipt_without_tds_is_unchanged(client, customer, sections):
    invoice = create_invoice(client, customer, 100000, "2026-05-10")
    response = post_voucher(
        client, customer, 118000, [{"invoice_id": invoice["id"], "allocated_amount": 118000}], "2026-05-20T10:00:00",
    )
    assert response.status_code == 200, response.text
    allocation = response.json()["invoice_allocations"][0]
    assert allocation["tds_amount"] == 0
    assert allocation["tds_section_id"] is None
    assert get_invoice(client, invoice["id"])["payment_status"] == "paid"
    assert [e for e in statement(client, customer)["entries"] if e["entry_type"] == "tds"] == []


def test_editing_a_receipt_updates_its_tds(client, customer, sections, db_session):
    invoice, receipt = _example(client, customer, sections)

    # Lower the TDS: the invoice is part-paid again.
    response = client.put(f"/api/payments/{receipt['id']}", json={
        "voucher_type": "receipt",
        "amount": 108000,
        "date": "2026-05-20T10:00:00",
        "invoice_allocations": [_tds(invoice["id"], 108000, 5000, sections["prof"].id)],
    })
    assert response.status_code == 200, response.text
    stored = get_invoice(client, invoice["id"])
    assert stored["payment_status"] == "partial"
    assert stored["remaining_amount"] == 5000
    assert ledger_balance(client, customer) == 5000

    # Remove the TDS altogether.
    response = client.put(f"/api/payments/{receipt['id']}", json={
        "voucher_type": "receipt",
        "amount": 108000,
        "date": "2026-05-20T10:00:00",
        "invoice_allocations": [{"invoice_id": invoice["id"], "allocated_amount": 108000}],
    })
    assert response.status_code == 200, response.text
    assert get_invoice(client, invoice["id"])["remaining_amount"] == 10000
    assert ledger_balance(client, customer) == 10000
    assert [e for e in statement(client, customer)["entries"] if e["entry_type"] == "tds"] == []


def test_editing_keeps_the_stored_section_copies(client, customer, sections, db_session):
    invoice, receipt = _example(client, customer, sections)

    # Our PAN goes missing: a fresh entry would get the no-PAN rate, but an
    # edit that keeps the section keeps the rate copied at entry time.
    set_company_pan(client, db_session, None)

    response = client.put(f"/api/payments/{receipt['id']}", json={
        "voucher_type": "receipt",
        "amount": 108000,
        "date": "2026-05-21T10:00:00",
        "invoice_allocations": [_tds(invoice["id"], 108000, 10000, sections["prof"].id)],
    })
    assert response.status_code == 200, response.text
    assert response.json()["invoice_allocations"][0]["tds_rate"] == 10


def test_updating_a_receipt_without_allocations_keeps_its_tds(client, customer, sections):
    invoice, receipt = _example(client, customer, sections)
    response = client.put(f"/api/payments/{receipt['id']}", json={
        "voucher_type": "receipt",
        "amount": 108000,
        "notes": "Bank ref 42",
    })
    assert response.status_code == 200, response.text
    assert response.json()["invoice_allocations"][0]["tds_amount"] == 10000
    assert get_invoice(client, invoice["id"])["payment_status"] == "paid"


def test_deleting_a_receipt_removes_its_tds(client, customer, sections):
    invoice, receipt = _example(client, customer, sections)
    response = client.delete(f"/api/payments/{receipt['id']}")
    assert response.status_code == 200, response.text

    stored = get_invoice(client, invoice["id"])
    assert stored["payment_status"] == "unpaid"
    assert stored["remaining_amount"] == 118000
    assert stored["tds_amount"] == 0
    assert ledger_balance(client, customer) == 118000
    assert [e for e in statement(client, customer)["entries"] if e["entry_type"] == "tds"] == []
    report = client.get("/api/tds/receivable", params={"tax_year": 2026}).json()
    assert report["rows"] == []


def test_invoice_with_a_credit_note_and_tds(client, customer, sections):
    invoice = create_invoice(client, customer, 100000, "2026-05-10", quantity=10)
    response = client.post("/api/credit-notes/", json={
        "ledger_id": customer,
        "invoice_ids": [invoice["id"]],
        "credit_note_type": "return",
        "direction": "outward",
        "items": [{"invoice_id": invoice["id"], "invoice_item_id": invoice["items"][0]["id"], "quantity": 1}],
    })
    assert response.status_code == 201, response.text
    # 1 of 10 units returned: ₹11,800 credited, ₹1,06,200 left on ₹90,000 taxable.
    assert get_invoice(client, invoice["id"])["remaining_amount"] == 106200

    over = post_voucher(
        client, customer, 97200, [_tds(invoice["id"], 97200, 9000.01, sections["prof"].id)], "2026-05-20T10:00:00",
    )
    assert over.status_code == 400

    response = post_voucher(
        client, customer, 97200, [_tds(invoice["id"], 97200, 9000, sections["prof"].id)], "2026-05-20T10:00:00",
    )
    assert response.status_code == 200, response.text
    assert get_invoice(client, invoice["id"])["payment_status"] == "paid"
    assert ledger_balance(client, customer) == 0


@pytest.mark.parametrize(
    "invoice_date,receipt_date,section_key,ok",
    [
        ("2026-03-31", "2026-03-31T10:00:00", "194J", True),
        ("2026-03-31", "2026-03-31T10:00:00", "prof", False),
        ("2026-04-01", "2026-04-02T10:00:00", "prof", True),
        ("2026-04-01", "2026-04-02T10:00:00", "194J", False),
        # Booked in March, paid in April: the earlier date (the invoice) decides.
        ("2026-03-31", "2026-04-15T10:00:00", "194J", True),
        ("2026-03-31", "2026-04-15T10:00:00", "prof", False),
    ],
)
def test_section_must_be_in_force_on_the_invoice_date(client, customer, sections, invoice_date, receipt_date, section_key, ok):
    invoice = create_invoice(client, customer, 100000, invoice_date)
    response = post_voucher(
        client, customer, 108000, [_tds(invoice["id"], 108000, 10000, sections[section_key].id)], receipt_date,
    )
    if ok:
        assert response.status_code == 200, response.text
        assert response.json()["invoice_allocations"][0]["tds_section_ref"] == sections[section_key].section_ref
    else:
        assert response.status_code == 400
        assert "not in force" in response.json()["detail"]


def test_sections_offered_switch_on_1_april_2026(client, sections):
    march = client.get("/api/tax-withholding-sections", params={"kind": "tds", "date": "2026-03-31"}).json()
    april = client.get("/api/tax-withholding-sections", params={"kind": "tds", "date": "2026-04-01"}).json()
    assert {row["act"] for row in march} == {1961}
    assert {row["act"] for row in april} == {2025}


def test_suggestion_is_rate_times_taxable_amount(client, customer, sections):
    invoice = create_invoice(client, customer, 100000, "2026-05-10")
    response = client.get("/api/tds/suggestion", params={"invoice_id": invoice["id"], "section_id": sections["prof"].id})
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["base_amount"] == 100000
    assert body["rate"] == 10
    assert body["amount"] == 10000
    assert body["applies"] is True


def test_receivable_report_lists_the_deduction_in_the_invoice_quarter(client, customer, sections):
    # Invoice in Q1 (June), receipt in Q2 (July): the customer deducted in Q1.
    invoice = create_invoice(client, customer, 100000, "2026-06-30")
    response = post_voucher(
        client, customer, 108000, [_tds(invoice["id"], 108000, 10000, sections["prof"].id)], "2026-07-05T10:00:00",
    )
    assert response.status_code == 200, response.text

    q1 = client.get("/api/tds/receivable", params={"tax_year": 2026, "quarter": 1})
    assert q1.status_code == 200, q1.text
    body = q1.json()
    assert body["tax_year_label"] == "2026-27"
    assert len(body["rows"]) == 1
    row = body["rows"][0]
    assert row["party_name"] == "Acme Clients Pvt Ltd"
    assert row["party_pan"] == "AAACA1234A"
    assert row["invoice_number"] == invoice["invoice_number"]
    assert row["section_ref"] == "393(1) Sl. No. 6(iii)"
    assert row["rate"] == 10
    assert row["taxable_amount"] == 100000
    assert row["tds_amount"] == 10000
    assert row["quarter"] == 1
    assert body["total_tds"] == 10000
    assert body["totals_by_section"][0]["label"] == "s.393(1) Sl. No. 6(iii)"
    assert body["totals_by_section"][0]["tds_amount"] == 10000
    assert body["totals_by_party"][0]["label"] == "Acme Clients Pvt Ltd"
    assert body["totals_by_party"][0]["pan"] == "AAACA1234A"

    q2 = client.get("/api/tds/receivable", params={"tax_year": 2026, "quarter": 2}).json()
    assert q2["rows"] == []
    # A payable report never shows what customers deducted.
    assert client.get("/api/tds/payable", params={"tax_year": 2026}).json()["rows"] == []

    exported = client.get("/api/tds/receivable/csv", params={"tax_year": 2026, "quarter": 1})
    assert exported.status_code == 200, exported.text
    assert exported.headers["content-type"].startswith("text/csv")
    assert "tds_receivable_2026-27_q1.csv" in exported.headers["content-disposition"]
    lines = list(csv.reader(StringIO(exported.content.decode("utf-8-sig"))))
    header = next(line for line in lines if line and line[0] == "Quarter")
    data = lines[lines.index(header) + 1]
    assert data[header.index("Customer")] == "Acme Clients Pvt Ltd"
    assert data[header.index("Section")] == "s.393(1) Sl. No. 6(iii)"
    assert data[header.index("TDS amount")] == "10000.00"
    assert data[header.index("Certificate received")] == "No"


def test_certificate_received_tick(client, customer, sections, db_session):
    _, receipt = _example(client, customer, sections)
    allocation_id = receipt["invoice_allocations"][0]["id"]
    response = client.patch(f"/api/tds/allocations/{allocation_id}", json={"certificate_received": True})
    assert response.status_code == 200, response.text
    assert response.json()["certificate_received"] is True
    report = client.get("/api/tds/receivable", params={"tax_year": 2026}).json()
    assert report["rows"][0]["certificate_received"] is True
    db_session.expire_all()
    assert db_session.get(PaymentInvoiceAllocation, allocation_id).tds_certificate_received is True


def test_ageing_and_ledger_open_amounts_count_tds_as_settled(client, customer, sections):
    invoice = create_invoice(client, customer, 100000, "2026-05-10")
    response = post_voucher(
        client, customer, 100000, [_tds(invoice["id"], 100000, 10000, sections["prof"].id)], "2026-05-20T10:00:00",
    )
    assert response.status_code == 200, response.text
    dues = client.get("/api/invoices/dues").json()
    row = next(item for item in dues["items"] if item["id"] == invoice["id"])
    assert row["remaining_amount"] == 8000
    ageing = client.get("/api/invoices/dues/ageing")
    assert ageing.status_code == 200, ageing.text
    assert ageing.json()["total_remaining"] == 8000
