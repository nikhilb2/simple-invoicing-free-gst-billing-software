"""Delivery challans (#840) on real Postgres, as the restricted role in shared hosting.

SQLite ignores FOR UPDATE and serialises every writer, so none of the races here can
be proven on the suite's normal database. Two threads convert one challan through the
real app: one must win, the other gets a 409, and stock and the invoice number move
once. The stock invariant is checked over a random sequence too, as on SQLite.

Skipped when DATABASE_URL is not Postgres.
"""

import random
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal
from pathlib import Path

import pytest
from fastapi import Depends
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app_main import app
from src.api.deps import get_current_user
from src.core.config import settings
from src.db.session import get_db
from src.db.tenant_context import set_tenant_context
from src.models.delivery_challan import DeliveryChallan
from src.models.invoice import Invoice
from src.models.user import User, UserRole

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "api"))
import test_tenant_isolation as iso  # noqa: E402
from quotation_helpers import seed_financial_year  # noqa: E402

pytestmark = pytest.mark.skipif(
    not settings.DATABASE_URL.startswith("postgres"),
    reason="row locks and partial indexes need Postgres",
)

OPENING = Decimal("100")


@pytest.fixture(params=["shared_hosting", "single_tenant"])
def deployment(request, monkeypatch):
    monkeypatch.setattr(settings, "DEPLOYMENT_MODE", request.param)
    monkeypatch.setattr(settings, "PLATFORM_ADMIN_EMAILS", "")
    monkeypatch.setattr(settings, "MAX_COMPANIES_PER_USER", 3)
    return request.param


@pytest.fixture
def app_db(clean_rls_db, deployment):
    """Each request on its own connection: the app role in shared hosting, else the owner."""
    factory = clean_rls_db.AppSession if deployment == "shared_hosting" else clean_rls_db.OwnerSession

    def _get_db():
        db = factory()
        try:
            yield db
        finally:
            db.close()

    previous = app.dependency_overrides.get(get_db)
    app.dependency_overrides[get_db] = _get_db
    try:
        yield clean_rls_db
    finally:
        app.dependency_overrides[get_db] = previous


@pytest.fixture
def signed_in():
    holder = {"email": None}

    def _current_user(db: Session = Depends(get_db)) -> User:
        return db.query(User).filter(User.email == holder["email"]).one()

    previous = app.dependency_overrides.get(get_current_user)
    app.dependency_overrides[get_current_user] = _current_user

    def switch(email: str) -> None:
        holder["email"] = email

    try:
        yield switch
    finally:
        app.dependency_overrides[get_current_user] = previous


def _seed_company(client, signed_in, db, email: str, name: str, sku: str) -> dict:
    with db.OwnerSession() as owner:
        iso._user(owner, email, role=UserRole.admin)
    signed_in(email)
    company = iso._create_company(client, name)
    if not iso._ok(client.get("/api/financial-years/")):
        seed_financial_year(client)
    ledger = iso._create_ledger(client, f"{name} Customer")
    product = iso._create_product(client, sku)
    return {"company": company, "ledger": ledger, "product": product, "email": email}


def _create_challan(client, tenant: dict, quantity: int = 10) -> dict:
    return iso._ok(client.post("/api/delivery-challans/", json={
        "ledger_id": tenant["ledger"],
        "purpose": "job_work",
        "items": [{"product_id": tenant["product"], "quantity": quantity, "unit_price": 100}],
    }))


def _draft(client, challan_id: int) -> dict:
    return iso._ok(client.get(f"/api/delivery-challans/{challan_id}/conversion-draft"))["invoice"]


