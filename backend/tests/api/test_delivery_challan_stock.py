"""Stock on delivery challans (#840): every row of the product spec's stock table.

A challan holds its goods out of stock only while it is open. Once invoiced, the
invoice's own sale stands; cancelled, it holds nothing. So at every point, for every
product that keeps stock:

    stock == opening + purchases - sales - (quantities on open challans)

The last test drives 60 random operations and checks exactly that after each one.
"""

import random
from decimal import Decimal

import pytest
from challan_helpers import (
    convert,
    create_challan,
    create_ledger,
    create_product,
    draft,
    get_challan,
    ok,
    seed_company,
    series_counters,
    stock,
    update_challan,
)
from sqlalchemy import text

OPENING = Decimal("100")


@pytest.fixture
def setup(client):
    seed_company(client)
    ledger = create_ledger(client)
    a = create_product(client, "A-1")
    b = create_product(client, "B-1")
    return client, ledger["id"], a["id"], b["id"]


def _sell(client, ledger_id, product_id, quantity, voucher_type="sales") -> dict:
    return ok(client.post("/api/invoices/", json={
        "ledger_id": ledger_id,
        "voucher_type": voucher_type,
        "items": [{"product_id": product_id, "quantity": quantity, "unit_price": 100}],
    }))


def _invoice_payload(invoice: dict, quantities: dict | None = None, extra=()) -> dict:
    items = []
    for item in invoice["items"]:
        quantity = (quantities or {}).get(item["product_id"], item["quantity"])
        items.append({"product_id": item["product_id"], "quantity": quantity, "unit_price": item["unit_price"]})
    for product_id, quantity in extra:
        items.append({"product_id": product_id, "quantity": quantity, "unit_price": 100})
    return {
        "ledger_id": invoice["ledger_id"],
        "voucher_type": invoice["voucher_type"],
        "invoice_date": invoice["invoice_date"][:10],
        "place_of_supply": invoice.get("place_of_supply"),
        "reference_notes": invoice.get("reference_notes"),
        "items": items,
    }


def _assert_refused_for_stock(response, needs: str | None = None):
    assert response.status_code == 400, response.text
    body = response.json()
    assert body["code"] == "insufficient_stock", body
    if needs is not None:
        assert needs in body["detail"], body["detail"]
    return body


# ---------------------------------------------------------------------------
# 1. Create
# ---------------------------------------------------------------------------

def test_saving_a_challan_reduces_stock(setup):
    client, ledger, a, b = setup
    challan = create_challan(client, ledger, [(a, 10), (b, 4)])
    assert challan["status"] == "open"
    assert stock(client, a) == OPENING - 10
    assert stock(client, b) == OPENING - 4


def test_two_lines_of_one_product_are_summed(setup):
    client, ledger, a, _ = setup
    create_challan(client, ledger, [(a, 10), (a, 5)])
    assert stock(client, a) == OPENING - 15


def test_too_little_stock_refuses_the_challan_and_saves_nothing(setup):
    client, ledger, a, b = setup
    counters = series_counters(client)
    response = client.post("/api/delivery-challans/", json={
        "ledger_id": ledger,
        "items": [{"product_id": b, "quantity": 5}, {"product_id": a, "quantity": 150}],
    })
    body = _assert_refused_for_stock(response, "this delivery challan needs 150")
    assert body["product_id"] == a
    assert body["available"] == "100" and body["required"] == "150"
    assert ok(client.get("/api/delivery-challans/"))["total"] == 0
    assert stock(client, a) == OPENING
    assert stock(client, b) == OPENING
    assert series_counters(client) == counters


def test_two_lines_that_only_together_exceed_stock_are_refused(setup):
    client, ledger, a, _ = setup
    response = client.post("/api/delivery-challans/", json={
        "ledger_id": ledger,
        "items": [{"product_id": a, "quantity": 60}, {"product_id": a, "quantity": 60}],
    })
    _assert_refused_for_stock(response, "needs 120")
    assert stock(client, a) == OPENING


def test_the_invoice_message_is_unchanged(setup):
    client, ledger, a, _ = setup
    response = client.post("/api/invoices/", json={
        "ledger_id": ledger,
        "items": [{"product_id": a, "quantity": 101, "unit_price": 100}],
    })
    _assert_refused_for_stock(response, "only 100 in stock, and this invoice needs 101.")


