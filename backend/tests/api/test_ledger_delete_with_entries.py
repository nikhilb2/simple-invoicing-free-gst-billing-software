"""Deleting a ledger that has entries (#1050).

The ledger is soft-deleted and everything live on it is cancelled the way the cancel
buttons do it, in one transaction: all of it, or nothing and a message naming the
document that refused.
"""

import json
from datetime import timedelta
from types import SimpleNamespace

import pytest
from challan_helpers import convert as convert_challan
from challan_helpers import create_challan, stock
from quotation_helpers import GST_KA, convert as convert_quotation
from quotation_helpers import create_product, create_quotation, ok, seed_company
from test_financial_years import as_role
from test_tenant_isolation import (  # noqa: F401 -- fixtures
    _create_company,
    _create_ledger,
    _user,
    act_as,
    shared_hosting,
)

from src.core.config import settings
from src.models.buyer import Buyer
from src.models.product import Product
from src.models.product_serial import STATUS_IN_STOCK, STATUS_SOLD, ProductSerial
from src.models.share_link import ShareLink
from src.models.user import UserRole
from src.services.gst_tax_service import india_today


@pytest.fixture(autouse=True)
def _share_links_on(monkeypatch):
    monkeypatch.setattr(settings, "SHARE_LINKS_ENABLED", True)


def _ledger(client, name: str, gst: str | None = None, opening_balance=None) -> int:
    body = {"name": name, "address": "2 Buyer Street", "phone_number": "9000000000"}
    if gst:
        body["gst"] = gst
    if opening_balance is not None:
        body["opening_balance"] = opening_balance
    return ok(client.post("/api/ledgers/", json=body))["id"]


def _invoice(client, ledger_id: int, product_id: int, quantity, *, voucher_type="sales", serials=None, **extra) -> dict:
    item = {"product_id": product_id, "quantity": quantity, "unit_price": 100}
    if serials is not None:
        item["serial_numbers"] = serials
    body = {"ledger_id": ledger_id, "voucher_type": voucher_type, "items": [item], **extra}
    if voucher_type == "purchase":
        body.setdefault("supplier_invoice_number", f"SUP-{product_id}-{quantity}")
    return ok(client.post("/api/invoices/", json=body))


def _receipt(client, ledger_id: int, amount, allocations=(), voucher_type="receipt") -> dict:
    return ok(client.post("/api/payments/", json={
        "ledger_id": ledger_id,
        "voucher_type": voucher_type,
        "amount": amount,
        "mode": "cash",
        "invoice_allocations": list(allocations),
    }))


def _serial_product(client, db_session, sku: str) -> int:
    product_id = create_product(client, sku, initial_quantity=0)["id"]
    db_session.query(Product).filter(Product.id == product_id).update({"track_serials": True})
    db_session.commit()
    return product_id


def _serial_status(db_session, number: str) -> str:
    db_session.expire_all()
    return db_session.query(ProductSerial).filter(ProductSerial.serial_number == number).one().status


def _listed(client, **params) -> set[int]:
    return {row["id"] for row in ok(client.get("/api/ledgers/", params={"page_size": 500, **params}))["items"]}


def _delete(client, ledger_id: int):
    return client.post(f"/api/ledgers/{ledger_id}/delete-with-entries")


