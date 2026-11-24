"""Undoing an invoice moves only the stock its lines moved (#905).

A shop can start without stock counting and turn "Maintain inventory" on later.
An invoice saved while counting was off took nothing out of stock, so cancelling,
restoring, editing or returning against it must not put anything back. The other
way round, an invoice saved while counting was on gives its stock back even after
counting is turned off.
"""

from decimal import Decimal

import pytest
from challan_helpers import convert, create_challan, create_ledger, create_product, ok, seed_company
from sqlalchemy import text

from src.models.invoice import InvoiceItem


@pytest.fixture
def ledger(client):
    seed_company(client)
    return create_ledger(client)["id"]


def _stock(db_session, product_id: int) -> Decimal | None:
    db_session.expire_all()
    row = db_session.execute(
        text("SELECT quantity FROM inventory WHERE product_id = :p"), {"p": product_id}
    ).first()
    return None if row is None else Decimal(str(row[0]))


def _set_counting(client, product: dict, on: bool) -> None:
    body = {
        key: product[key]
        for key in ("sku", "name", "hsn_sac", "price", "gst_rate", "unit", "allow_decimal", "track_serials")
    }
    body["maintain_inventory"] = on
    ok(client.put(f"/api/products/{product['id']}", json=body))


def _adjust(client, product_id: int, quantity) -> None:
    ok(client.post("/api/inventory/adjust", json={"product_id": product_id, "quantity": quantity}))


def _invoice(client, ledger_id: int, lines, voucher_type: str = "sales") -> dict:
    return ok(client.post("/api/invoices/", json={
        "ledger_id": ledger_id,
        "voucher_type": voucher_type,
        "items": [{"product_id": p, "quantity": q, "unit_price": 100} for p, q in lines],
    }))


def _edit(client, invoice: dict, lines) -> dict:
    return ok(client.put(f"/api/invoices/{invoice['id']}", json={
        "ledger_id": invoice["ledger_id"],
        "voucher_type": invoice["voucher_type"],
        "invoice_date": invoice["invoice_date"][:10],
        "items": [{"product_id": p, "quantity": q, "unit_price": 100} for p, q in lines],
    }))


def _return(client, invoice: dict, quantity) -> dict:
    line = invoice["items"][0]
    return ok(client.post("/api/credit-notes/", json={
        "ledger_id": invoice["ledger_id"],
        "invoice_ids": [invoice["id"]],
        "credit_note_type": "return",
        "items": [{"invoice_id": invoice["id"], "invoice_item_id": line["id"], "quantity": quantity}],
    }), 201)


def _uncounted_then_counted(client, ledger_id, voucher_type="sales"):
    """Invoice 5 while counting is off, then turn counting on and count 10."""
    product = create_product(client, "LATE-1", maintain_inventory=False, initial_quantity=0)
    invoice = _invoice(client, ledger_id, [(product["id"], 5)], voucher_type)
    _set_counting(client, product, True)
    _adjust(client, product["id"], 10)
    return product, invoice


# ---------------------------------------------------------------------------
# Saved while counting was off, undone after it was turned on
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("voucher_type", ["sales", "purchase"])
def test_cancel_and_restore_of_an_invoice_saved_before_counting_moves_nothing(client, db_session, ledger, voucher_type):
    product, invoice = _uncounted_then_counted(client, ledger, voucher_type)
    assert _stock(db_session, product["id"]) == 10

    ok(client.delete(f"/api/invoices/{invoice['id']}"))
    assert _stock(db_session, product["id"]) == 10

    ok(client.post(f"/api/invoices/{invoice['id']}/restore"))
    assert _stock(db_session, product["id"]) == 10


def test_editing_an_invoice_saved_before_counting_moves_nothing(client, db_session, ledger):
    product, invoice = _uncounted_then_counted(client, ledger)

    edited = _edit(client, invoice, [(product["id"], 7)])
    assert _stock(db_session, product["id"]) == 10

    # The edited line still records that it took nothing out.
    ok(client.delete(f"/api/invoices/{edited['id']}"))
    assert _stock(db_session, product["id"]) == 10


def test_a_product_added_to_an_old_invoice_moves_stock_as_it_does_today(client, db_session, ledger):
    product, invoice = _uncounted_then_counted(client, ledger)
    counted = create_product(client, "NOW-1")
    assert _stock(db_session, counted["id"]) == 100

    _edit(client, invoice, [(product["id"], 5), (counted["id"], 3)])
    assert _stock(db_session, counted["id"]) == 97
    assert _stock(db_session, product["id"]) == 10

    ok(client.delete(f"/api/invoices/{invoice['id']}"))
    assert _stock(db_session, counted["id"]) == 100
    assert _stock(db_session, product["id"]) == 10


def test_a_return_against_an_invoice_saved_before_counting_moves_nothing(client, db_session, ledger):
    product, invoice = _uncounted_then_counted(client, ledger)

    note = _return(client, invoice, 2)
    assert _stock(db_session, product["id"]) == 10

    ok(client.post(f"/api/credit-notes/{note['id']}/cancel"))
    assert _stock(db_session, product["id"]) == 10


