"""TDS on receipts (#768) and on payments to suppliers (#770), on PostgreSQL in both deployment modes.

Besides the money arithmetic through the real app (the app role under RLS in shared
hosting, the owner in single tenant), this proves the row lock: the invoices a receipt
or payment allocates against are locked FOR UPDATE, so two saved at once cannot both
spend the same remaining amount. SQLite ignores FOR UPDATE, so that can only be shown
here. Skipped when DATABASE_URL is not Postgres.
"""

import time
from concurrent.futures import ThreadPoolExecutor

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from app_main import app
from src.core.config import settings
from test_quotation_bounds_postgres import tenant  # noqa: F401
from test_quotation_convert_postgres import app_db, deployment, signed_in  # noqa: F401
from tests.api.tds_helpers import add_sections

pytestmark = pytest.mark.skipif(
    not settings.DATABASE_URL.startswith("postgres"),
    reason="row locks need Postgres",
)

LOCK_INVOICE = "SELECT id FROM invoices WHERE id = :id FOR UPDATE"


def _ok(response, status=200):
    assert response.status_code == status, response.text
    return response.json()


@pytest.fixture
def sections(app_db):
    with app_db.OwnerSession() as session:
        rows = add_sections(session)
        return {key: row.id for key, row in rows.items()}


@pytest.fixture
def books(tenant, sections):  # noqa: F811
    """A company with a PAN and TAN, purchase TDS on, and a company-type customer and supplier."""
    client = tenant["client"]
    profile = _ok(client.get("/api/company/"))
    _ok(client.put("/api/company/", json={
        **profile, "pan": "AAACM1234M", "tan": "MUMA12345B", "enable_purchase_tds": True,
    }))
    customer = _ok(client.get(f"/api/ledgers/{tenant['ledger']}"))
    _ok(client.put(f"/api/ledgers/{tenant['ledger']}", json={**customer, "pan": "AAACA1234A", "party_type": "company"}))
    supplier = _ok(client.post("/api/ledgers/", json={
        "name": "BuildCo Pvt Ltd", "address": "Pune", "phone_number": "9999999999", "pan": "AABCB1234C", "party_type": "company",
    }))
    return {**tenant, "sections": sections, "supplier": supplier["id"]}


def _invoice(books, *, ledger=None, voucher_type="sales", taxable=100000, invoice_date="2026-05-10"):
    payload = {
        "ledger_id": ledger or books["ledger"], "voucher_type": voucher_type, "tax_inclusive": False,
        "apply_round_off": False, "invoice_date": invoice_date,
        "items": [{"product_id": books["untaxed"], "quantity": 1, "unit_price": taxable, "gst_rate": 18}],
    }
    if voucher_type == "purchase":
        payload["supplier_invoice_number"] = "SUP-1"
    return _ok(books["client"].post("/api/invoices/", json=payload))


def _voucher(books, ledger, voucher_type, amount, allocations, when="2026-05-20T10:00:00"):
    return books["client"].post("/api/payments/", json={
        "ledger_id": ledger, "voucher_type": voucher_type, "amount": amount, "date": when, "mode": "bank",
        "invoice_allocations": allocations,
    })


def _allocation(invoice_id, cash, tds, section_id):
    return {"invoice_id": invoice_id, "allocated_amount": cash, "tds_amount": tds, "tds_section_id": section_id}


def _receipt(books, invoice, cash=108000, tds=10000):
    return _voucher(books, books["ledger"], "receipt", cash, [_allocation(invoice["id"], cash, tds, books["sections"]["prof"])])


def test_receipt_with_tds_settles_the_invoice(books):
    client = books["client"]
    invoice = _invoice(books)
    assert invoice["total_amount"] == 118000
    receipt = _ok(_receipt(books, invoice))
    saved = receipt["invoice_allocations"][0]
    assert (saved["allocated_amount"], saved["tds_amount"], saved["tds_rate"], saved["tds_base_amount"]) == (108000, 10000, 10, 100000)
    paid = _ok(client.get(f"/api/invoices/{invoice['id']}"))
    assert (paid["payment_status"], paid["paid_amount"], paid["tds_amount"], paid["remaining_amount"]) == ("paid", 108000, 10000, 0)
    assert paid["total_tax_amount"] == invoice["total_tax_amount"]
    entries = _ok(client.get(f"/api/ledgers/{books['ledger']}/statement", params={"from_date": "2026-04-01", "to_date": "2027-03-31"}))
    assert entries["closing_balance"] == 0
    assert [row["credit"] for row in entries["entries"] if row["entry_type"] == "tds"] == [10000]