@pytest.fixture
def books(client, db_session):
    """A customer with a bit of everything on it, and the stock it moved."""
    seed_company(client)
    widget = create_product(client, "WID-1")["id"]
    phone = _serial_product(client, db_session, "PHONE-1")
    supplier = _ledger(client, "Phone Supplier")
    _invoice(client, supplier, phone, 2, voucher_type="purchase", serials=["SN-0001", "SN-0002"])
    customer = _ledger(client, "Party To Delete", GST_KA, opening_balance=500)
    widget_before = stock(client, widget)

    paid = _invoice(client, customer, widget, 5)
    returned = _invoice(client, customer, widget, 3)
    serial_sale = _invoice(client, customer, phone, 1, serials=["SN-0001"])
    receipt = _receipt(client, customer, 200, [{"invoice_id": paid["id"], "allocated_amount": 200}])
    payment_out = _receipt(client, customer, 50, voucher_type="payment")
    note = ok(client.post("/api/credit-notes/", json={
        "ledger_id": customer,
        "invoice_ids": [returned["id"]],
        "credit_note_type": "return",
        "direction": "outward",
        "items": [{"invoice_id": returned["id"], "invoice_item_id": returned["items"][0]["id"], "quantity": 1}],
    }), 201)
    open_quote = create_quotation(client, customer, widget)
    converted_quote = create_quotation(client, customer, widget)
    quote_invoice = ok(convert_quotation(client, converted_quote["id"]))
    open_challan = create_challan(client, customer, [(widget, 4)])
    converted_challan = create_challan(client, customer, [(widget, 2)])
    challan_invoice = ok(convert_challan(client, converted_challan["id"]))
    today = india_today().isoformat()
    statement_link = ok(client.post("/api/share/", json={
        "resource_type": "ledger_statement", "resource_id": customer, "from_date": today, "to_date": today,
    }))
    invoice_link = ok(client.post("/api/share/", json={"resource_type": "invoice", "resource_id": paid["id"]}))

    return SimpleNamespace(
        customer=customer, supplier=supplier, widget=widget, phone=phone, widget_before=widget_before,
        invoices=[paid, returned, serial_sale, quote_invoice, challan_invoice],
        payments=[receipt, payment_out], note=note,
        quotations=[open_quote, converted_quote], challans=[open_challan, converted_challan],
        links=[statement_link, invoice_link],
    )


def test_preview_counts_what_the_delete_cancels(client, books):
    preview = ok(client.get(f"/api/ledgers/{books.customer}/delete-preview"))

    assert preview["ledger_name"] == "Party To Delete"
    assert preview["has_entries"] is True
    assert preview["to_cancel"] == {
        "sales_invoices": 5,
        "purchase_invoices": 0,
        "receipts": 1,
        "payments": 1,
        "opening_balance": True,
        "credit_notes": 1,
        # The open one, and the converted one its invoice's cancel reopens.
        "delivery_challans": 2,
        "quotations": 2,
        "share_links": 2,
    }
    # Every invoice is dated today.
    assert preview["has_invoices_from_earlier_months"] is False


def test_delete_cancels_everything_and_puts_stock_and_serials_back(client, db_session, books):
    response = _delete(client, books.customer)
    assert response.status_code == 200, response.text
    assert response.json()["cancelled"] == {
        "sales_invoices": 5, "purchase_invoices": 0, "receipts": 1, "payments": 1, "opening_balance": True,
        "credit_notes": 1, "delivery_challans": 2, "quotations": 2, "share_links": 2,
    }

    for invoice in books.invoices:
        body = ok(client.get(f"/api/invoices/{invoice['id']}"))
        assert body["status"] == "cancelled"
        # The cancelled document keeps the party's name, and its PDF still renders.
        assert body["ledger_name"] == "Party To Delete"
        assert client.get(f"/api/invoices/{invoice['id']}/pdf").status_code == 200
    payments = ok(client.get("/api/payments/", params={"ledger_id": books.customer, "include_cancelled": True}))
    assert {p["status"] for p in payments} == {"cancelled"}
    assert {p["voucher_type"] for p in payments} == {"receipt", "payment", "opening_balance"}
    assert ok(client.get(f"/api/credit-notes/{books.note['id']}"))["status"] == "cancelled"
    for quotation in books.quotations:
        assert ok(client.get(f"/api/quotations/{quotation['id']}"))["status"] == "cancelled"
    for challan in books.challans:
        assert ok(client.get(f"/api/delivery-challans/{challan['id']}"))["status"] == "cancelled"

    assert stock(client, books.widget) == books.widget_before
    assert _serial_status(db_session, "SN-0001") == STATUS_IN_STOCK
    db_session.expire_all()
    assert all(link.revoked_at is not None for link in db_session.query(ShareLink).all())
    ledger = db_session.get(Buyer, books.customer)
    assert ledger.deleted_at is not None
    assert ledger.deleted_by == 1