# ---------------------------------------------------------------------------
# 2. Edit
# ---------------------------------------------------------------------------

def test_editing_moves_stock_by_the_difference(setup):
    client, ledger, a, b = setup
    challan = create_challan(client, ledger, [(a, 10)])

    ok(update_challan(client, challan, [(a, 25)]))  # up
    assert stock(client, a) == OPENING - 25

    ok(update_challan(client, challan, [(a, 5)]))  # down
    assert stock(client, a) == OPENING - 5

    ok(update_challan(client, challan, [(a, 5), (b, 7)]))  # a product added
    assert stock(client, a) == OPENING - 5
    assert stock(client, b) == OPENING - 7

    ok(update_challan(client, challan, [(b, 7)]))  # a product removed
    assert stock(client, a) == OPENING
    assert stock(client, b) == OPENING - 7

    ok(update_challan(client, challan, [(b, 7)]))  # nothing changed
    assert stock(client, b) == OPENING - 7


def test_editing_beyond_stock_is_refused_and_moves_nothing(setup):
    client, ledger, a, _ = setup
    challan = create_challan(client, ledger, [(a, 10)])
    _sell(client, ledger, a, 80)  # 10 left
    # The challan already holds 10, so it may grow by the 10 on hand, not more.
    ok(update_challan(client, challan, [(a, 20)]))
    assert stock(client, a) == 0
    _assert_refused_for_stock(update_challan(client, challan, [(a, 21)]), "this delivery challan needs 1")
    assert stock(client, a) == 0
    assert get_challan(client, challan["id"])["items"][0]["quantity"] == 20


# ---------------------------------------------------------------------------
# 3. Cancel
# ---------------------------------------------------------------------------

def test_cancelling_puts_the_goods_back(setup):
    client, ledger, a, b = setup
    challan = create_challan(client, ledger, [(a, 10), (b, 3)])
    cancelled = ok(client.post(f"/api/delivery-challans/{challan['id']}/cancel"))
    assert cancelled["status"] == "cancelled" and cancelled["cancelled_at"]
    assert stock(client, a) == OPENING
    assert stock(client, b) == OPENING

    again = client.post(f"/api/delivery-challans/{challan['id']}/cancel")
    assert again.status_code == 400
    assert again.json()["detail"] == "Delivery challan is already cancelled"
    assert stock(client, a) == OPENING

    edit = update_challan(client, challan, [(a, 1)])
    assert edit.status_code == 400
    assert edit.json()["detail"] == "A cancelled delivery challan cannot be edited"
    assert stock(client, a) == OPENING


def test_an_invoiced_challan_cannot_be_cancelled_or_edited(setup):
    client, ledger, a, _ = setup
    challan = create_challan(client, ledger, [(a, 10)])
    invoice = ok(convert(client, challan["id"]))

    response = client.post(f"/api/delivery-challans/{challan['id']}/cancel")
    assert response.status_code == 400
    assert response.json()["detail"] == (
        f"This delivery challan has a live invoice ({invoice['invoice_number']}). Cancel the invoice first."
    )
    edit = update_challan(client, challan, [(a, 1)])
    assert edit.status_code == 400
    assert edit.json()["detail"] == "An invoiced delivery challan cannot be edited"
    assert stock(client, a) == OPENING - 10


# ---------------------------------------------------------------------------
# 4. Convert
# ---------------------------------------------------------------------------

def test_convert_same_quantity_moves_nothing_more(setup):
    client, ledger, a, _ = setup
    challan = create_challan(client, ledger, [(a, 10)])
    invoice = ok(convert(client, challan["id"]))
    assert stock(client, a) == OPENING - 10
    assert invoice["source_challan_id"] == challan["id"]
    assert get_challan(client, challan["id"])["status"] == "invoiced"


def test_convert_fewer_adds_the_difference_back(setup):
    client, ledger, a, _ = setup
    challan = create_challan(client, ledger, [(a, 10)])
    ok(convert(client, challan["id"], quantities={a: 8}))
    assert stock(client, a) == OPENING - 8