@pytest.mark.parametrize("column", ["challan_number", "ledger_name"])
@pytest.mark.parametrize("literal,lookalike", [("_", "x"), ("%", "anything"), ("\\", "")])
def test_search_treats_pattern_characters_literally(app_db, signed_in, column, literal, lookalike):
    client = TestClient(app)
    tenant = _seed_company(client, signed_in, app_db, "search@example.com", "Search Co", "SEARCH-1")
    matching = _create_challan(client, tenant, 1)
    other = _create_challan(client, tenant, 1)
    # Names may contain these characters. Updating snapshots also covers legacy
    # numbers, even though new challan numbers follow the stricter Rule 55 format.
    with app_db.OwnerSession() as db:
        for challan, value in ((matching, f"DC{literal}1"), (other, f"DC{lookalike}1")):
            row = db.get(DeliveryChallan, challan["id"])
            setattr(row, column, value)
        db.commit()

    for term in (literal, f"  dc{literal}1  "):
        result = iso._ok(client.get("/api/delivery-challans/", params={"search": term}))
        assert [row["id"] for row in result["items"]] == [matching["id"]]
        assert result["total"] == 1
        assert result["status_counts"] == {"open": 1}


def _stock(db, product_id: int) -> Decimal:
    with db.owner_engine.connect() as conn:
        return Decimal(str(conn.execute(
            text("SELECT quantity FROM inventory WHERE product_id = :p"), {"p": product_id}
        ).scalar()))


def _sales_counter(db, company_id: int) -> int:
    with db.owner_engine.connect() as conn:
        return conn.execute(text(
            "SELECT next_sequence FROM invoice_series WHERE voucher_type = 'sales' AND company_id = :c"
        ), {"c": company_id}).scalar()


def _invoices_for(db, challan_id: int) -> list[str]:
    with db.owner_engine.connect() as conn:
        return [row[0] for row in conn.execute(text(
            "SELECT status FROM invoices WHERE source_challan_id = :c ORDER BY id"
        ), {"c": challan_id})]


def _status_of(db, challan_id: int) -> str:
    with db.owner_engine.connect() as conn:
        return conn.execute(text("SELECT status FROM delivery_challans WHERE id = :c"), {"c": challan_id}).scalar()


def _expected_stock(db, company_id: int, product_id: int) -> Decimal:
    with db.owner_engine.connect() as conn:
        def total(sql: str) -> Decimal:
            return Decimal(str(conn.execute(text(sql), {"c": company_id, "p": product_id}).scalar() or 0))

        purchases = total("""
            SELECT SUM(ii.quantity) FROM invoice_items ii JOIN invoices i ON i.id = ii.invoice_id
             WHERE i.company_id = :c AND ii.product_id = :p AND i.status = 'active' AND i.voucher_type = 'purchase'
        """)
        sales = total("""
            SELECT SUM(ii.quantity) FROM invoice_items ii JOIN invoices i ON i.id = ii.invoice_id
             WHERE i.company_id = :c AND ii.product_id = :p AND i.status = 'active' AND i.voucher_type = 'sales'
        """)
        held = total("""
            SELECT SUM(ci.quantity) FROM delivery_challan_items ci JOIN delivery_challans c ON c.id = ci.challan_id
             WHERE c.company_id = :c AND ci.product_id = :p AND c.status = 'open'
        """)
    return OPENING + purchases - sales - held


# ---------------------------------------------------------------------------
# The invariant
# ---------------------------------------------------------------------------

