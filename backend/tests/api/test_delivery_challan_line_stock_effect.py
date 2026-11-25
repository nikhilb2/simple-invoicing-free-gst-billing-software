"""Releasing a delivery challan puts back only the stock its lines took (#1067).

#905 did this for invoices. A challan saved while "Maintain inventory" was off took
nothing out, so cancelling, editing or invoicing it after the setting was turned on
must not put anything back. The other way round, a challan saved while counting was
on gives its goods back even after counting is turned off.
"""

from decimal import Decimal

import pytest
from challan_helpers import convert, create_challan, create_ledger, create_product, ok, seed_company, update_challan
from sqlalchemy import text

from src.models.delivery_challan import DeliveryChallanItem


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


def _cancel(client, challan: dict) -> None:
    ok(client.post(f"/api/delivery-challans/{challan['id']}/cancel"))


def _uncounted_then_counted(client, ledger_id):
    """A challan for 5 while counting is off, then counting turned on with 10 counted."""
    product = create_product(client, "DCL-LATE", maintain_inventory=False, initial_quantity=0)
    challan = create_challan(client, ledger_id, [(product["id"], 5)])
    _set_counting(client, product, True)
    _adjust(client, product["id"], 10)
    return product, challan


def _counted_then_uncounted(client, db_session, ledger_id):
    """A challan for 5 out of 100 while counting is on, then counting turned off."""
    product = create_product(client, "DCL-EARLY")
    challan = create_challan(client, ledger_id, [(product["id"], 5)])
    assert _stock(db_session, product["id"]) == 95
    _set_counting(client, product, False)
    return product, challan


# ---------------------------------------------------------------------------
# Saved while counting was off, released after it was turned on
# ---------------------------------------------------------------------------

def test_cancelling_a_challan_saved_before_counting_moves_nothing(client, db_session, ledger):
    product, challan = _uncounted_then_counted(client, ledger)
    assert _stock(db_session, product["id"]) == 10

    _cancel(client, challan)
    assert _stock(db_session, product["id"]) == 10


def test_editing_a_challan_saved_before_counting_moves_only_the_new_lines(client, db_session, ledger):
    product, challan = _uncounted_then_counted(client, ledger)

    # The old 5 never left; the new 7 are taken under today's setting.
    ok(update_challan(client, challan, [(product["id"], 7)]))
    assert _stock(db_session, product["id"]) == 3

    _cancel(client, challan)
    assert _stock(db_session, product["id"]) == 10


def test_invoicing_a_challan_saved_before_counting_releases_nothing(client, db_session, ledger):
    product, challan = _uncounted_then_counted(client, ledger)

    invoice = ok(convert(client, challan["id"]))
    # Only the invoice's own sale moves stock.
    assert _stock(db_session, product["id"]) == 5

    # Cancelling the invoice gives its 5 back and the re-opened challan holds them,
    # as the invoice moved stock; cancelling the challan then puts them back.
    ok(client.delete(f"/api/invoices/{invoice['id']}"))
    assert _stock(db_session, product["id"]) == 5
    _cancel(client, challan)
    assert _stock(db_session, product["id"]) == 10


# ---------------------------------------------------------------------------
# Saved while counting was on, released after it was turned off
# ---------------------------------------------------------------------------

def test_cancelling_a_counted_challan_after_counting_is_off_gives_its_stock_back(client, db_session, ledger):
    product, challan = _counted_then_uncounted(client, db_session, ledger)

    _cancel(client, challan)
    assert _stock(db_session, product["id"]) == 100


def test_editing_a_counted_challan_after_counting_is_off(client, db_session, ledger):
    product, challan = _counted_then_uncounted(client, db_session, ledger)

    # The old 5 come back; the new 7 are not taken, as counting is off now.
    ok(update_challan(client, challan, [(product["id"], 7)]))
    assert _stock(db_session, product["id"]) == 100

    _cancel(client, challan)
    assert _stock(db_session, product["id"]) == 100


def test_invoicing_a_counted_challan_after_counting_is_off(client, db_session, ledger):
    product, challan = _counted_then_uncounted(client, db_session, ledger)

    # The challan's 5 come back; the invoice, saved with counting off, takes nothing.
    invoice = ok(convert(client, challan["id"]))
    assert _stock(db_session, product["id"]) == 100

    ok(client.delete(f"/api/invoices/{invoice['id']}"))
    assert _stock(db_session, product["id"]) == 100
    _cancel(client, challan)
    assert _stock(db_session, product["id"]) == 100


def test_a_reopened_challan_releases_what_it_took_after_counting_is_off(client, db_session, ledger):
    """Invoice cancelled while counting is on, so the challan holds 5 again."""
    product = create_product(client, "DCL-REOPEN")
    challan = create_challan(client, ledger, [(product["id"], 5)])
    invoice = ok(convert(client, challan["id"]))
    ok(client.delete(f"/api/invoices/{invoice['id']}"))
    assert _stock(db_session, product["id"]) == 95
    _set_counting(client, product, False)

    _cancel(client, challan)
    assert _stock(db_session, product["id"]) == 100


def test_restoring_the_invoice_of_a_challan_edited_after_counting_is_off(client, db_session, ledger):
    """The re-opened challan was edited with counting off, so it holds nothing to release."""
    product = create_product(client, "DCL-RESTORE")
    challan = create_challan(client, ledger, [(product["id"], 5)])
    invoice = ok(convert(client, challan["id"]))
    ok(client.delete(f"/api/invoices/{invoice['id']}"))
    _set_counting(client, product, False)
    ok(update_challan(client, challan, [(product["id"], 4)]))
    assert _stock(db_session, product["id"]) == 100

    # The invoice's line moved stock when saved, so restoring it takes its 5 again.
    ok(client.post(f"/api/invoices/{invoice['id']}/restore"))
    assert _stock(db_session, product["id"]) == 95


# ---------------------------------------------------------------------------
# Unchanged behaviour
# ---------------------------------------------------------------------------

def test_new_challan_lines_record_whether_they_took_stock(client, db_session, ledger):
    counted = create_product(client, "DCL-REC-1")
    uncounted = create_product(client, "DCL-REC-2", maintain_inventory=False, initial_quantity=0)
    challan = create_challan(client, ledger, [(counted["id"], 1), (uncounted["id"], 1)])

    db_session.expire_all()
    recorded = {
        item.product_id: item.stock_applied
        for item in db_session.query(DeliveryChallanItem).filter(DeliveryChallanItem.challan_id == challan["id"])
    }
    assert recorded == {counted["id"]: True, uncounted["id"]: False}


def test_a_challan_line_with_no_record_follows_the_current_setting(client, db_session, ledger):
    """Rows written before the column existed and missed by the backfill."""
    product = create_product(client, "DCL-LEGACY")
    challan = create_challan(client, ledger, [(product["id"], 5)])
    db_session.query(DeliveryChallanItem).filter(
        DeliveryChallanItem.challan_id == challan["id"]
    ).update({"stock_applied": None})
    db_session.commit()

    _cancel(client, challan)
    assert _stock(db_session, product["id"]) == 100
