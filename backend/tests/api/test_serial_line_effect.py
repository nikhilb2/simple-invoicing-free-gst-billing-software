"""Undoing a document moves the serials its lines moved, whatever "Track serials" says now (#1068).

The serial rows linked to an invoice (``sales_invoice_id``) or stamped by a return
(its note) are the record of what the line did. Turning tracking off afterwards
must not strand those units: a restored sale sells them again, a cancelled return
sends them back out, and an edit that drops the product puts them back in stock.
"""

from datetime import date

import pytest

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


# The line was saved with no serials, so it has none to move back. Each line
# records whether it carried serials (invoice_items.serials_applied); a line that
# did not is undone with no serial numbers, as long as the units it takes off the
# shelf are ones no serial covers. Otherwise in-stock serials would outnumber the
# shelf (#925), so the refusal says how to do it: turn tracking off, do it, and
# turn tracking back on, naming the units still on the shelf (#918).

TURN_OFF = "Turn off serial tracking for"


def _untracked_sale(client, db_session, sku: str, *, stock: int, sold: int):
    customer = _create_ledger(client, name=f"{sku} Customer", gst="27ABCDE9999F1ZW")
    product = _create_product(client, db_session, sku=sku, track_serials=False, initial_quantity=stock)
    sale = _create_invoice(client, customer, "sales", product, sold)
    return customer, product, sale


def _line_record(db_session, invoice_id: int, product_id: int):
    from src.models.invoice import InvoiceItem

    db_session.expire_all()
    return {
        item.serials_applied
        for item in db_session.query(InvoiceItem).filter(
            InvoiceItem.invoice_id == invoice_id, InvoiceItem.product_id == product_id
        )
    }


def test_a_line_records_whether_it_carried_serials(client, db_session):
    supplier = _create_ledger(client, name="Record Supplier")
    tracked = _create_product(client, db_session, sku="SER-REC-T")
    purchase = _stock_of(client, supplier, tracked, ["R1"])
    assert _line_record(db_session, purchase["id"], tracked) == {True}

    _, untracked, sale = _untracked_sale(client, db_session, "SER-REC-U", stock=2, sold=1)
    assert _line_record(db_session, sale["id"], untracked) == {False}


def test_the_invoice_returns_whether_each_line_carried_serials(client, db_session):
    """The invoice form needs it to know which lines take no serials on an edit (#1104)."""
    from src.models.invoice import InvoiceItem

    supplier = _create_ledger(client, name="Out Supplier")
    tracked = _create_product(client, db_session, sku="SER-OUT-T")
    purchase = _stock_of(client, supplier, tracked, ["O1"])
    assert [line["serials_applied"] for line in purchase["items"]] == [True]

    customer, untracked, sale = _untracked_sale(client, db_session, "SER-OUT-U", stock=2, sold=1)
    assert [line["serials_applied"] for line in sale["items"]] == [False]
    # Turning tracking on later does not change what the line recorded.
    _set_tracking(client, untracked, True, ["U1"])
    fetched = client.get(f"/api/invoices/{sale['id']}")
    assert fetched.status_code == 200, fetched.text
    assert [line["serials_applied"] for line in fetched.json()["items"]] == [False]

    # A line saved before the record existed has none.
    db_session.query(InvoiceItem).filter(InvoiceItem.invoice_id == sale["id"]).update(
        {InvoiceItem.serials_applied: None}
    )
    db_session.commit()
    fetched = client.get(f"/api/invoices/{sale['id']}")
    assert [line["serials_applied"] for line in fetched.json()["items"]] == [None]


def test_restoring_an_untracked_sale_after_tracking_is_on_is_refused_with_the_way_out(client, db_session):
    """The issue's case: the refusal must not claim the units went out on another invoice."""
    _, product, sale = _untracked_sale(client, db_session, "SER-ON-RESTORE", stock=3, sold=2)
    assert client.delete(f"/api/invoices/{sale['id']}").status_code == 200
    _set_tracking(client, product, True, ["B1", "B2", "B3"])
    assert assert_serial_invariant(db_session, product) == 3

    response = client.post(f"/api/invoices/{sale['id']}/restore")
    assert response.status_code == 400, response.text
    detail = response.json()["detail"]
    assert "another invoice" not in detail
    assert "before serial tracking was turned on" in detail
    assert TURN_OFF in detail
    assert assert_serial_invariant(db_session, product) == 3

    # The way out the message names works.
    _set_tracking(client, product, False)
    response = client.post(f"/api/invoices/{sale['id']}/restore")
    assert response.status_code == 200, response.text
    _set_tracking(client, product, True, ["B1"])
    assert assert_serial_invariant(db_session, product) == 1


def test_restoring_an_untracked_sale_takes_back_units_no_serial_covers(client, db_session):
    """Cancelled after tracking went on, its units came back with no serial; restore takes them again."""
    _, product, sale = _untracked_sale(client, db_session, "SER-ON-ROUND", stock=3, sold=1)
    _set_tracking(client, product, True, ["C1", "C2"])
    assert client.delete(f"/api/invoices/{sale['id']}").status_code == 200

    response = client.post(f"/api/invoices/{sale['id']}/restore")
    assert response.status_code == 200, response.text
    assert assert_serial_invariant(db_session, product) == 2
    for code in ("C1", "C2"):
        assert _serial_row(db_session, code).status == STATUS_IN_STOCK