def test_invariant_over_random_operations(app_db, signed_in):
    client = TestClient(app)
    tenant = _seed_company(client, signed_in, app_db, "alice@alpha.example", "Alpha Traders", "ALPHA-1")
    products = [tenant["product"], iso._create_product(client, "ALPHA-2")]
    ledgers = [tenant["ledger"], iso._create_ledger(client, "Alpha Second")]
    rng = random.Random(840)
    challans: list[int] = []
    invoices: list[int] = []
    successes: set[str] = set()

    def lines():
        return [
            {"product_id": rng.choice(products), "quantity": rng.randint(1, 30), "unit_price": 100}
            for _ in range(rng.choice([1, 2]))
        ]

    def create():
        response = client.post("/api/delivery-challans/", json={"ledger_id": rng.choice(ledgers), "items": lines()})
        if response.status_code == 200:
            challans.append(response.json()["id"])
        return response

    def edit():
        if not challans:
            return None
        challan = iso._ok(client.get(f"/api/delivery-challans/{rng.choice(challans)}"))
        return client.put(f"/api/delivery-challans/{challan['id']}", json={
            "ledger_id": challan["ledger_id"], "items": lines(),
        })

    def cancel():
        return client.post(f"/api/delivery-challans/{rng.choice(challans)}/cancel") if challans else None

    def convert():
        if not challans:
            return None
        challan_id = rng.choice(challans)
        response = client.get(f"/api/delivery-challans/{challan_id}/conversion-draft")
        if response.status_code != 200:
            return response
        payload = response.json()["invoice"]
        for item in payload["items"]:
            item["quantity"] = max(1, item["quantity"] + rng.randint(-5, 5))
        if rng.random() < 0.3:
            payload["items"].append({"product_id": rng.choice(products), "quantity": rng.randint(1, 5), "unit_price": 100})
        response = client.post(f"/api/delivery-challans/{challan_id}/convert", json=payload)
        if response.status_code == 200:
            invoices.append(response.json()["id"])
        return response

    def cancel_invoice():
        return client.delete(f"/api/invoices/{rng.choice(invoices)}") if invoices else None

    def restore_invoice():
        return client.post(f"/api/invoices/{rng.choice(invoices)}/restore") if invoices else None

    def edit_invoice():
        if not invoices:
            return None
        invoice = iso._ok(client.get(f"/api/invoices/{rng.choice(invoices)}"))
        return client.put(f"/api/invoices/{invoice['id']}", json={
            "ledger_id": invoice["ledger_id"],
            "voucher_type": "sales",
            "invoice_date": invoice["invoice_date"][:10],
            "reference_notes": invoice["reference_notes"],
            "items": [
                {"product_id": item["product_id"], "quantity": max(1, item["quantity"] + rng.randint(-4, 4)),
                 "unit_price": item["unit_price"]}
                for item in invoice["items"]
            ],
        })

    operations = [create] * 5 + [edit] * 2 + [cancel] + [convert] * 4 + [cancel_invoice] * 2 + [restore_invoice] * 2 + [edit_invoice] * 2
    for step in range(20):
        op = rng.choice(operations)
        response = op()
        if response is not None:
            assert response.status_code in (200, 400, 409), (step, op.__name__, response.text)
            if response.status_code == 200:
                successes.add(op.__name__)
        for product_id in products:
            assert _stock(app_db, product_id) == _expected_stock(app_db, tenant["company"], product_id), (
                step, op.__name__, product_id,
            )
    assert {"create", "convert"} <= successes, successes


# ---------------------------------------------------------------------------
# Races
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("attempt", range(3))
def test_two_threads_convert_one_challan(app_db, signed_in, attempt):
    client = TestClient(app)
    tenant = _seed_company(client, signed_in, app_db, "alice@alpha.example", "Alpha Traders", "ALPHA-1")
    challan = _create_challan(client, tenant, quantity=10)
    draft = _draft(client, challan["id"])
    for item in draft["items"]:
        item["quantity"] = 8
    assert _stock(app_db, tenant["product"]) == OPENING - 10
    counter_before = _sales_counter(app_db, tenant["company"])

    start = threading.Barrier(2)

    def convert():
        thread_client = TestClient(app)
        start.wait()
        return thread_client.post(f"/api/delivery-challans/{challan['id']}/convert", json=draft)

    with ThreadPoolExecutor(max_workers=2) as pool:
        responses = [future.result(timeout=30) for future in [pool.submit(convert), pool.submit(convert)]]

    statuses = sorted(response.status_code for response in responses)
    assert statuses == [200, 409], [response.text[:300] for response in responses]
    winner = next(response.json() for response in responses if response.status_code == 200)
    loser = next(response.json() for response in responses if response.status_code == 409)
    assert loser["detail"]["code"] == "challan_already_invoiced"
    assert loser["detail"]["invoice_id"] == winner["id"]
    assert loser["detail"]["invoice_number"] == winner["invoice_number"]

    assert _invoices_for(app_db, challan["id"]) == ["active"]
    # Released once (+10), sold once (-8).
    assert _stock(app_db, tenant["product"]) == OPENING - 8
    assert _sales_counter(app_db, tenant["company"]) == counter_before + 1
    assert _status_of(app_db, challan["id"]) == "invoiced"


