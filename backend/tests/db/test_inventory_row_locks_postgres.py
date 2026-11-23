"""A stock write waits for a held inventory row lock and keeps a concurrent update.

Stock changes read the inventory row, add to it and write it back. Without
FOR UPDATE two writers read the same quantity and the later write silently drops
the earlier one. SQLite ignores FOR UPDATE, so the API suite cannot show this.

Each test holds the inventory row from a separate connection, starts the request,
and changes the quantity from that connection before letting go: the request must
have waited, and must add to the quantity it finds after the wait. Skipped when
DATABASE_URL is not Postgres.
"""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from app_main import app
from src.core.config import settings
from test_quotation_bounds_postgres import tenant  # noqa: F401
from test_quotation_convert_postgres import _stock, app_db, deployment, signed_in  # noqa: F401
from test_quotation_invoice_locks_postgres import _call, _pile_up_behind_a_lock

pytestmark = pytest.mark.skipif(
    not settings.DATABASE_URL.startswith("postgres"),
    reason="row locks need Postgres",
)

LOCK_STOCK = "SELECT id FROM inventory WHERE product_id = :id FOR UPDATE"
CONCURRENT_RECEIPT = 50  # the other writer's committed change, made while the lock is held


def _receive_stock_while_held(product_id: int):
    def receive(owner):
        owner.execute(
            text("UPDATE inventory SET quantity = quantity + :n WHERE product_id = :id"),
            {"n": CONCURRENT_RECEIPT, "id": product_id},
        )
    return receive


def test_inventory_adjustment_waits_and_keeps_a_concurrent_update(app_db, tenant):
    product = tenant["product"]
    before = _stock(app_db, product)

    [response] = _pile_up_behind_a_lock(
        app_db, LOCK_STOCK, product,
        [_call("POST", "/api/inventory/adjust", json={"product_id": product, "quantity": 7})],
        while_held=_receive_stock_while_held(product),
    )

    assert response.status_code == 200, response.text
    assert _stock(app_db, product) == before + CONCURRENT_RECEIPT + 7


def test_invoice_waits_and_keeps_a_concurrent_update(app_db, tenant):
    product = tenant["product"]
    before = _stock(app_db, product)
    body = {
        "ledger_id": tenant["ledger"],
        "voucher_type": "sales",
        "items": [{"product_id": product, "quantity": 2, "unit_price": 100}],
    }

    [response] = _pile_up_behind_a_lock(
        app_db, LOCK_STOCK, product,
        [_call("POST", "/api/invoices/", json=body)],
        while_held=_receive_stock_while_held(product),
    )

    assert response.status_code == 200, response.text
    assert _stock(app_db, product) == before + CONCURRENT_RECEIPT - 2


def test_two_adjustments_both_land(app_db, tenant):
    product = tenant["product"]
    before = _stock(app_db, product)
    adjust = lambda quantity: _call("POST", "/api/inventory/adjust", json={"product_id": product, "quantity": quantity})

    responses = _pile_up_behind_a_lock(app_db, LOCK_STOCK, product, [adjust(3), adjust(4)])

    assert [r.status_code for r in responses] == [200, 200], [r.text[:200] for r in responses]
    assert _stock(app_db, product) == before + 7