def _return(client, customer, sale, quantity, serials=None):
    item = {
        "invoice_id": sale["id"],
        "invoice_item_id": sale["items"][0]["id"],
        "quantity": quantity,
    }
    if serials is not None:
        item["serial_numbers"] = serials
    return client.post("/api/credit-notes/", json={
        "ledger_id": customer,
        "invoice_ids": [sale["id"]],
        "credit_note_type": "return",
        "items": [item],
    })


def test_an_untracked_sale_can_be_returned_and_the_return_cancelled_after_tracking_is_on(client, db_session):
    customer, product, sale = _untracked_sale(client, db_session, "SER-ON-RET", stock=3, sold=2)
    _set_tracking(client, product, True, ["D1"])

    response = _return(client, customer, sale, 1)
    assert response.status_code == 201, response.text
    note = response.json()
    assert _serial_row(db_session, "D1").status == STATUS_IN_STOCK

    response = client.post(f"/api/credit-notes/{note['id']}/cancel")
    assert response.status_code == 200, response.text
    assert assert_serial_invariant(db_session, product) == 1


def test_an_untracked_return_cannot_take_serial_numbers(client, db_session):
    customer, product, sale = _untracked_sale(client, db_session, "SER-ON-RET-CODES", stock=3, sold=2)
    _set_tracking(client, product, True, ["E1"])

    response = _return(client, customer, sale, 1, ["E1"])
    assert response.status_code == 400, response.text
    assert "before serial tracking was turned on" in response.json()["detail"]
    assert _serial_row(db_session, "E1").status == STATUS_IN_STOCK


def test_cancelling_an_untracked_return_after_tracking_is_on_is_refused_with_the_way_out(client, db_session):
    customer, product, sale = _untracked_sale(client, db_session, "SER-ON-RET-CANCEL", stock=3, sold=2)
    response = _return(client, customer, sale, 1)
    assert response.status_code == 201, response.text
    note = response.json()
    _set_tracking(client, product, True, ["F1", "F2"])

    response = client.post(f"/api/credit-notes/{note['id']}/cancel")
    assert response.status_code == 400, response.text
    detail = response.json()["detail"]
    assert "another invoice" not in detail
    assert TURN_OFF in detail
    assert assert_serial_invariant(db_session, product) == 2


def test_editing_an_untracked_sale_after_tracking_is_on_needs_no_serials(client, db_session):
    customer, product, sale = _untracked_sale(client, db_session, "SER-ON-EDIT", stock=5, sold=2)
    _set_tracking(client, product, True, ["G1", "G2", "G3"])

    response = client.put(f"/api/invoices/{sale['id']}", json={
        "ledger_id": customer,
        "voucher_type": "sales",
        "items": [{"product_id": product, "quantity": 2, "unit_price": 150}],
    })
    assert response.status_code == 200, response.text
    assert response.json()["items"][0]["unit_price"] == 150
    assert _line_record(db_session, sale["id"], product) == {False}
    assert assert_serial_invariant(db_session, product) == 3


def test_editing_an_untracked_sale_refuses_serials_and_more_units(client, db_session):
    customer, product, sale = _untracked_sale(client, db_session, "SER-ON-EDIT-MORE", stock=5, sold=2)
    _set_tracking(client, product, True, ["H1", "H2", "H3"])

    response = client.put(
        f"/api/invoices/{sale['id']}",
        json=_invoice_payload_for(customer, product, 2, ["H1", "H2"]),
    )
    assert response.status_code == 400, response.text
    assert "before serial tracking was turned on" in response.json()["detail"]

    response = client.put(f"/api/invoices/{sale['id']}", json=_invoice_payload_for(customer, product, 3))
    assert response.status_code == 400, response.text
    assert TURN_OFF in response.json()["detail"]

    for code in ("H1", "H2", "H3"):
        assert _serial_row(db_session, code).status == STATUS_IN_STOCK
    assert assert_serial_invariant(db_session, product) == 3


def _invoice_payload_for(ledger, product, quantity, serials=None, voucher_type="sales"):
    item = {"product_id": product, "quantity": quantity, "unit_price": 100}
    if serials is not None:
        item["serial_numbers"] = serials
    return {"ledger_id": ledger, "voucher_type": voucher_type, "items": [item]}


def test_cancelling_an_untracked_purchase_after_tracking_is_on_is_refused(client, db_session):
    """Its units have no serial, so taking them off the shelf would strand the serials of others."""
    supplier = _create_ledger(client, name="Late Purchase Supplier")
    product = _create_product(client, db_session, sku="SER-ON-PUR", track_serials=False)
    purchase = _create_invoice(client, supplier, "purchase", product, 2)
    _set_tracking(client, product, True, ["K1", "K2"])

    response = client.delete(f"/api/invoices/{purchase['id']}")
    assert response.status_code == 400, response.text
    assert TURN_OFF in response.json()["detail"]
    assert assert_serial_invariant(db_session, product) == 2


