"""A NUL character (#775) is refused with a 422, never passed to Postgres.

Postgres cannot store or compare text containing a NUL character (\\0): the value
gets past every schema's validation and the 500 only shows up once the query hits
the database. SQLite accepts a NUL happily, so this needs real Postgres to prove
the 500 is gone -- and that nothing was written when the request is refused.

Skipped when DATABASE_URL is not Postgres.
"""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from app_main import app
from src.core.config import settings
# Fixtures, imported by name so pytest finds them here too.
from test_quotation_bounds_postgres import tenant  # noqa: F401
from test_quotation_convert_postgres import app_db, deployment, signed_in  # noqa: F401

pytestmark = pytest.mark.skipif(
    not settings.DATABASE_URL.startswith("postgres"),
    reason="Postgres rejects a NUL character; SQLite stores it without complaint",
)

NUL = "\x00"


def test_product_create_with_nul_in_name_is_rejected_without_saving(tenant, app_db):  # noqa: F811
    client = tenant["client"]
    with app_db.owner_engine.connect() as conn:
        count_before = conn.execute(text("SELECT count(*) FROM products")).scalar_one()

    response = client.post("/api/products/", json={
        "sku": "NUL-NAME",
        "name": f"Bad{NUL}name",
        "price": 10,
    })

    assert response.status_code == 422, response.text
    assert "not allowed" in response.json()["detail"]
    with app_db.owner_engine.connect() as conn:
        assert conn.execute(text("SELECT count(*) FROM products")).scalar_one() == count_before


def test_ledger_update_with_nul_in_name_is_rejected_without_saving(tenant, app_db):  # noqa: F811
    client = tenant["client"]
    ledger_id = tenant["ledger"]
    # The ledgers API is backed by the "buyers" table (src/models/buyer.py).
    with app_db.owner_engine.connect() as conn:
        name_before = conn.execute(
            text("SELECT name FROM buyers WHERE id = :id"), {"id": ledger_id},
        ).scalar_one()

    response = client.put(f"/api/ledgers/{ledger_id}", json={
        "name": f"Led{NUL}ger",
        "address": "1 Market Road",
        "phone_number": "9876543210",
    })

    assert response.status_code == 422, response.text
    assert "not allowed" in response.json()["detail"]
    with app_db.owner_engine.connect() as conn:
        name_after = conn.execute(
            text("SELECT name FROM buyers WHERE id = :id"), {"id": ledger_id},
        ).scalar_one()
    assert name_after == name_before


def test_product_search_with_nul_query_param_is_rejected(tenant):  # noqa: F811
    client = tenant["client"]

    # httpx percent-encodes the NUL for us, the same as a client sending ?search=%00.
    response = client.get("/api/products/", params={"search": NUL})

    assert response.status_code == 422, response.text
    assert "not allowed" in response.json()["detail"]


def test_csv_import_fails_only_the_row_with_a_nul_character(tenant, app_db):  # noqa: F811
    client = tenant["client"]
    csv_content = (
        "item_code,item_name,selling_price\n"
        "GOOD-1,Good Item,10\n"
        f"BAD{NUL}1,Bad{NUL}Item,10\n"
    ).encode("utf-8")

    response = client.post(
        "/api/products/import-csv",
        files={"file": ("products.csv", csv_content, "text/csv")},
    )

    assert response.status_code == 200, response.text
    result = response.json()
    assert result["created"] == 1
    assert len(result["errors"]) == 1
    assert "not allowed" in result["errors"][0]["message"]

    with app_db.owner_engine.connect() as conn:
        good = conn.execute(
            text("SELECT count(*) FROM products WHERE sku = 'GOOD-1'")
        ).scalar_one()
        bad = conn.execute(
            text("SELECT count(*) FROM products WHERE sku LIKE 'BAD%'")
        ).scalar_one()
    assert good == 1
    assert bad == 0
