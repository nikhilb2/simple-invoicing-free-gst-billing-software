"""Production and returns must reject stock overflow before NUMERIC(12, 3) does."""

from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import event, text

from app_main import app
from src.core.config import settings
from src.models.production_transaction import ProductionTransaction
from src.services.gst_tax_service import india_today
from test_quotation_bounds_postgres import tenant  # noqa: F401
from test_quotation_convert_postgres import app_db, deployment, signed_in  # noqa: F401

pytestmark = pytest.mark.skipif(
    not settings.DATABASE_URL.startswith("postgres"),
    reason="column limits need Postgres",
)

MAX_STOCK = Decimal("999999999.999")
STOCK_ERROR = "Stock for Stock limit widget can't go above 999,999,999.999."


@pytest.fixture
def product(tenant):
    response = tenant["client"].post("/api/products/", json={
        "sku": "STOCK-LIMIT",
        "name": "Stock limit widget",
        "price": 10,
        "gst_rate": 0,
        "initial_quantity": 5,
        "allow_decimal": True,
        "is_producable": True,
    })
    assert response.status_code == 200, response.text
    return response.json()["id"]


def _stock(app_db, product_id):
    with app_db.owner_engine.connect() as conn:
        return conn.execute(
            text("SELECT quantity FROM inventory WHERE product_id = :id"),
            {"id": product_id},
        ).scalar_one()


def _set_stock(app_db, product_id, quantity):
    with app_db.owner_engine.begin() as conn:
        conn.execute(
            text("UPDATE inventory SET quantity = :quantity WHERE product_id = :id"),
            {"id": product_id, "quantity": Decimal(quantity)},
        )


def _state(app_db):
    """Read committed state on a separate connection after the request closes."""
    queries = {
        "stock": "SELECT product_id, quantity FROM inventory ORDER BY product_id",
        "production": "SELECT id FROM production_transactions ORDER BY id",
        "notes": "SELECT id, status, cancelled_at FROM credit_notes ORDER BY id",
        "items": "SELECT id FROM credit_note_items ORDER BY id",
        "refs": "SELECT id FROM credit_note_invoice_refs ORDER BY id",
        "invoices": "SELECT id, credit_status FROM invoices ORDER BY id",
        "series": "SELECT id, next_sequence FROM invoice_series ORDER BY id",
    }
    with app_db.owner_engine.connect() as conn:
        return {key: conn.execute(text(query)).all() for key, query in queries.items()}


def _add_component(tenant, product):
    response = tenant["client"].post("/api/bom/", json={
        "product_id": product,
        "component_product_id": tenant["product"],
        "quantity_required": 1,
    })
    assert response.status_code == 201, response.text


@pytest.mark.parametrize("stock, quantity, with_bom", [
    pytest.param("0", 2_000_000_000, False, id="oversized-run"),
    pytest.param("999999999", 2, False, id="existing-stock"),
    pytest.param("999999999", 2, True, id="component-rollback"),
    pytest.param("999999999", 0.9995, True, id="rounds-to-limit"),
    pytest.param("999999999", 0.9996, True, id="rounds-past-limit"),
])
def test_production_overflow_returns_400_without_changes(tenant, app_db, product, stock, quantity, with_bom):
    if with_bom:
        _add_component(tenant, product)
    _set_stock(app_db, product, stock)
    before = _state(app_db)

    response = TestClient(app, raise_server_exceptions=False).post(
        "/api/inventory/produce", json={"product_id": product, "quantity": quantity},
    )

    assert response.status_code == 400, response.text
    assert response.json() == {"detail": STOCK_ERROR}
    assert _state(app_db) == before