def test_returning_an_untracked_purchase_after_tracking_is_on_is_refused(client, db_session):
    supplier = _create_ledger(client, name="Late Return Supplier")
    product = _create_product(client, db_session, sku="SER-ON-PUR-RET", track_serials=False)
    purchase = _create_invoice(client, supplier, "purchase", product, 2)
    _set_tracking(client, product, True, ["M1", "M2"])

    response = client.post("/api/credit-notes/", json={
        "ledger_id": supplier,
        "invoice_ids": [purchase["id"]],
        "credit_note_type": "return",
        "direction": "inward",
        "supplier_credit_note_number": "SUP-CN-1",
        "supplier_credit_note_date": date.today().isoformat(),
        "items": [{
            "invoice_id": purchase["id"],
            "invoice_item_id": purchase["items"][0]["id"],
            "quantity": 1,
        }],
    })
    assert response.status_code == 400, response.text
    assert TURN_OFF in response.json()["detail"]
    assert assert_serial_invariant(db_session, product) == 2


# ---------------------------------------------------------------------------
# Several lines of one product on one note (review of #1105)
# ---------------------------------------------------------------------------
# Production sessions run with autoflush=False (src/db/session.py), so the spare
# units check must flush the stock moved by the note's earlier lines before it
# reads the shelf. The test sessions autoflush by default, which hid this.

@pytest.fixture
def no_autoflush(client, db_session):
    """Serve requests from sessions configured like production's SessionLocal."""
    from sqlalchemy.orm import sessionmaker

    from src.db.session import get_db

    factory = sessionmaker(bind=db_session.get_bind(), autoflush=False)

    def override_get_db():
        db = factory()
        try:
            yield db
        finally:
            db.close()

    overrides = client.app.dependency_overrides
    previous = overrides[get_db]
    overrides[get_db] = override_get_db
    yield
    overrides[get_db] = previous


def _two_line_invoice(client, ledger, voucher_type, product, quantity):
    line = {"product_id": product, "quantity": quantity, "unit_price": 100}
    response = client.post("/api/invoices/", json={
        "ledger_id": ledger,
        "voucher_type": voucher_type,
        "tax_inclusive": False,
        "apply_round_off": False,
        "items": [dict(line), dict(line)],
    })
    assert response.status_code == 200, response.text
    return response.json()


def test_a_supplier_return_of_two_untracked_lines_counts_both(client, db_session, no_autoflush):
    supplier = _create_ledger(client, name="Two Line Supplier")
    customer = _create_ledger(client, name="Two Line Customer", gst="27ABCDE9999F1ZW")
    product = _create_product(client, db_session, sku="SER-ON-TWO-PUR", track_serials=False)
    purchase = _two_line_invoice(client, supplier, "purchase", product, 2)
    sale = _create_invoice(client, customer, "sales", product, 2)
    _set_tracking(client, product, True, ["N1", "N2"])
    # The sale's 2 units come back with no serial: shelf 4, 2 in-stock serials.
    assert client.delete(f"/api/invoices/{sale['id']}").status_code == 200

    response = client.post("/api/credit-notes/", json={
        "ledger_id": supplier,
        "invoice_ids": [purchase["id"]],
        "credit_note_type": "return",
        "direction": "inward",
        "supplier_credit_note_number": "SUP-CN-2",
        "supplier_credit_note_date": date.today().isoformat(),
        "items": [
            {"invoice_id": purchase["id"], "invoice_item_id": item["id"], "quantity": 2}
            for item in purchase["items"]
        ],
    })
    assert response.status_code == 400, response.text
    assert TURN_OFF in response.json()["detail"]
    for code in ("N1", "N2"):
        assert _serial_row(db_session, code).status == STATUS_IN_STOCK


def test_cancelling_a_return_of_two_untracked_lines_counts_both(client, db_session, no_autoflush):
    customer = _create_ledger(client, name="Two Line Return Customer", gst="27ABCDE9999F1ZW")
    product = _create_product(client, db_session, sku="SER-ON-TWO-RET", track_serials=False, initial_quantity=4)
    sale = _two_line_invoice(client, customer, "sales", product, 1)
    response = client.post("/api/credit-notes/", json={
        "ledger_id": customer,
        "invoice_ids": [sale["id"]],
        "credit_note_type": "return",
        "items": [
            {"invoice_id": sale["id"], "invoice_item_id": item["id"], "quantity": 1}
            for item in sale["items"]
        ],
    })
    assert response.status_code == 201, response.text
    note = response.json()
    later = _create_invoice(client, customer, "sales", product, 1)
    _set_tracking(client, product, True, ["Q1", "Q2", "Q3"])
    # The later sale's unit comes back with no serial: shelf 4, 3 in-stock serials.
    assert client.delete(f"/api/invoices/{later['id']}").status_code == 200

    response = client.post(f"/api/credit-notes/{note['id']}/cancel")
    assert response.status_code == 400, response.text
    assert TURN_OFF in response.json()["detail"]
    for code in ("Q1", "Q2", "Q3"):
        assert _serial_row(db_session, code).status == STATUS_IN_STOCK