def test_a_converter_really_waits_on_the_challan_lock(app_db, signed_in):
    """While a transaction holds the challan, conversion cannot get past it, and then sees its change."""
    client = TestClient(app)
    tenant = _seed_company(client, signed_in, app_db, "alice@alpha.example", "Alpha Traders", "ALPHA-1")
    challan = _create_challan(client, tenant)
    draft = _draft(client, challan["id"])
    draft.pop("challan_updated_at")

    owner = app_db.owner_engine.connect()
    holding = owner.begin()
    owner.execute(text("SELECT id FROM delivery_challans WHERE id = :c FOR UPDATE"), {"c": challan["id"]})
    try:
        with ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(
                lambda: TestClient(app).post(f"/api/delivery-challans/{challan['id']}/convert", json=draft)
            )
            time.sleep(1)
            assert not future.done(), "conversion went straight past a held row lock"
            assert _invoices_for(app_db, challan["id"]) == []
            owner.execute(text("UPDATE delivery_challans SET status = 'cancelled' WHERE id = :c"), {"c": challan["id"]})
            holding.commit()
            response = future.result(timeout=30)
    finally:
        owner.close()

    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "challan_cancelled"
    assert _invoices_for(app_db, challan["id"]) == []


def test_editing_while_converting_cannot_double_count(app_db, signed_in):
    """Both take the challan first: either the edit lands and the stale draft is refused, or the edit is."""
    client = TestClient(app)
    tenant = _seed_company(client, signed_in, app_db, "alice@alpha.example", "Alpha Traders", "ALPHA-1")
    challan = _create_challan(client, tenant, quantity=10)
    draft = _draft(client, challan["id"])
    start = threading.Barrier(2)

    def edit():
        thread_client = TestClient(app)
        start.wait()
        return thread_client.put(f"/api/delivery-challans/{challan['id']}", json={
            "ledger_id": tenant["ledger"],
            "items": [{"product_id": tenant["product"], "quantity": 20, "unit_price": 100}],
        })

    def convert():
        thread_client = TestClient(app)
        start.wait()
        return thread_client.post(f"/api/delivery-challans/{challan['id']}/convert", json=draft)

    with ThreadPoolExecutor(max_workers=2) as pool:
        edited, converted = [future.result(timeout=30) for future in [pool.submit(edit), pool.submit(convert)]]

    assert sorted([edited.status_code, converted.status_code]) in ([200, 400], [200, 409]), (edited.text, converted.text)
    if edited.status_code == 200:
        assert converted.json()["detail"]["code"] == "challan_changed"
        assert _status_of(app_db, challan["id"]) == "open"
        assert _stock(app_db, tenant["product"]) == OPENING - 20
    else:
        assert edited.json()["detail"] == "An invoiced delivery challan cannot be edited"
        assert _status_of(app_db, challan["id"]) == "invoiced"
        assert _stock(app_db, tenant["product"]) == OPENING - 10
    assert _stock(app_db, tenant["product"]) == _expected_stock(app_db, tenant["company"], tenant["product"])