def test_convert_more_reduces_the_extra(setup):
    client, ledger, a, _ = setup
    challan = create_challan(client, ledger, [(a, 10)])
    ok(convert(client, challan["id"], quantities={a: 13}))
    assert stock(client, a) == OPENING - 13


def test_convert_with_a_line_not_on_the_challan_reduces_it_as_usual(setup):
    client, ledger, a, b = setup
    challan = create_challan(client, ledger, [(a, 10)])
    ok(convert(client, challan["id"], extra_lines=[(b, 4)]))
    assert stock(client, a) == OPENING - 10
    assert stock(client, b) == OPENING - 4


def test_convert_dropping_a_challan_line_brings_it_back(setup):
    client, ledger, a, b = setup
    challan = create_challan(client, ledger, [(a, 10), (b, 5)])
    assert stock(client, b) == OPENING - 5
    ok(convert(client, challan["id"], drop={b}))
    assert stock(client, a) == OPENING - 10
    assert stock(client, b) == OPENING


def test_convert_more_than_is_left_is_refused_and_moves_nothing(setup):
    client, ledger, a, _ = setup
    challan = create_challan(client, ledger, [(a, 10)])
    counters = series_counters(client)
    # 90 on the shelf plus the 10 the challan releases: 100 can be invoiced, 101 cannot.
    _assert_refused_for_stock(convert(client, challan["id"], quantities={a: 101}), "this invoice needs 101")
    assert stock(client, a) == OPENING - 10
    assert get_challan(client, challan["id"])["status"] == "open"
    assert series_counters(client) == counters
    ok(convert(client, challan["id"], quantities={a: 100}))
    assert stock(client, a) == 0


# ---------------------------------------------------------------------------
# 5. Cancel the invoice made from a challan
# ---------------------------------------------------------------------------

def test_cancelling_the_invoice_reopens_the_challan_and_takes_its_goods_out_again(setup):
    client, ledger, a, b = setup
    challan = create_challan(client, ledger, [(a, 10)])
    invoice = ok(convert(client, challan["id"], quantities={a: 8}, extra_lines=[(b, 3)]))
    assert stock(client, a) == OPENING - 8

    ok(client.delete(f"/api/invoices/{invoice['id']}"))
    reopened = get_challan(client, challan["id"])
    assert reopened["status"] == "open"
    assert reopened["invoiced_at"] is None
    assert reopened["invoice_id"] is None
    assert [row["status"] for row in reopened["invoices"]] == ["cancelled"]
    assert stock(client, a) == OPENING - 10
    # The extra line was the invoice's alone, so it comes back in full.
    assert stock(client, b) == OPENING

    # And it can be invoiced again.
    ok(convert(client, challan["id"], quantities={a: 10}))
    assert stock(client, a) == OPENING - 10


def test_cancelling_the_invoice_is_refused_when_the_goods_were_sold_since(setup):
    client, ledger, a, _ = setup
    challan = create_challan(client, ledger, [(a, 10)])
    invoice = ok(convert(client, challan["id"], quantities={a: 2}))
    assert stock(client, a) == OPENING - 2
    _sell(client, ledger, a, 97)
    assert stock(client, a) == 1

    # +2 back from the invoice makes 3; re-opening the challan needs 10.
    response = client.delete(f"/api/invoices/{invoice['id']}")
    body = _assert_refused_for_stock(response, f"re-opening delivery challan {challan['challan_number']} needs 10")
    assert body["available"] == "3"
    assert ok(client.get(f"/api/invoices/{invoice['id']}"))["status"] == "active"
    assert get_challan(client, challan["id"])["status"] == "invoiced"
    assert stock(client, a) == 1


# ---------------------------------------------------------------------------
# 6. Restore the cancelled invoice
# ---------------------------------------------------------------------------

def test_restoring_the_invoice_invoices_the_challan_again(setup):
    client, ledger, a, _ = setup
    challan = create_challan(client, ledger, [(a, 10)])
    invoice = ok(convert(client, challan["id"], quantities={a: 8}))
    ok(client.delete(f"/api/invoices/{invoice['id']}"))
    assert stock(client, a) == OPENING - 10

    restored = ok(client.post(f"/api/invoices/{invoice['id']}/restore"))
    assert restored["status"] == "active"
    again = get_challan(client, challan["id"])
    assert again["status"] == "invoiced" and again["invoiced_at"]
    assert again["invoice_id"] == invoice["id"]
    assert stock(client, a) == OPENING - 8