def test_tds_leaves_a_partly_paid_invoice_with_the_rest_remaining(books):
    invoice = _invoice(books)
    _ok(_receipt(books, invoice, cash=50000, tds=10000))
    stored = _ok(books["client"].get(f"/api/invoices/{invoice['id']}"))
    assert (stored["payment_status"], stored["remaining_amount"]) == ("partial", 58000)


@pytest.mark.parametrize("cash,tds", [(108000, 10000.01), (118000, 1)])
def test_cash_plus_tds_cannot_exceed_the_remaining_amount(books, cash, tds):
    invoice = _invoice(books)
    response = _receipt(books, invoice, cash=cash, tds=tds)
    assert response.status_code == 400 and "remaining" in response.json()["detail"]
    assert _ok(books["client"].get("/api/payments/")) == []
    assert _ok(books["client"].get(f"/api/invoices/{invoice['id']}"))["remaining_amount"] == 118000


def test_tds_on_a_second_receipt_respects_what_the_first_already_took(books):
    invoice = _invoice(books)
    _ok(_receipt(books, invoice, cash=60000, tds=10000))
    response = _receipt(books, invoice, cash=48000, tds=1)
    assert response.status_code == 400 and "only has 48000.00 remaining" in response.json()["detail"]
    _ok(_receipt(books, invoice, cash=48000, tds=0))
    assert _ok(books["client"].get(f"/api/invoices/{invoice['id']}"))["payment_status"] == "paid"


def test_payment_to_a_supplier_with_tds(books):
    client = books["client"]
    bill = _invoice(books, ledger=books["supplier"], voucher_type="purchase", taxable=50000, invoice_date="2026-06-15")
    assert bill["total_amount"] == 59000
    payment = _ok(_voucher(
        books, books["supplier"], "payment", 58000,
        [_allocation(bill["id"], 58000, 1000, books["sections"]["contractor"])], "2026-06-20T10:00:00",
    ))
    saved = payment["invoice_allocations"][0]
    assert (saved["tds_amount"], saved["tds_rate"], saved["tds_base_amount"]) == (1000, 2, 50000)
    stored = _ok(client.get(f"/api/invoices/{bill['id']}"))
    assert (stored["payment_status"], stored["paid_amount"], stored["tds_amount"], stored["remaining_amount"]) == ("paid", 58000, 1000, 0)


def test_payment_tds_cannot_exceed_the_bill_remaining(books):
    bill = _invoice(books, ledger=books["supplier"], voucher_type="purchase", taxable=50000, invoice_date="2026-06-15")
    response = _voucher(
        books, books["supplier"], "payment", 58000,
        [_allocation(bill["id"], 58000, 1000.01, books["sections"]["contractor"])], "2026-06-20T10:00:00",
    )
    assert response.status_code == 400 and "remaining" in response.json()["detail"]
    assert _ok(books["client"].get(f"/api/invoices/{bill['id']}"))["remaining_amount"] == 59000


def test_payment_tds_is_refused_while_the_company_setting_is_off(books):
    client = books["client"]
    _ok(client.put("/api/company/", json={**_ok(client.get("/api/company/")), "enable_purchase_tds": False}))
    bill = _invoice(books, ledger=books["supplier"], voucher_type="purchase", taxable=50000, invoice_date="2026-06-15")
    response = _voucher(
        books, books["supplier"], "payment", 58000,
        [_allocation(bill["id"], 58000, 1000, books["sections"]["contractor"])], "2026-06-20T10:00:00",
    )
    assert response.status_code == 400 and "turned off" in response.json()["detail"]