def test_a_deleted_ledger_is_hidden_from_lists_search_and_pickers(client, books):
    assert ok(_delete(client, books.customer))

    assert books.customer not in _listed(client)
    assert books.customer not in _listed(client, search="Party To Delete")
    assert books.customer not in _listed(client, search=GST_KA)
    assert client.get(f"/api/ledgers/{books.customer}").status_code == 404
    assert client.get(f"/api/ledgers/{books.customer}/statement").status_code == 404
    assert client.get(f"/api/ledgers/{books.customer}/unpaid-invoices").status_code == 404
    assert client.get(f"/api/ledgers/{books.customer}/delete-preview").status_code == 404
    assert _delete(client, books.customer).status_code == 404
    # No new documents can be written to it.
    response = client.post("/api/invoices/", json={
        "ledger_id": books.customer, "voucher_type": "sales",
        "items": [{"product_id": books.widget, "quantity": 1, "unit_price": 100}],
    })
    assert response.status_code == 404, response.text
    assert client.post("/api/payments/", json={
        "ledger_id": books.customer, "voucher_type": "receipt", "amount": 10, "mode": "cash",
    }).status_code == 404
    assert client.post("/api/quotations/", json={
        "ledger_id": books.customer, "items": [{"product_id": books.widget, "quantity": 1, "unit_price": 100}],
    }).status_code == 404
    # And nothing is due from it.
    dues = ok(client.get("/api/invoices/dues", params={"page_size": 100}))
    assert not [row for row in dues["items"] if row["ledger_id"] == books.customer]
    # Its cancelled invoices stay cancelled.
    response = client.post(f"/api/invoices/{books.invoices[0]['id']}/restore")
    assert response.status_code == 400
    assert "ledger was deleted" in response.text


def test_a_refused_step_rolls_everything_back_and_names_the_document(client, db_session):
    seed_company(client)
    widget = create_product(client, "WID-1")["id"]
    phone = _serial_product(client, db_session, "PHONE-1")
    supplier = _ledger(client, "Supplier And Buyer")
    other = _ledger(client, "Someone Else")
    purchase = _invoice(client, supplier, phone, 2, voucher_type="purchase", serials=["SN-0001", "SN-0002"])
    _invoice(client, other, phone, 1, serials=["SN-0002"])
    # Cancelled before the purchase is reached, then put back by the rollback.
    sale = _invoice(client, supplier, widget, 2)
    receipt = _receipt(client, supplier, 100, [{"invoice_id": sale["id"], "allocated_amount": 100}])
    quotation = create_quotation(client, supplier, widget)
    widget_before = stock(client, widget)

    response = _delete(client, supplier)

    assert response.status_code == 409, response.text
    detail = response.json()["detail"]
    assert detail["code"] == "ledger_delete_blocked"
    assert detail["document_type"] == "invoice"
    assert detail["document_id"] == purchase["id"]
    assert f"Purchase invoice {purchase['invoice_number']} cannot be cancelled" in detail["message"]
    assert "SN-0002" in detail["message"]
    assert detail["message"].endswith("Nothing was changed.")

    assert ok(client.get(f"/api/invoices/{sale['id']}"))["status"] == "active"
    assert ok(client.get(f"/api/invoices/{purchase['id']}"))["status"] == "active"
    assert ok(client.get(f"/api/payments/{receipt['id']}"))["status"] == "active"
    assert ok(client.get(f"/api/quotations/{quotation['id']}"))["status"] == "open"
    assert stock(client, widget) == widget_before
    assert _serial_status(db_session, "SN-0001") == STATUS_IN_STOCK
    assert _serial_status(db_session, "SN-0002") == STATUS_SOLD
    assert supplier in _listed(client)
    db_session.expire_all()
    assert db_session.get(Buyer, supplier).deleted_at is None


def test_a_manager_cannot_delete_a_ledger_with_entries(client, books):
    with as_role(UserRole.manager):
        # The dialog can still show what it would take.
        assert client.get(f"/api/ledgers/{books.customer}/delete-preview").status_code == 200
        response = _delete(client, books.customer)
    assert response.status_code == 403, response.text
    assert books.customer in _listed(client)


def test_another_companys_ledger_is_not_found(client, db_session, shared_hosting, act_as):  # noqa: F811
    owner = _user(db_session, "bob@beta.example")
    intruder = _user(db_session, "alice@alpha.example", role=UserRole.admin)
    act_as(owner)
    _create_company(client, "Beta Stores")
    theirs = _create_ledger(client, "Beta Customer")
    act_as(intruder)
    _create_company(client, "Alpha Traders")

    assert client.get(f"/api/ledgers/{theirs}/delete-preview").status_code == 404
    assert _delete(client, theirs).status_code == 404
    db_session.expire_all()
    assert db_session.get(Buyer, theirs).deleted_at is None