def test_restoring_after_the_challan_was_edited_releases_what_it_holds_now(setup):
    client, ledger, a, _ = setup
    challan = create_challan(client, ledger, [(a, 10)])
    invoice = ok(convert(client, challan["id"], quantities={a: 8}))
    ok(client.delete(f"/api/invoices/{invoice['id']}"))
    ok(update_challan(client, challan, [(a, 15)]))
    assert stock(client, a) == OPENING - 15

    ok(client.post(f"/api/invoices/{invoice['id']}/restore"))
    assert get_challan(client, challan["id"])["status"] == "invoiced"
    assert stock(client, a) == OPENING - 8


def test_restoring_is_refused_once_the_challan_was_invoiced_again(setup):
    client, ledger, a, _ = setup
    challan = create_challan(client, ledger, [(a, 10)])
    first = ok(convert(client, challan["id"], quantities={a: 8}))
    ok(client.delete(f"/api/invoices/{first['id']}"))
    second = ok(convert(client, challan["id"], quantities={a: 9}))
    assert stock(client, a) == OPENING - 9

    response = client.post(f"/api/invoices/{first['id']}/restore")
    assert response.status_code == 409, response.text
    detail = response.json()["detail"]
    assert detail["code"] == "challan_reinvoiced"
    assert detail["invoice_id"] == second["id"]
    assert detail["invoice_number"] == second["invoice_number"]
    assert detail["message"] == (
        f"{challan['challan_number']} was invoiced again as {second['invoice_number']}. Cancel that invoice first."
    )
    assert ok(client.get(f"/api/invoices/{first['id']}"))["status"] == "cancelled"
    assert stock(client, a) == OPENING - 9


def test_restoring_after_the_challan_was_cancelled_leaves_it_cancelled(setup):
    client, ledger, a, _ = setup
    challan = create_challan(client, ledger, [(a, 10)])
    invoice = ok(convert(client, challan["id"], quantities={a: 8}))
    ok(client.delete(f"/api/invoices/{invoice['id']}"))
    ok(client.post(f"/api/delivery-challans/{challan['id']}/cancel"))
    assert stock(client, a) == OPENING

    restored = client.post(f"/api/invoices/{invoice['id']}/restore")
    assert restored.status_code == 200, restored.text
    assert get_challan(client, challan["id"])["status"] == "cancelled"
    assert stock(client, a) == OPENING - 8

    # Cancelling that invoice again leaves the cancelled challan alone.
    ok(client.delete(f"/api/invoices/{invoice['id']}"))
    assert get_challan(client, challan["id"])["status"] == "cancelled"
    assert stock(client, a) == OPENING


# ---------------------------------------------------------------------------
# 7. Edit the invoice made from a challan
# ---------------------------------------------------------------------------

def test_editing_the_invoice_adjusts_against_the_challan_state(setup):
    client, ledger, a, b = setup
    challan = create_challan(client, ledger, [(a, 10)])
    invoice = ok(convert(client, challan["id"], quantities={a: 8}))
    assert stock(client, a) == OPENING - 8

    edited = ok(client.put(f"/api/invoices/{invoice['id']}", json=_invoice_payload(invoice, {a: 12})))
    assert edited["source_challan_id"] == challan["id"]
    assert edited["source_challan_number"] == challan["challan_number"]
    assert stock(client, a) == OPENING - 12

    ok(client.put(f"/api/invoices/{invoice['id']}", json=_invoice_payload(edited, {a: 3}, extra=[(b, 2)])))
    assert stock(client, a) == OPENING - 3
    assert stock(client, b) == OPENING - 2
    assert get_challan(client, challan["id"])["status"] == "invoiced"

    # Cancelling the edited invoice still lands on the challan's out state.
    ok(client.delete(f"/api/invoices/{invoice['id']}"))
    assert stock(client, a) == OPENING - 10
    assert stock(client, b) == OPENING