def test_cancelling_the_invoice_while_a_conversion_runs_cannot_deadlock(app_db, signed_in):
    """Both orders take the challan first, so one simply waits for the other."""
    client = TestClient(app)
    tenant = _seed_company(client, signed_in, app_db, "alice@alpha.example", "Alpha Traders", "ALPHA-1")
    challan = _create_challan(client, tenant)
    draft = _draft(client, challan["id"])
    invoice = iso._ok(client.post(f"/api/delivery-challans/{challan['id']}/convert", json=draft))
    draft.pop("challan_updated_at")

    start = threading.Barrier(2)

    def cancel():
        thread_client = TestClient(app)
        start.wait()
        return thread_client.delete(f"/api/invoices/{invoice['id']}")

    def convert():
        thread_client = TestClient(app)
        start.wait()
        return thread_client.post(f"/api/delivery-challans/{challan['id']}/convert", json=draft)

    with ThreadPoolExecutor(max_workers=2) as pool:
        cancelled, converted = [future.result(timeout=30) for future in [pool.submit(cancel), pool.submit(convert)]]

    assert cancelled.status_code == 200, cancelled.text
    assert converted.status_code in (200, 409), converted.text
    expected = ["cancelled", "active"] if converted.status_code == 200 else ["cancelled"]
    assert _invoices_for(app_db, challan["id"]) == expected
    assert _status_of(app_db, challan["id"]) == ("invoiced" if converted.status_code == 200 else "open")
    assert _stock(app_db, tenant["product"]) == _expected_stock(app_db, tenant["company"], tenant["product"])


def test_the_partial_index_holds_when_the_lock_is_bypassed(app_db, signed_in):
    client = TestClient(app)
    tenant = _seed_company(client, signed_in, app_db, "alice@alpha.example", "Alpha Traders", "ALPHA-1")
    challan = _create_challan(client, tenant)
    first = iso._ok(client.post(f"/api/delivery-challans/{challan['id']}/convert", json=_draft(client, challan["id"])))
    other = iso._create_invoice(client, tenant["ledger"], tenant["product"])

    with app_db.OwnerSession() as owner:
        row = owner.query(Invoice).filter(Invoice.id == other["id"]).one()
        row.source_challan_id = challan["id"]
        with pytest.raises(IntegrityError) as caught:
            owner.commit()
        assert "ux_invoices_active_source_challan" in str(caught.value)
        owner.rollback()

    # Cancelled ones fall out of it, so a re-conversion is allowed.
    iso._ok(client.delete(f"/api/invoices/{first['id']}"))
    second = iso._ok(client.post(f"/api/delivery-challans/{challan['id']}/convert", json=_draft(client, challan["id"])))
    assert _invoices_for(app_db, challan["id"]) == ["cancelled", "active"]
    restored = client.post(f"/api/invoices/{first['id']}/restore")
    assert restored.status_code == 409
    assert restored.json()["detail"]["code"] == "challan_reinvoiced"
    assert second["invoice_number"] in restored.text


def test_a_lost_race_on_the_index_is_a_409_not_a_500(app_db, signed_in, monkeypatch):
    """Skip the status check, as an unforeseen path would, and the index still decides."""
    from src.services import delivery_challan as challan_service

    client = TestClient(app)
    tenant = _seed_company(client, signed_in, app_db, "alice@alpha.example", "Alpha Traders", "ALPHA-1")
    challan = _create_challan(client, tenant)
    draft = _draft(client, challan["id"])
    first = iso._ok(client.post(f"/api/delivery-challans/{challan['id']}/convert", json=draft))
    stock_after = _stock(app_db, tenant["product"])

    monkeypatch.setattr(challan_service, "_require_convertible", lambda db, challan: None)
    draft.pop("challan_updated_at")
    response = client.post(f"/api/delivery-challans/{challan['id']}/convert", json=draft)
    assert response.status_code == 409, response.text
    assert response.json()["detail"]["code"] == "challan_already_invoiced"
    assert response.json()["detail"]["invoice_id"] == first["id"]
    assert _invoices_for(app_db, challan["id"]) == ["active"]
    assert _stock(app_db, tenant["product"]) == stock_after