def _pile_up_behind_a_lock(db, invoice_id: int, requests: list) -> list:
    """Hold the invoice row, start every request, let them all reach it, then let go."""
    owner = db.owner_engine.connect()
    holding = owner.begin()
    owner.execute(text(LOCK_INVOICE), {"id": invoice_id})
    try:
        with ThreadPoolExecutor(max_workers=len(requests)) as pool:
            futures = [pool.submit(request) for request in requests]
            time.sleep(1)
            assert not any(future.done() for future in futures), "a request went past a held invoice row lock"
            holding.commit()
            return [future.result(timeout=30) for future in futures]
    finally:
        owner.close()


def _post(path, body):
    return lambda: TestClient(app).post(path, json=body)


def test_saving_a_receipt_waits_for_a_lock_on_the_invoice(books, app_db):
    invoice = _invoice(books)
    body = {
        "ledger_id": books["ledger"], "voucher_type": "receipt", "amount": 108000, "date": "2026-05-20T10:00:00", "mode": "bank",
        "invoice_allocations": [_allocation(invoice["id"], 108000, 10000, books["sections"]["prof"])],
    }
    [response] = _pile_up_behind_a_lock(app_db, invoice["id"], [_post("/api/payments/", body)])
    assert response.status_code == 200, response.text


def test_saving_a_payment_to_a_supplier_waits_for_a_lock_on_the_bill(books, app_db):
    bill = _invoice(books, ledger=books["supplier"], voucher_type="purchase", taxable=50000, invoice_date="2026-06-15")
    body = {
        "ledger_id": books["supplier"], "voucher_type": "payment", "amount": 58000, "date": "2026-06-20T10:00:00", "mode": "bank",
        "invoice_allocations": [_allocation(bill["id"], 58000, 1000, books["sections"]["contractor"])],
    }
    [response] = _pile_up_behind_a_lock(app_db, bill["id"], [_post("/api/payments/", body)])
    assert response.status_code == 200, response.text


def test_two_receipts_at_once_cannot_both_take_the_same_remaining_amount(books, app_db):
    """Both read ₹1,18,000 remaining; only one may settle it. The other must see the first's rows."""
    invoice = _invoice(books)
    body = {
        "ledger_id": books["ledger"], "voucher_type": "receipt", "amount": 108000, "date": "2026-05-20T10:00:00", "mode": "bank",
        "invoice_allocations": [_allocation(invoice["id"], 108000, 10000, books["sections"]["prof"])],
    }
    responses = _pile_up_behind_a_lock(app_db, invoice["id"], [_post("/api/payments/", body), _post("/api/payments/", body)])
    assert sorted(response.status_code for response in responses) == [200, 400], [r.text[:200] for r in responses]
    assert any("remaining" in response.text for response in responses if response.status_code == 400)
    stored = _ok(books["client"].get(f"/api/invoices/{invoice['id']}"))
    assert (stored["paid_amount"], stored["tds_amount"], stored["remaining_amount"]) == (108000, 10000, 0)
    assert len(_ok(books["client"].get("/api/payments/"))) == 1


def test_two_receipt_edits_at_once_cannot_both_take_the_same_remaining_amount(books, app_db):
    """Each edit is fine on its own against the other's old rows; together they overspend the bill.

    Without the invoice lock both read the other receipt's old ₹50,000 and both pass.
    """
    invoice = _invoice(books)
    prof = books["sections"]["prof"]
    first = _ok(_receipt(books, invoice, cash=50000, tds=0))
    second = _ok(_receipt(books, invoice, cash=50000, tds=0))

    def edit(receipt):
        body = {
            "voucher_type": "receipt", "amount": 68000,
            "invoice_allocations": [_allocation(invoice["id"], 58000, 10000, prof)],
        }
        return lambda: TestClient(app).put(f"/api/payments/{receipt['id']}", json=body)

    responses = _pile_up_behind_a_lock(app_db, invoice["id"], [edit(first), edit(second)])
    assert sorted(response.status_code for response in responses) == [200, 400], [r.text[:200] for r in responses]
    stored = _ok(books["client"].get(f"/api/invoices/{invoice['id']}"))
    assert stored["remaining_amount"] >= 0
    assert stored["paid_amount"] + stored["tds_amount"] <= invoice["total_amount"]