# ---------------------------------------------------------------------------
# 8. Products that keep no stock
# ---------------------------------------------------------------------------

def _raw_quantity(db_session, product_id):
    row = db_session.execute(
        text("SELECT quantity FROM inventory WHERE product_id = :p"), {"p": product_id}
    ).first()
    return None if row is None else Decimal(str(row[0]))


def test_products_without_inventory_never_move(setup, db_session):
    client, ledger, a, _ = setup
    service = create_product(client, "SVC-1", maintain_inventory=False, initial_quantity=0, hsn_sac="998313")
    before = _raw_quantity(db_session, service["id"])

    challan = create_challan(client, ledger, [(service["id"], 500), (a, 1)])
    assert _raw_quantity(db_session, service["id"]) == before
    ok(update_challan(client, challan, [(service["id"], 900), (a, 1)]))
    assert _raw_quantity(db_session, service["id"]) == before
    invoice = ok(convert(client, challan["id"], quantities={service["id"]: 3}))
    assert _raw_quantity(db_session, service["id"]) == before
    ok(client.delete(f"/api/invoices/{invoice['id']}"))
    assert _raw_quantity(db_session, service["id"]) == before
    ok(client.post(f"/api/delivery-challans/{challan['id']}/cancel"))
    assert _raw_quantity(db_session, service["id"]) == before
    assert stock(client, a) == OPENING


def test_a_product_that_stops_keeping_stock_is_left_alone(setup, db_session):
    """The flag is read at the time of each movement, as invoice reversal does."""
    client, ledger, a, _ = setup
    challan = create_challan(client, ledger, [(a, 10)])
    assert stock(client, a) == OPENING - 10
    db_session.execute(text("UPDATE products SET maintain_inventory = 0 WHERE id = :p"), {"p": a})
    db_session.commit()
    ok(client.post(f"/api/delivery-challans/{challan['id']}/cancel"))
    assert _raw_quantity(db_session, a) == OPENING - 10


# ---------------------------------------------------------------------------
# 9. Serial-numbered products
# ---------------------------------------------------------------------------

def test_serial_numbered_products_are_refused(setup):
    client, ledger, a, _ = setup
    phone = create_product(client, "PHONE-1", track_serials=True, initial_quantity=0)
    response = client.post("/api/delivery-challans/", json={
        "ledger_id": ledger,
        "items": [{"product_id": a, "quantity": 1}, {"product_id": phone["id"], "quantity": 1}],
    })
    assert response.status_code == 400, response.text
    assert response.json()["detail"] == (
        "Widget PHONE-1 is serial-numbered. Delivery challans don't support serial-numbered products yet, "
        "so bill it on an invoice instead."
    )
    assert stock(client, a) == OPENING
    assert ok(client.get("/api/delivery-challans/"))["total"] == 0

    challan = create_challan(client, ledger, [(a, 1)])
    edit = update_challan(client, challan, [(phone["id"], 1)])
    assert edit.status_code == 400
    assert "serial-numbered" in edit.json()["detail"]
    assert stock(client, a) == OPENING - 1


def _turn_on_serials(client, product_id: int, count: int):
    """PUT the product with tracking on and one serial for each unit in stock."""
    product = ok(client.get(f"/api/products/{product_id}"))
    return client.put(f"/api/products/{product_id}", json={
        "sku": product["sku"],
        "name": product["name"],
        "hsn_sac": product["hsn_sac"],
        "price": product["price"],
        "gst_rate": product["gst_rate"],
        "maintain_inventory": True,
        "track_serials": True,
        "serial_numbers": [f"SN-{product_id}-{n}" for n in range(count)],
    })


def _serials_in_stock(db_session, product_id: int) -> int:
    return db_session.execute(
        text("SELECT COUNT(*) FROM product_serials WHERE product_id = :p AND status = 'in_stock'"),
        {"p": product_id},
    ).scalar()


