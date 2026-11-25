"""Undoing a document moves the serials its lines moved, whatever "Track serials" says now (#1068).

The serial rows linked to an invoice (``sales_invoice_id``) or stamped by a return
(its note) are the record of what the line did. Turning tracking off afterwards
must not strand those units: a restored sale sells them again, a cancelled return
sends them back out, and an edit that drops the product puts them back in stock.
"""

from test_serials import (
    _create_invoice,
    _create_ledger,
    _create_product,
    _product_put_payload,
    _serial_row,
    _stock_of,
    assert_serial_invariant,
)

from src.models.product_serial import STATUS_IN_STOCK, STATUS_SOLD, ProductSerial


def _set_tracking(client, product_id: int, on: bool, serials=None) -> None:
    response = client.put(
        f"/api/products/{product_id}",
        json=_product_put_payload(track_serials=on, serial_numbers=serials),
    )
    assert response.status_code == 200, response.text


def _sold_then_untracked(client, db_session, sku: str):
    """Receive A1 and A2, sell A1 while tracked, then turn tracking off."""
    supplier = _create_ledger(client, name=f"{sku} Supplier")
    customer = _create_ledger(client, name=f"{sku} Customer", gst="27ABCDE9999F1ZW")
    product = _create_product(client, db_session, sku=sku)
    _stock_of(client, supplier, product, ["A1", "A2"])
    sale = _create_invoice(client, customer, "sales", product, 1, ["A1"])
    assert _serial_row(db_session, "A1").status == STATUS_SOLD
    _set_tracking(client, product, False)
    return customer, product, sale


def test_cancel_and_restore_of_a_sale_after_tracking_is_off(client, db_session):
    _, product, sale = _sold_then_untracked(client, db_session, "SER-OFF-RESTORE")

    response = client.delete(f"/api/invoices/{sale['id']}")
    assert response.status_code == 200, response.text
    row = _serial_row(db_session, "A1")
    assert (row.status, row.sales_invoice_id) == (STATUS_IN_STOCK, sale["id"])

    response = client.post(f"/api/invoices/{sale['id']}/restore")
    assert response.status_code == 200, response.text
    row = _serial_row(db_session, "A1")
    assert (row.status, row.sales_invoice_id) == (STATUS_SOLD, sale["id"])

    # Tracking can be turned back on with nothing to reconcile.
    _set_tracking(client, product, True)
    assert assert_serial_invariant(db_session, product) == 1


def test_cancelling_a_return_after_tracking_is_off_sends_the_unit_out_again(client, db_session):
    customer, product, sale = _sold_then_untracked(client, db_session, "SER-OFF-RETURN")
    # The return is written while tracking is on, so put it back on for that step.
    _set_tracking(client, product, True)
    response = client.post("/api/credit-notes/", json={
        "ledger_id": customer,
        "invoice_ids": [sale["id"]],
        "credit_note_type": "return",
        "items": [{
            "invoice_id": sale["id"],
            "invoice_item_id": sale["items"][0]["id"],
            "quantity": 1,
            "serial_numbers": ["A1"],
        }],
    })
    assert response.status_code == 201, response.text
    note = response.json()
    assert _serial_row(db_session, "A1").status == STATUS_IN_STOCK
    _set_tracking(client, product, False)

    response = client.post(f"/api/credit-notes/{note['id']}/cancel")
    assert response.status_code == 200, response.text
    row = _serial_row(db_session, "A1")
    assert (row.status, row.sales_invoice_id) == (STATUS_SOLD, sale["id"])

    _set_tracking(client, product, True)
    assert assert_serial_invariant(db_session, product) == 1


def test_editing_a_product_off_a_sale_after_tracking_is_off_frees_its_unit(client, db_session):
    customer, product, sale = _sold_then_untracked(client, db_session, "SER-OFF-EDIT")
    other = _create_product(client, db_session, sku="SER-OFF-EDIT-2", track_serials=False, initial_quantity=5)

    response = client.put(f"/api/invoices/{sale['id']}", json={
        "ledger_id": customer,
        "voucher_type": "sales",
        "items": [{"product_id": other, "quantity": 1, "unit_price": 100}],
    })
    assert response.status_code == 200, response.text
    row = _serial_row(db_session, "A1")
    assert (row.status, row.sales_invoice_id) == (STATUS_IN_STOCK, None)

    _set_tracking(client, product, True)
    assert assert_serial_invariant(db_session, product) == 2


def test_editing_a_product_off_a_purchase_after_tracking_is_off_drops_its_units(client, db_session):
    supplier = _create_ledger(client, name="Edit Purchase Supplier")
    product = _create_product(client, db_session, sku="SER-OFF-PUR")
    other = _create_product(client, db_session, sku="SER-OFF-PUR-2", track_serials=False)
    purchase = _stock_of(client, supplier, product, ["P1", "P2"])
    _set_tracking(client, product, False)

    response = client.put(f"/api/invoices/{purchase['id']}", json={
        "ledger_id": supplier,
        "voucher_type": "purchase",
        "items": [{"product_id": other, "quantity": 1, "unit_price": 100}],
    })
    assert response.status_code == 200, response.text
    db_session.expire_all()
    assert db_session.query(ProductSerial).filter(ProductSerial.product_id == product).count() == 0

    _set_tracking(client, product, True)
    assert assert_serial_invariant(db_session, product) == 0


def test_editing_a_sale_after_tracking_is_off_keeps_the_unit_on_a_kept_line(client, db_session):
    """The line still sells the product, so the unit it went out with stays sold."""
    customer, product, sale = _sold_then_untracked(client, db_session, "SER-OFF-KEEP")

    response = client.put(f"/api/invoices/{sale['id']}", json={
        "ledger_id": customer,
        "voucher_type": "sales",
        "items": [{"product_id": product, "quantity": 1, "unit_price": 120}],
    })
    assert response.status_code == 200, response.text
    row = _serial_row(db_session, "A1")
    assert (row.status, row.sales_invoice_id) == (STATUS_SOLD, sale["id"])


# ---------------------------------------------------------------------------
# Tracking turned on after an untracked sale
# ---------------------------------------------------------------------------

def test_cancelling_an_untracked_sale_after_tracking_is_on_touches_no_serial(client, db_session):
    customer = _create_ledger(client, name="Late Customer", gst="27ABCDE9999F1ZW")
    product = _create_product(client, db_session, sku="SER-ON-LATE", track_serials=False, initial_quantity=3)
    sale = _create_invoice(client, customer, "sales", product, 1)
    _set_tracking(client, product, True, ["B1", "B2"])
    assert assert_serial_invariant(db_session, product) == 2

    response = client.delete(f"/api/invoices/{sale['id']}")
    assert response.status_code == 200, response.text
    for code in ("B1", "B2"):
        row = _serial_row(db_session, code)
        assert (row.status, row.sales_invoice_id) == (STATUS_IN_STOCK, None)