def test_a_ledger_with_no_entries_is_still_deleted_outright(client, db_session):
    seed_company(client)
    ledger = _ledger(client, "Never Used")
    preview = ok(client.get(f"/api/ledgers/{ledger}/delete-preview"))
    assert preview["has_entries"] is False
    assert not any(preview["to_cancel"].values())

    ok(client.delete(f"/api/ledgers/{ledger}"))
    assert db_session.get(Buyer, ledger) is None


def test_a_ledger_whose_entries_are_all_cancelled_can_now_be_deleted(client):
    seed_company(client)
    widget = create_product(client, "WID-1")["id"]
    ledger = _ledger(client, "Old Customer")
    invoice = _invoice(client, ledger, widget, 1)
    ok(client.delete(f"/api/invoices/{invoice['id']}"))
    # The plain delete still refuses: the cancelled invoice points at the ledger.
    assert client.delete(f"/api/ledgers/{ledger}").status_code == 400

    preview = ok(client.get(f"/api/ledgers/{ledger}/delete-preview"))
    assert preview["has_entries"] is True
    assert not any(preview["to_cancel"].values())
    assert not any(ok(_delete(client, ledger))["cancelled"].values())
    assert ledger not in _listed(client)


def test_a_new_ledger_can_take_the_deleted_ones_name_and_gstin(client):
    seed_company(client)
    widget = create_product(client, "WID-1")["id"]
    old = _ledger(client, "Same Party", GST_KA)
    _invoice(client, old, widget, 1)
    ok(_delete(client, old))

    new = _ledger(client, "Same Party", GST_KA)

    assert new != old
    assert _listed(client, search="Same Party") == {new}
    # Editing it keeps its GSTIN: the deleted ledger does not count as a duplicate.
    body = ok(client.get(f"/api/ledgers/{new}"))
    body["address"] = "New address"
    ok(client.put(f"/api/ledgers/{new}", json=body))


def test_reports_show_the_cancelled_invoices_like_any_cancelled_invoice(client):
    """GSTR-1, the day book and the tax ledger treat a deleted ledger's invoice
    exactly like one cancelled from the invoice page."""
    seed_company(client)
    widget = create_product(client, "WID-1", hsn_sac="8471")["id"]
    last_month = india_today().replace(day=1) - timedelta(days=1)
    period = {"from_date": last_month.replace(day=1).isoformat(), "to_date": last_month.isoformat()}
    dated = last_month.replace(day=5).isoformat()
    kept = _ledger(client, "Kept Customer")
    gone = _ledger(client, "Deleted Customer")
    by_hand = _invoice(client, kept, widget, 1, invoice_date=dated)
    by_delete = _invoice(client, gone, widget, 1, invoice_date=dated)
    live = _invoice(client, kept, widget, 1, invoice_date=dated)
    assert ok(client.get(f"/api/ledgers/{gone}/delete-preview"))["has_invoices_from_earlier_months"] is True

    ok(client.delete(f"/api/invoices/{by_hand['id']}"))
    ok(_delete(client, gone))

    numbers = (by_hand["invoice_number"], by_delete["invoice_number"])
    day_book = {e["reference_number"] for e in ok(client.get("/api/ledgers/day-book", params=period))["entries"]}
    assert (numbers[0] in day_book) == (numbers[1] in day_book)
    assert live["invoice_number"] in day_book

    tax_ledger = {e["reference_number"] for e in ok(client.get("/api/ledgers/tax-ledger/", params=period))["entries"]}
    assert (numbers[0] in tax_ledger) == (numbers[1] in tax_ledger)
    assert live["invoice_number"] in tax_ledger

    export = client.get("/api/ledgers/tax-ledger/gstr1/export-json", params=period)
    assert export.status_code == 200, export.text
    [invoices_row] = [row for row in json.loads(export.content)["doc_issue"]["doc_det"] if row["doc_num"] == 1]
    assert sum(doc["totnum"] for doc in invoices_row["docs"]) == 3
    assert sum(doc["cancel"] for doc in invoices_row["docs"]) == 2
    summary = ok(client.get("/api/ledgers/tax-ledger/gstr1/summary", params=period))
    # Only the live invoice is reported as a supply.
    assert summary["b2cs"]["taxable_value"] == pytest.approx(100.0)