def test_serial_numbers_cannot_be_turned_on_while_an_open_challan_holds_the_product(setup, db_session):
    client, ledger, a, _ = setup
    challan = create_challan(client, ledger, [(a, 3)])
    response = _turn_on_serials(client, a, 97)
    assert response.status_code == 400, response.text
    assert response.json()["detail"] == (
        f"Widget A-1 is on open delivery challan {challan['challan_number']}. "
        "Invoice or cancel it before turning on serial numbers."
    )
    assert ok(client.get(f"/api/products/{a}"))["track_serials"] is False
    assert _serials_in_stock(db_session, a) == 0

    # Once the challan no longer holds it, tracking turns on and stock matches the serials.
    ok(client.post(f"/api/delivery-challans/{challan['id']}/cancel"))
    ok(_turn_on_serials(client, a, 100))
    assert stock(client, a) == OPENING
    assert _serials_in_stock(db_session, a) == 100


def test_a_challan_never_moves_stock_of_a_product_that_became_serial_numbered(setup, db_session):
    client, ledger, a, _ = setup
    challan = create_challan(client, ledger, [(a, 3)])
    invoice = ok(convert(client, challan["id"]))
    # Invoiced, so the challan holds nothing and tracking may be turned on.
    ok(_turn_on_serials(client, a, 97))
    assert stock(client, a) == 97 and _serials_in_stock(db_session, a) == 97

    # Cancelling the invoice would re-open the challan and take 3 out with no serials.
    response = client.delete(f"/api/invoices/{invoice['id']}")
    assert response.status_code == 400, response.text
    assert response.json()["detail"] == (
        "Widget A-1 is now serial-numbered, and a delivery challan can't move its stock. "
        "Turn off serial numbers for it first."
    )
    assert ok(client.get(f"/api/invoices/{invoice['id']}"))["status"] == "active"
    assert get_challan(client, challan["id"])["status"] == "invoiced"
    assert stock(client, a) == 97 and _serials_in_stock(db_session, a) == 97


# ---------------------------------------------------------------------------
# 10. The invariant, over random operations
# ---------------------------------------------------------------------------

def _expected_stock(db_session, company_id: int, product_id: int) -> Decimal:
    def total(sql: str) -> Decimal:
        value = db_session.execute(text(sql), {"c": company_id, "p": product_id}).scalar()
        return Decimal(str(value or 0))

    purchases = total("""
        SELECT SUM(ii.quantity) FROM invoice_items ii JOIN invoices i ON i.id = ii.invoice_id
         WHERE i.company_id = :c AND ii.product_id = :p AND i.status = 'active' AND i.voucher_type = 'purchase'
    """)
    sales = total("""
        SELECT SUM(ii.quantity) FROM invoice_items ii JOIN invoices i ON i.id = ii.invoice_id
         WHERE i.company_id = :c AND ii.product_id = :p AND i.status = 'active' AND i.voucher_type = 'sales'
    """)
    on_open_challans = total("""
        SELECT SUM(ci.quantity) FROM delivery_challan_items ci JOIN delivery_challans c ON c.id = ci.challan_id
         WHERE c.company_id = :c AND ci.product_id = :p AND c.status = 'open'
    """)
    return OPENING + purchases - sales - on_open_challans


def _actual_stock(db_session, company_id: int, product_id: int) -> Decimal:
    value = db_session.execute(
        text("SELECT quantity FROM inventory WHERE company_id = :c AND product_id = :p"),
        {"c": company_id, "p": product_id},
    ).scalar()
    return Decimal(str(value))


