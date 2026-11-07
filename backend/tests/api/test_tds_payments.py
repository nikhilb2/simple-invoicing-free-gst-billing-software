"""TDS deducted on payments to suppliers (#770)."""

import csv
from io import StringIO

import pytest

from src.models.company import CompanyProfile
from tests.api.tds_helpers import (
    add_sections,
    create_account,
    create_invoice,
    create_ledger,
    enable_purchase_tds,
    get_invoice,
    ledger_balance,
    post_voucher,
    statement,
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


def _contractor_example(client, db_session, sections, *, account_id=None):
    """₹50,000 + 18% GST from a company contractor; 2% of ₹50,000 kept back."""
    enable_purchase_tds(db_session, client=client)
    supplier = create_ledger(client, "BuildCo Pvt Ltd", pan="AABCB1234C", party_type="company")
    bill = create_invoice(client, supplier, 50000, "2026-06-15", voucher_type="purchase")
    assert bill["total_amount"] == 59000
    response = post_voucher(
        client, supplier, 58000, [_tds(bill["id"], 58000, 1000, sections["contractor"].id)],
        "2026-06-20T10:00:00", voucher_type="payment", account_id=account_id,
    )
    assert response.status_code == 200, response.text
    return supplier, bill, response.json()


def test_setting_is_off_by_default_and_payment_tds_is_refused(client, db_session, sections):
    supplier = create_ledger(client, "BuildCo Pvt Ltd", pan="AABCB1234C", party_type="company")
    bill = create_invoice(client, supplier, 50000, "2026-06-15", voucher_type="purchase")
    assert client.get("/api/company/").json()["enable_purchase_tds"] is False
    response = post_voucher(
        client, supplier, 58000, [_tds(bill["id"], 58000, 1000, sections["contractor"].id)],
        "2026-06-20T10:00:00", voucher_type="payment",
    )
    assert response.status_code == 400
    assert "turned off" in response.json()["detail"]
    # A plain payment still works exactly as before.
    response = post_voucher(
        client, supplier, 59000, [{"invoice_id": bill["id"], "allocated_amount": 59000}],
        "2026-06-20T10:00:00", voucher_type="payment",
    )
    assert response.status_code == 200, response.text
    assert get_invoice(client, bill["id"])["payment_status"] == "paid"


def test_turning_the_setting_on_needs_a_tan(client, db_session):
    profile = client.get("/api/company/").json()
    payload = {key: profile[key] for key in ("name", "address", "gst", "phone_number", "currency_code")}
    payload["name"] = payload["name"] or "My Co"
    payload["address"] = payload["address"] or "Pune"

    response = client.put("/api/company/", json={**payload, "enable_purchase_tds": True})
    assert response.status_code == 400
    assert "TAN" in response.json()["detail"]

    response = client.put("/api/company/", json={**payload, "tan": "PNEA12345B", "enable_purchase_tds": True})
    assert response.status_code == 200, response.text
    assert response.json()["enable_purchase_tds"] is True
    assert response.json()["tan"] == "PNEA12345B"

    # A partial save that does not mention the setting keeps it on.
    response = client.put("/api/company/", json={**payload})
    assert response.status_code == 200, response.text
    assert response.json()["enable_purchase_tds"] is True
    db_session.expire_all()
    assert db_session.query(CompanyProfile).first().enable_purchase_tds is True


def test_contractor_example_settles_the_bill_and_cash_falls_by_58000(client, db_session, sections):
    account_id = create_account(client)
    supplier, bill, payment = _contractor_example(client, db_session, sections, account_id=account_id)

    allocation = payment["invoice_allocations"][0]
    assert payment["amount"] == 58000
    assert allocation["tds_amount"] == 1000
    assert allocation["tds_rate"] == 2
    assert allocation["tds_section_ref"] == "393(1) Sl. No. 6(i)"

    stored = get_invoice(client, bill["id"])
    assert stored["payment_status"] == "paid"
    assert stored["remaining_amount"] == 0
    assert stored["paid_amount"] == 58000
    assert stored["tds_amount"] == 1000
    assert stored["taxable_amount"] == 50000
    assert stored["total_tax_amount"] == 9000

    # Only the cash leaves the account.
    payments = client.get("/api/payments/").json()
    assert [p["amount"] for p in payments if p["account_id"] == account_id] == [58000]
    day_book = client.get("/api/ledgers/day-book", params={"from_date": "2026-06-01", "to_date": "2026-06-30"}).json()
    assert sum(e["debit"] for e in day_book["entries"] if e["entry_type"] == "payment") == 58000

    # The supplier's ledger is debited by both the cash and the TDS.
    assert ledger_balance(client, supplier) == 0
    body = statement(client, supplier)
    tds_lines = [e for e in body["entries"] if e["entry_type"] == "tds"]
    assert [(line["debit"], line["credit"]) for line in tds_lines] == [(1000, 0)]
    assert tds_lines[0]["particulars"].startswith("TDS deducted, s.393(1) Sl. No. 6(i)")

    # Nothing left to pay.
    unpaid = client.get(f"/api/ledgers/{supplier}/unpaid-invoices", params={"voucher_type": "payment"}).json()
    assert unpaid == []


def test_contractor_suggestion_is_two_percent_for_a_company(client, db_session, sections):
    enable_purchase_tds(db_session, client=client)
    supplier = create_ledger(client, "BuildCo Pvt Ltd", pan="AABCB1234C", party_type="company")
    bill = create_invoice(client, supplier, 50000, "2026-06-15", voucher_type="purchase")
    body = _suggest(client, bill["id"], sections["contractor"].id)
    assert body["applies"] is True
    assert body["rate"] == 2
    assert body["base_amount"] == 50000
    assert body["amount"] == 1000


def test_small_bill_suggests_no_tds_until_the_year_crosses_the_threshold(client, db_session, sections):
    enable_purchase_tds(db_session, client=client)
    contractor = create_ledger(client, "Ravi Kumar", pan="ABCPK1234D", party_type="individual")
    first = create_invoice(client, contractor, 20000, "2026-05-01", voucher_type="purchase")
    body = _suggest(client, first["id"], sections["contractor"].id)
    assert body["applies"] is False
    assert body["amount"] == 0
    assert "₹20,000.00" in body["reason"]
    assert "₹30,000.00" in body["reason"]
    assert "₹1,00,000.00" in body["reason"]

    # Three more bills under ₹30,000 each: 20,000 + 25,000 + 25,000 = 70,000, still no TDS...
    second = create_invoice(client, contractor, 25000, "2026-06-01", voucher_type="purchase")
    third = create_invoice(client, contractor, 25000, "2026-07-01", voucher_type="purchase")
    assert _suggest(client, third["id"], sections["contractor"].id)["applies"] is False
    assert _suggest(client, second["id"], sections["contractor"].id)["tax_year_total"] == 45000

    # ...until one takes the year above ₹1,00,000: TDS at 1% for an individual.
    fourth = create_invoice(client, contractor, 29000, "2026-08-01", voucher_type="purchase")
    body = _suggest(client, fourth["id"], sections["contractor"].id)
    assert body["tax_year_total"] == 99000
    assert body["applies"] is False

    fifth = create_invoice(client, contractor, 2000, "2026-08-15", voucher_type="purchase")
    body = _suggest(client, fifth["id"], sections["contractor"].id)
    assert body["tax_year_total"] == 101000
    assert body["applies"] is True
    assert body["rate"] == 1
    assert body["amount"] == 20
    assert "Earlier bills" in body["reason"]


def test_bills_from_last_tax_year_do_not_count(client, db_session, sections):
    enable_purchase_tds(db_session, client=client)
    contractor = create_ledger(client, "Ravi Kumar", pan="ABCPK1234D", party_type="individual")
    create_invoice(client, contractor, 29000, "2026-03-20", voucher_type="purchase")
    create_invoice(client, contractor, 29000, "2026-03-25", voucher_type="purchase")
    create_invoice(client, contractor, 29000, "2026-03-30", voucher_type="purchase")
    bill = create_invoice(client, contractor, 29000, "2026-04-10", voucher_type="purchase")
    body = _suggest(client, bill["id"], sections["contractor"].id)
    assert body["tax_year_total"] == 29000
    assert body["applies"] is False


def test_supplier_without_pan_gets_the_s397_2_rate(client, db_session, sections):
    enable_purchase_tds(db_session, client=client)
    supplier = create_ledger(client, "No PAN Works", party_type="company")
    bill = create_invoice(client, supplier, 50000, "2026-06-15", voucher_type="purchase")
    body = _suggest(client, bill["id"], sections["contractor"].id)
    assert body["has_pan"] is False
    assert body["rate"] == 20
    assert body["amount"] == 10000
    assert "397(2)" in body["reason"]

    response = post_voucher(
        client, supplier, 49000, [_tds(bill["id"], 49000, 10000, sections["contractor"].id)],
        "2026-06-20T10:00:00", voucher_type="payment",
    )
    assert response.status_code == 200, response.text
    assert response.json()["invoice_allocations"][0]["tds_rate"] == 20


def test_purchase_of_goods_suggests_tds_only_above_fifty_lakh(client, db_session, sections):
    enable_purchase_tds(db_session, client=client)
    seller = create_ledger(client, "Steel Traders", pan="AAFCS1234E", party_type="company")
    first = create_invoice(client, seller, 4900000, "2026-05-01", voucher_type="purchase", gst_rate=0)
    body = _suggest(client, first["id"], sections["goods"].id)
    assert body["applies"] is False

    second = create_invoice(client, seller, 200000, "2026-06-01", voucher_type="purchase", gst_rate=0)
    body = _suggest(client, second["id"], sections["goods"].id)
    assert body["applies"] is True
    assert body["base_amount"] == 100000
    assert body["amount"] == 100  # 0.1% of the ₹1,00,000 above ₹50 lakh


def test_tds_over_settling_a_bill_is_rejected(client, db_session, sections):
    enable_purchase_tds(db_session, client=client)
    supplier = create_ledger(client, "BuildCo Pvt Ltd", pan="AABCB1234C", party_type="company")
    bill = create_invoice(client, supplier, 50000, "2026-06-15", voucher_type="purchase")
    response = post_voucher(
        client, supplier, 58000, [_tds(bill["id"], 58000, 1000.01, sections["contractor"].id)],
        "2026-06-20T10:00:00", voucher_type="payment",
    )
    assert response.status_code == 400


def test_editing_and_cancelling_a_payment_with_tds(client, db_session, sections):
    supplier, bill, payment = _contractor_example(client, db_session, sections)
    response = client.put(f"/api/payments/{payment['id']}", json={
        "voucher_type": "payment",
        "amount": 58000,
        "date": "2026-06-20T10:00:00",
        "invoice_allocations": [_tds(bill["id"], 58000, 500, sections["contractor"].id)],
    })
    assert response.status_code == 200, response.text
    assert get_invoice(client, bill["id"])["remaining_amount"] == 500
    assert ledger_balance(client, supplier) == -500

    assert client.delete(f"/api/payments/{payment['id']}").status_code == 200
    assert get_invoice(client, bill["id"])["remaining_amount"] == 59000
    assert client.get("/api/tds/payable", params={"tax_year": 2026}).json()["rows"] == []


def test_payable_report_lists_the_deduction_in_the_right_quarter(client, db_session, sections):
    supplier, bill, _ = _contractor_example(client, db_session, sections)

    q1 = client.get("/api/tds/payable", params={"tax_year": 2026, "quarter": 1})
    assert q1.status_code == 200, q1.text
    body = q1.json()
    assert body["kind"] == "payable"
    assert len(body["rows"]) == 1
    row = body["rows"][0]
    assert row["party_name"] == "BuildCo Pvt Ltd"
    assert row["party_pan"] == "AABCB1234C"
    assert row["supplier_invoice_number"] == bill["supplier_invoice_number"]
    assert row["section_ref"] == "393(1) Sl. No. 6(i)"
    assert row["rate"] == 2
    assert row["base_amount"] == 50000
    assert row["tds_amount"] == 1000
    assert row["quarter"] == 1
    assert body["totals_by_section"] == [{
        "key": "393(1) Sl. No. 6(i)", "label": "s.393(1) Sl. No. 6(i)", "pan": None,
        "count": 1, "base_amount": 50000.0, "tds_amount": 1000.0,
    }]
    assert body["total_tds"] == 1000

    assert client.get("/api/tds/payable", params={"tax_year": 2026, "quarter": 2}).json()["rows"] == []
    assert client.get("/api/tds/payable", params={"tax_year": 2025}).json()["rows"] == []
    assert client.get("/api/tds/receivable", params={"tax_year": 2026}).json()["rows"] == []

    exported = client.get("/api/tds/payable/csv", params={"tax_year": 2026, "quarter": 1})
    assert exported.status_code == 200, exported.text
    assert "tds_payable_2026-27_q1.csv" in exported.headers["content-disposition"]
    lines = list(csv.reader(StringIO(exported.content.decode("utf-8-sig"))))
    header = next(line for line in lines if line and line[0] == "Quarter")
    data = lines[lines.index(header) + 1]
    assert data[header.index("Supplier")] == "BuildCo Pvt Ltd"
    assert data[header.index("Supplier PAN")] == "AABCB1234C"
    assert data[header.index("Section")] == "s.393(1) Sl. No. 6(i)"
    assert data[header.index("TDS amount")] == "1000.00"
    assert "Certificate received" not in header


def test_unknown_report_kind_is_rejected(client):
    assert client.get("/api/tds/elsewhere").status_code == 422