# ---------------------------------------------------------------------------
# Saved while counting was on, undone after it was turned off
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("voucher_type,after_save", [("sales", 95), ("purchase", 105)])
def test_cancel_and_restore_of_a_counted_invoice_after_counting_is_off(client, db_session, ledger, voucher_type, after_save):
    product = create_product(client, "EARLY-1")
    invoice = _invoice(client, ledger, [(product["id"], 5)], voucher_type)
    assert _stock(db_session, product["id"]) == after_save
    _set_counting(client, product, False)

    ok(client.delete(f"/api/invoices/{invoice['id']}"))
    assert _stock(db_session, product["id"]) == 100

    ok(client.post(f"/api/invoices/{invoice['id']}/restore"))
    assert _stock(db_session, product["id"]) == after_save


def test_editing_a_counted_invoice_after_counting_is_off(client, db_session, ledger):
    product = create_product(client, "EARLY-2")
    invoice = _invoice(client, ledger, [(product["id"], 5)])
    _set_counting(client, product, False)

    edited = _edit(client, invoice, [(product["id"], 7)])
    assert _stock(db_session, product["id"]) == 93

    ok(client.delete(f"/api/invoices/{edited['id']}"))
    assert _stock(db_session, product["id"]) == 100


def test_a_return_against_a_counted_invoice_after_counting_is_off(client, db_session, ledger):
    product = create_product(client, "EARLY-3")
    invoice = _invoice(client, ledger, [(product["id"], 5)])
    _set_counting(client, product, False)

    note = _return(client, invoice, 2)
    assert _stock(db_session, product["id"]) == 97

    ok(client.post(f"/api/credit-notes/{note['id']}/cancel"))
    assert _stock(db_session, product["id"]) == 95


# ---------------------------------------------------------------------------
# Unchanged behaviour
# ---------------------------------------------------------------------------

def test_a_counted_invoice_still_gives_its_stock_back(client, db_session, ledger):
    product = create_product(client, "ALWAYS-1")
    invoice = _invoice(client, ledger, [(product["id"], 5)])
    assert _stock(db_session, product["id"]) == 95

    ok(client.delete(f"/api/invoices/{invoice['id']}"))
    assert _stock(db_session, product["id"]) == 100
    ok(client.post(f"/api/invoices/{invoice['id']}/restore"))
    assert _stock(db_session, product["id"]) == 95


def test_a_line_with_no_record_follows_the_current_setting(client, db_session, ledger):
    """Rows written before the column existed and missed by the backfill."""
    product = create_product(client, "LEGACY-1")
    invoice = _invoice(client, ledger, [(product["id"], 5)])
    db_session.query(InvoiceItem).filter(InvoiceItem.invoice_id == invoice["id"]).update({"stock_applied": None})
    db_session.commit()

    ok(client.delete(f"/api/invoices/{invoice['id']}"))
    assert _stock(db_session, product["id"]) == 100


def test_new_lines_record_whether_they_moved_stock(client, db_session, ledger):
    counted = create_product(client, "REC-1")
    uncounted = create_product(client, "REC-2", maintain_inventory=False, initial_quantity=0)
    invoice = _invoice(client, ledger, [(counted["id"], 1), (uncounted["id"], 1)])

    db_session.expire_all()
    recorded = {
        item.product_id: item.stock_applied
        for item in db_session.query(InvoiceItem).filter(InvoiceItem.invoice_id == invoice["id"])
    }
    assert recorded == {counted["id"]: True, uncounted["id"]: False}


# ---------------------------------------------------------------------------
# Invoices made from a delivery challan
# ---------------------------------------------------------------------------

def test_challan_invoice_saved_before_counting(client, db_session, ledger):
    """The re-opened challan follows the invoice, so the two still cancel out."""
    product = create_product(client, "DC-1", maintain_inventory=False, initial_quantity=0)
    challan = create_challan(client, ledger, [(product["id"], 5)])
    invoice = ok(convert(client, challan["id"]))
    _set_counting(client, product, True)
    _adjust(client, product["id"], 10)

    ok(client.delete(f"/api/invoices/{invoice['id']}"))
    assert _stock(db_session, product["id"]) == 10
    ok(client.post(f"/api/invoices/{invoice['id']}/restore"))
    assert _stock(db_session, product["id"]) == 10


def test_challan_invoice_saved_while_counting(client, db_session, ledger):
    product = create_product(client, "DC-2")
    challan = create_challan(client, ledger, [(product["id"], 5)])
    invoice = ok(convert(client, challan["id"]))
    assert _stock(db_session, product["id"]) == 95
    _set_counting(client, product, False)

    # The invoice's 5 come back and the re-opened challan holds them again.
    ok(client.delete(f"/api/invoices/{invoice['id']}"))
    assert _stock(db_session, product["id"]) == 95
    ok(client.post(f"/api/invoices/{invoice['id']}/restore"))
    assert _stock(db_session, product["id"]) == 95