def test_invariant_holds_after_every_random_operation(client, db_session):
    company = seed_company(client)
    company_id = company["id"]
    ledgers = [create_ledger(client)["id"], create_ledger(client, "Customer Two", gst="")["id"]]
    products = [create_product(client, "A-1")["id"], create_product(client, "B-1")["id"]]
    rng = random.Random(840)

    challans: list[int] = []
    invoices: list[int] = []
    outcomes: dict[str, list[int]] = {}

    def random_lines():
        count = rng.choice([1, 1, 2, 3])
        return [(rng.choice(products), rng.randint(1, 30)) for _ in range(count)]

    def op_create():
        response = client.post("/api/delivery-challans/", json={
            "ledger_id": rng.choice(ledgers),
            "items": [{"product_id": p, "quantity": q, "unit_price": 100} for p, q in random_lines()],
        })
        if response.status_code == 200:
            challans.append(response.json()["id"])
        return response

    def op_edit():
        if not challans:
            return None
        challan = get_challan(client, rng.choice(challans))
        return update_challan(client, challan, random_lines())

    def op_cancel():
        if not challans:
            return None
        return client.post(f"/api/delivery-challans/{rng.choice(challans)}/cancel")

    def op_convert():
        if not challans:
            return None
        challan_id = rng.choice(challans)
        draft_response = client.get(f"/api/delivery-challans/{challan_id}/conversion-draft")
        if draft_response.status_code != 200:
            return draft_response
        payload = draft_response.json()["invoice"]
        items = []
        for item in payload["items"]:
            if len(payload["items"]) > 1 and rng.random() < 0.15:
                continue  # a challan line dropped from the invoice
            item["quantity"] = max(1, item["quantity"] + rng.randint(-5, 5))
            items.append(item)
        if rng.random() < 0.25:
            items.append({"product_id": rng.choice(products), "quantity": rng.randint(1, 10), "unit_price": 100})
        payload["items"] = items
        if rng.random() < 0.2:
            payload["ledger_id"] = rng.choice(ledgers)
        response = client.post(f"/api/delivery-challans/{challan_id}/convert", json=payload)
        if response.status_code == 200:
            invoices.append(response.json()["id"])
        return response

    def op_cancel_invoice():
        if not invoices:
            return None
        return client.delete(f"/api/invoices/{rng.choice(invoices)}")

    def op_restore_invoice():
        if not invoices:
            return None
        return client.post(f"/api/invoices/{rng.choice(invoices)}/restore")

    def op_edit_invoice():
        if not invoices:
            return None
        invoice = ok(client.get(f"/api/invoices/{rng.choice(invoices)}"))
        if invoice["status"] != "active":
            return client.put(f"/api/invoices/{invoice['id']}", json=_invoice_payload(invoice))
        quantities = {item["product_id"]: max(1, item["quantity"] + rng.randint(-6, 6)) for item in invoice["items"]}
        extra = [(rng.choice(products), rng.randint(1, 5))] if rng.random() < 0.2 else []
        return client.put(f"/api/invoices/{invoice['id']}", json=_invoice_payload(invoice, quantities, extra))

    def op_purchase():
        # Keeps the shelf from running dry, so the later operations still have room.
        return client.post("/api/invoices/", json={
            "ledger_id": rng.choice(ledgers),
            "voucher_type": "purchase",
            "items": [{"product_id": rng.choice(products), "quantity": rng.randint(5, 25), "unit_price": 50}],
        })

    operations = [
        (op_create, 5), (op_edit, 3), (op_cancel, 2), (op_convert, 4),
        (op_cancel_invoice, 2), (op_restore_invoice, 2), (op_edit_invoice, 2), (op_purchase, 1),
    ]
    names, weights = zip(*[(op, weight) for op, weight in operations])

    for step in range(60):
        op = rng.choices(names, weights)[0]
        response = op()
        if response is not None:
            assert response.status_code in (200, 400, 409), (step, op.__name__, response.status_code, response.text)
            outcomes.setdefault(op.__name__, []).append(response.status_code)
        for product_id in products:
            expected = _expected_stock(db_session, company_id, product_id)
            actual = _actual_stock(db_session, company_id, product_id)
            assert actual == expected, (step, op.__name__, product_id, actual, expected)
            assert actual >= 0

    # The sequence really exercised every path, successes included.
    for name in (
        "op_create", "op_edit", "op_cancel", "op_convert",
        "op_cancel_invoice", "op_restore_invoice", "op_edit_invoice",
    ):
        assert 200 in outcomes.get(name, []), (name, outcomes)


def test_the_draft_reflects_the_challan(setup):
    """Not a stock rule, but the stock tests rely on the draft carrying the challan lines."""
    client, ledger, a, b = setup
    challan = create_challan(client, ledger, [(a, 10), (b, 2)])
    body = draft(client, challan["id"])
    assert [(item["product_id"], item["quantity"]) for item in body["invoice"]["items"]] == [(a, 10), (b, 2)]
    assert [(line["product_id"], line["quantity"]) for line in body["challan_items"]] == [(a, 10), (b, 2)]