@pytest.mark.parametrize("stock, quantity, with_bom", [
    pytest.param("0", 999_999_999.999, False, id="largest-run"),
    pytest.param("999999999", 0.999, True, id="exact-maximum"),
    pytest.param("999999999", 0.9994, True, id="rounds-within-limit"),
])
def test_production_allows_maximum_stock(tenant, app_db, product, stock, quantity, with_bom):
    if with_bom:
        _add_component(tenant, product)
    _set_stock(app_db, product, stock)

    response = tenant["client"].post(
        "/api/inventory/produce", json={"product_id": product, "quantity": quantity},
    )

    assert response.status_code == 200, response.text
    assert _stock(app_db, product) == MAX_STOCK
    assert len(_state(app_db)["production"]) == 1


def _return_payload(tenant, product, action, split_lines=False):
    client = tenant["client"]
    response = client.post("/api/invoices/", json={
        "ledger_id": tenant["ledger"],
        "voucher_type": "sales" if action == "sales-return" else "purchase",
        "items": [{"product_id": product, "quantity": 5, "unit_price": 10}],
    })
    assert response.status_code == 200, response.text
    invoice = response.json()
    payload = {
        "ledger_id": tenant["ledger"],
        "invoice_ids": [invoice["id"]],
        "credit_note_type": "return",
        "items": [{
            "invoice_id": invoice["id"],
            "invoice_item_id": invoice["items"][0]["id"],
            "quantity": quantity,
        } for quantity in ([2, 3] if split_lines else [5])],
    }
    if action == "cancel-purchase-return":
        payload.update(
            direction="inward",
            supplier_credit_note_number="SUP-RETURN-1",
            supplier_credit_note_date=india_today().isoformat(),
        )
        response = client.post("/api/credit-notes/", json=payload)
        assert response.status_code == 201, response.text
        return f"/api/credit-notes/{response.json()['id']}/cancel", {}
    return "/api/credit-notes/", payload


@pytest.mark.parametrize("action", ["sales-return", "cancel-purchase-return"])
@pytest.mark.parametrize("stock, split_lines", [
    pytest.param("999999999", False, id="past-limit"),
    pytest.param("999999995", False, id="at-limit"),
    pytest.param("999999996", True, id="earlier-line-rollback"),
])
def test_return_overflow_returns_400_without_changes(tenant, app_db, product, action, stock, split_lines):
    url, payload = _return_payload(tenant, product, action, split_lines)
    _set_stock(app_db, product, stock)
    before = _state(app_db)

    response = TestClient(app, raise_server_exceptions=False).post(url, json=payload)

    assert response.status_code == 400, response.text
    assert response.json() == {"detail": STOCK_ERROR}
    assert _state(app_db) == before
    if action == "sales-return":
        assert before["notes"] == []
    else:
        assert len(before["notes"]) == 1
        assert before["notes"][0][1:] == ("active", None)


@pytest.mark.parametrize("action", ["sales-return", "cancel-purchase-return"])
def test_return_allows_maximum_stock(tenant, app_db, product, action):
    url, payload = _return_payload(tenant, product, action)
    _set_stock(app_db, product, "999999994.999")

    response = tenant["client"].post(url, json=payload)

    assert response.status_code == (201 if action == "sales-return" else 200), response.text
    assert _stock(app_db, product) == MAX_STOCK
    notes = _state(app_db)["notes"]
    if action == "sales-return":
        assert len(notes) == 1
        assert notes[0][1:] == ("active", None)
    else:
        assert notes == []


def test_production_database_error_is_private_and_rolls_back(tenant, app_db, product):
    _add_component(tenant, product)
    before = _state(app_db)

    def fail_insert(mapper, connection, target):
        connection.execute(text("SELECT 1 / 0"))

    event.listen(ProductionTransaction, "before_insert", fail_insert)
    try:
        response = TestClient(app, raise_server_exceptions=False).post(
            "/api/inventory/produce", json={"product_id": product, "quantity": 1},
        )
    finally:
        event.remove(ProductionTransaction, "before_insert", fail_insert)

    assert response.status_code == 400, response.text
    assert response.json() == {"detail": "Production failed. Please try again."}
    assert _state(app_db) == before
