"""Real PostgreSQL coverage for company account opening_balance limits (#755).

SQLite ignores NUMERIC precision and scale, and happily stores NaN/Infinity in a
numeric column, so none of this can be proven against the normal test database.
These tests hit the API with Postgres behind it and assert that out-of-range or
non-finite opening balances are refused with 422 before any row is written, that
the largest value the column can hold still saves, and that a request Postgres
would otherwise accept but turn into NaN/Infinity never breaks the accounts list.

Skipped when DATABASE_URL is not Postgres.
"""

import json

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from app_main import app
from src.core.config import settings
# Fixtures, imported by name so pytest finds them here too.
from test_quotation_convert_postgres import (  # noqa: F401
    _seed_company,
    app_db,
    deployment,
    signed_in,
)

pytestmark = pytest.mark.skipif(
    not settings.DATABASE_URL.startswith("postgres"),
    reason="column limits need Postgres",
)


@pytest.fixture
def tenant(app_db, signed_in):  # noqa: F811
    client = TestClient(app)
    seeded = _seed_company(
        client, signed_in, app_db, "accounts@alpha.example", "Account Traders", "ACC-1"
    )
    seeded["client"] = client
    return seeded


def _added(listing) -> list[dict]:
    """The accounts a test added, without the "Cash" account every new company starts with."""
    return [item for item in listing.json() if item["display_name"] == "Main Account"]


def _accounts_count(db) -> int:
    with db.owner_engine.connect() as conn:
        return conn.execute(text("SELECT count(*) FROM company_accounts")).scalar_one()


OUT_OF_RANGE = [
    pytest.param(1e11, id="far_over_the_column"),
    pytest.param(9_999_999_999.996, id="rounds_up_to_the_column_limit"),
]

NOT_FINITE = [
    pytest.param(float("nan"), id="nan"),
    pytest.param(float("inf"), id="infinity"),
]


def _account(opening_balance, **extra) -> dict:
    return {
        "account_type": "bank",
        "display_name": "Main Account",
        "opening_balance": opening_balance,
        **extra,
    }


@pytest.mark.parametrize("amount", OUT_OF_RANGE)
def test_create_refuses_opening_balance_that_overflows_the_column(tenant, app_db, amount):
    # Not zero: every new company starts with a seeded "Cash" account.
    before = _accounts_count(app_db)
    response = tenant["client"].post("/api/company-accounts/", json=_account(amount))
    assert response.status_code == 422, response.text[:500]
    assert response.json()["detail"][0]["loc"] == ["body", "opening_balance"]
    assert _accounts_count(app_db) == before


@pytest.mark.parametrize("amount", OUT_OF_RANGE)
def test_update_refuses_opening_balance_that_overflows_the_column(tenant, app_db, amount):
    created = tenant["client"].post("/api/company-accounts/", json=_account(100)).json()
    response = tenant["client"].put(
        f"/api/company-accounts/{created['id']}", json={"opening_balance": amount}
    )
    assert response.status_code == 422, response.text[:500]
    assert response.json()["detail"][0]["loc"] == ["body", "opening_balance"]
    with app_db.owner_engine.connect() as conn:
        assert conn.execute(
            text("SELECT opening_balance FROM company_accounts WHERE id = :id"),
            {"id": created["id"]},
        ).scalar_one() == pytest.approx(100)


@pytest.mark.parametrize("amount", NOT_FINITE)
def test_create_refuses_nan_and_infinity_opening_balance(tenant, app_db, amount):
    # On main this request returns 500, but Postgres still stores NaN in the
    # NUMERIC column, so the row is saved despite the 500 -- and every later
    # GET /api/company-accounts/ for this company then 500s too. Fixed, the
    # request is rejected before any row is written. json.dumps (unlike
    # httpx's own json= encoding) emits the bare NaN/Infinity literal, which
    # is exactly what a non-browser API client can send.
    before = _accounts_count(app_db)
    response = tenant["client"].post(
        "/api/company-accounts/",
        content=json.dumps(_account(amount)),
        headers={"Content-Type": "application/json"},
    )
    assert response.status_code == 422, response.text[:500]
    assert response.json()["detail"][0]["loc"] == ["body", "opening_balance"]
    assert _accounts_count(app_db) == before

    listing = tenant["client"].get("/api/company-accounts/")
    assert listing.status_code == 200, listing.text[:500]
    assert _added(listing) == []


@pytest.mark.parametrize("amount", NOT_FINITE)
def test_update_refuses_nan_and_infinity_opening_balance(tenant, app_db, amount):
    created = tenant["client"].post("/api/company-accounts/", json=_account(100)).json()
    response = tenant["client"].put(
        f"/api/company-accounts/{created['id']}",
        content=json.dumps({"opening_balance": amount}),
        headers={"Content-Type": "application/json"},
    )
    assert response.status_code == 422, response.text[:500]
    assert response.json()["detail"][0]["loc"] == ["body", "opening_balance"]

    listing = tenant["client"].get("/api/company-accounts/")
    assert listing.status_code == 200, listing.text[:500]
    assert _added(listing)[0]["opening_balance"] == pytest.approx(100)


def test_largest_storable_opening_balance_is_saved(tenant, app_db):
    created = tenant["client"].post(
        "/api/company-accounts/", json=_account(9_999_999_999.99)
    )
    assert created.status_code == 200, created.text[:500]
    assert created.json()["opening_balance"] == 9_999_999_999.99

    listing = tenant["client"].get("/api/company-accounts/")
    assert listing.status_code == 200, listing.text[:500]
    assert _added(listing)[0]["opening_balance"] == 9_999_999_999.99