def test_a_challan_number_race_is_settled_by_the_unique_constraint(app_db, signed_in):
    """Two typed copies of one number at once: one saves, the other is refused, never both."""
    client = TestClient(app)
    tenant = _seed_company(client, signed_in, app_db, "alice@alpha.example", "Alpha Traders", "ALPHA-1")
    start = threading.Barrier(2)

    def create():
        thread_client = TestClient(app)
        start.wait()
        return thread_client.post("/api/delivery-challans/", json={
            "ledger_id": tenant["ledger"],
            "challan_number": "JW-1",
            "items": [{"product_id": tenant["product"], "quantity": 1, "unit_price": 100}],
        })

    with ThreadPoolExecutor(max_workers=2) as pool:
        responses = [future.result(timeout=30) for future in [pool.submit(create), pool.submit(create)]]
    codes = sorted(response.status_code for response in responses)
    assert codes == [200, 409], [response.text for response in responses]
    refused = next(response for response in responses if response.status_code == 409)
    assert refused.json()["detail"]["code"] == "challan_number_taken"
    with app_db.owner_engine.connect() as conn:
        assert conn.execute(text("SELECT count(*) FROM delivery_challans")).scalar() == 1
    assert _stock(app_db, tenant["product"]) == OPENING - 1


# ---------------------------------------------------------------------------
# Row-level security
# ---------------------------------------------------------------------------

@pytest.fixture
def two_tenant_challans(clean_rls_db, signed_in, monkeypatch):
    monkeypatch.setattr(settings, "DEPLOYMENT_MODE", "shared_hosting")
    monkeypatch.setattr(settings, "PLATFORM_ADMIN_EMAILS", "")
    monkeypatch.setattr(settings, "MAX_COMPANIES_PER_USER", 3)
    db = clean_rls_db

    def _get_db():
        session = db.AppSession()
        try:
            yield session
        finally:
            session.close()

    previous = app.dependency_overrides.get(get_db)
    app.dependency_overrides[get_db] = _get_db
    try:
        client = TestClient(app)
        a = _seed_company(client, signed_in, db, "alice@alpha.example", "Alpha Traders", "ALPHA-1")
        a["challan"] = _create_challan(client, a)
        b = _seed_company(client, signed_in, db, "bob@beta.example", "Beta Stores", "BETA-1")
        b["challan"] = _create_challan(client, b)
        yield db, a, b
    finally:
        app.dependency_overrides[get_db] = previous


def test_for_update_cannot_see_the_other_tenants_challan(two_tenant_challans):
    db, a, b = two_tenant_challans
    session = db.AppSession()
    try:
        set_tenant_context(session, company_id=b["company"])
        row = (
            session.query(DeliveryChallan)
            .filter(DeliveryChallan.id == a["challan"]["id"])
            .with_for_update()
            .first()
        )
        assert row is None
        assert session.execute(
            text("SELECT count(*) FROM delivery_challan_items WHERE challan_id = :c"), {"c": a["challan"]["id"]}
        ).scalar() == 0
    finally:
        session.rollback()
        session.close()


def test_the_whole_path_as_the_restricted_role(two_tenant_challans, signed_in):
    db, a, b = two_tenant_challans
    client = TestClient(app)
    signed_in(a["email"])
    invoice = iso._ok(client.post(
        f"/api/delivery-challans/{a['challan']['id']}/convert", json=_draft(client, a["challan"]["id"])
    ))
    assert invoice["source_challan_number"] == a["challan"]["challan_number"]
    assert _status_of(db, a["challan"]["id"]) == "invoiced"

    signed_in(b["email"])
    assert client.get(f"/api/delivery-challans/{a['challan']['id']}").status_code == 404
    assert client.delete(f"/api/invoices/{invoice['id']}").status_code == 404

    signed_in(a["email"])
    iso._ok(client.delete(f"/api/invoices/{invoice['id']}"))
    assert _status_of(db, a["challan"]["id"]) == "open"
    iso._ok(client.post(f"/api/invoices/{invoice['id']}/restore"))
    assert _status_of(db, a["challan"]["id"]) == "invoiced"
    assert client.get(f"/api/delivery-challans/{a['challan']['id']}/pdf").status_code == 200
    for tenant in (a, b):
        assert _stock(db, tenant["product"]) == _expected_stock(db, tenant["company"], tenant["product"])
