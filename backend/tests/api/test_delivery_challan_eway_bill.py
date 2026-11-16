"""The delivery challan e-way bill routes (precheck and generate)."""

import json
from datetime import date

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app_main import app
from src.api.deps import get_active_company, get_current_user
from src.db.base import Base
from src.db.session import get_db
from src.models.buyer import Buyer
from src.models.company import CompanyProfile
from src.models.delivery_challan import DeliveryChallan, DeliveryChallanItem
from src.models.eway_bill import EwayBillTransporter
from src.models.product import Product
from src.models.user import User, UserRole

engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
TestingSessionLocal = sessionmaker(bind=engine)

SELLER_GST = "29AABCT1234Q1Z5"
BUYER_GST = "27BBBCD5678R2Z9"


@pytest.fixture(autouse=True)
def setup_db():
    Base.metadata.create_all(bind=engine)
    yield
    Base.metadata.drop_all(bind=engine)


@pytest.fixture
def db():
    session = TestingSessionLocal()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture
def company(db):
    c = CompanyProfile(
        name="API Corp",
        address="123 API Road\nBangalore\n560001",
        gst=SELLER_GST,
        phone_number="9999999999",
        currency_code="INR",
    )
    db.add(c)
    db.flush()
    return c


@pytest.fixture
def role():
    return {"value": UserRole.admin}


@pytest.fixture
def client(db, company, role):
    def override_get_db():
        yield db

    def override_get_current_user():
        return User(id=1, email="test@example.com", role=role["value"])

    saved = dict(app.dependency_overrides)
    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_current_user] = override_get_current_user
    app.dependency_overrides[get_active_company] = lambda: company
    yield TestClient(app)
    app.dependency_overrides = saved


@pytest.fixture
def buyer(db, company):
    b = Buyer(
        name="GST Buyer",
        address="456 Buyer Lane\nMumbai\n400001",
        gst=BUYER_GST,
        phone_number="8888888888",
        company_id=company.id,
    )
    db.add(b)
    db.flush()
    return b


@pytest.fixture
def product(db, company):
    p = Product(sku="CH001", name="Challan Product", price=100.0, gst_rate=18.0, unit="Pieces", company_id=company.id)
    db.add(p)
    db.flush()
    return p


def make_challan(db, company, buyer, product, *, purpose="job_work", status="open", number="DC-2026-001"):
    challan = DeliveryChallan(
        company_id=company.id,
        challan_number=number,
        status=status,
        purpose=purpose,
        challan_date=date(2026, 11, 15),
        ledger_id=buyer.id,
        ledger_name=buyer.name,
        ledger_address=buyer.address,
        ledger_gst=buyer.gst,
        company_name=company.name,
        company_address=company.address,
        company_gst=company.gst,
        taxable_amount=1000,
        total_tax_amount=180,
        cgst_amount=0,
        sgst_amount=0,
        igst_amount=180,
        total_amount=1180,
        created_by=1,
    )
    db.add(challan)
    db.flush()
    db.add(DeliveryChallanItem(
        challan_id=challan.id,
        product_id=product.id,
        hsn_sac="85176290",
        quantity=10,
        unit_price=100,
        gst_rate=18,
        taxable_amount=1000,
        tax_amount=180,
        cgst_amount=0,
        sgst_amount=0,
        igst_amount=180,
        line_total=1180,
    ))
    db.flush()
    db.refresh(challan)
    return challan


@pytest.fixture
def challan(db, company, buyer, product):
    return make_challan(db, company, buyer, product)


def form_from_precheck(client, challan_id, **extra):
    data = client.get(f"/api/delivery-challans/{challan_id}/eway-bill/precheck").json()["form_data"]
    data.update({"vehicle_number": "KA01AB1234", "distance_km": 850})
    data.update(extra)
    return data


# ── Precheck ──


def test_precheck(client, challan):
    resp = client.get(f"/api/delivery-challans/{challan.id}/eway-bill/precheck")
    assert resp.status_code == 200
    data = resp.json()
    assert data["valid"] is True
    assert data["document_type"] == "CHL"
    assert data["sub_supply_label"] == "Job Work"
    assert data["form_data"]["sub_supply_type"] == "4"
    assert data["form_data"]["seller_gstin"] == SELLER_GST
    assert data["form_data"]["buyer_gstin"] == BUYER_GST


def test_precheck_on_an_invoiced_challan_is_allowed(client, db, company, buyer, product):
    invoiced = make_challan(db, company, buyer, product, status="invoiced")
    assert client.get(f"/api/delivery-challans/{invoiced.id}/eway-bill/precheck").status_code == 200


def test_precheck_cancelled_is_refused(client, db, company, buyer, product):
    cancelled = make_challan(db, company, buyer, product, status="cancelled")
    resp = client.get(f"/api/delivery-challans/{cancelled.id}/eway-bill/precheck")
    assert resp.status_code == 400
    assert resp.json()["detail"] == "E-Way Bill can't be generated for a cancelled delivery challan."


def test_precheck_404(client):
    resp = client.get("/api/delivery-challans/99999/eway-bill/precheck")
    assert resp.status_code == 404
    assert resp.json()["detail"] == "Delivery challan 99999 not found"


def test_precheck_other_company_is_404(client, db, challan):
    other = CompanyProfile(name="Other", address="x", gst="27AAAAA0000A1Z2", currency_code="INR")
    db.add(other)
    db.flush()
    challan.company_id = other.id
    db.flush()
    assert client.get(f"/api/delivery-challans/{challan.id}/eway-bill/precheck").status_code == 404


def test_precheck_disabled_company_is_400(client, company, challan):
    company.eway_enabled = False
    resp = client.get(f"/api/delivery-challans/{challan.id}/eway-bill/precheck")
    assert resp.status_code == 400
    assert "turned off" in resp.json()["detail"]


def test_precheck_autofills_default_transporter(client, db, company, challan):
    db.add(EwayBillTransporter(
        company_id=company.id,
        transporter_name="Fast Freight",
        transporter_gstin="07TRNSP1234Q1Z5",
        transport_mode="1",
        vehicle_type="R",
        is_default=True,
    ))
    db.flush()
    data = client.get(f"/api/delivery-challans/{challan.id}/eway-bill/precheck").json()
    assert data["form_data"]["transporter_name"] == "Fast Freight"


# ── Generate ──


def test_generate_is_a_challan_file(client, challan):
    resp = client.post(f"/api/delivery-challans/{challan.id}/eway-bill/generate", json=form_from_precheck(client, challan.id))
    assert resp.status_code == 200, resp.text
    assert resp.headers["content-disposition"] == 'attachment; filename="EWB_DC-2026-001.json"'
    bill = json.loads(resp.text)["billLists"][0]
    assert bill["docType"] == "CHL"
    assert bill["subSupplyType"] == 4
    assert bill["docNo"] == "DC-2026-001"
    assert bill["totInvValue"] == 1180.0


def test_generate_ignores_the_client_sub_supply(client, challan):
    form = form_from_precheck(client, challan.id, sub_supply_type="1")
    resp = client.post(f"/api/delivery-challans/{challan.id}/eway-bill/generate", json=form)
    assert resp.status_code == 200, resp.text
    assert json.loads(resp.text)["billLists"][0]["subSupplyType"] == 4


def test_generate_others_carries_the_description(client, db, company, buyer, product):
    c = make_challan(db, company, buyer, product, purpose="supply_on_approval")
    resp = client.post(f"/api/delivery-challans/{c.id}/eway-bill/generate", json=form_from_precheck(client, c.id))
    bill = json.loads(resp.text)["billLists"][0]
    assert bill["subSupplyType"] == 8
    assert bill["subSupplyDesc"] == "Supply on approval"


def test_generate_invoiced_challan_is_allowed(client, db, company, buyer, product):
    c = make_challan(db, company, buyer, product, status="invoiced")
    resp = client.post(f"/api/delivery-challans/{c.id}/eway-bill/generate", json=form_from_precheck(client, c.id))
    assert resp.status_code == 200


def test_generate_cancelled_is_refused(client, db, company, buyer, product):
    c = make_challan(db, company, buyer, product, status="cancelled")
    resp = client.post(f"/api/delivery-challans/{c.id}/eway-bill/generate", json={})
    assert resp.status_code == 400


def test_generate_404(client):
    assert client.post("/api/delivery-challans/99999/eway-bill/generate", json={}).status_code == 404


def test_generate_validation_errors_are_422(client, challan):
    form = form_from_precheck(client, challan.id, vehicle_number="", transporter_gstin="")
    resp = client.post(f"/api/delivery-challans/{challan.id}/eway-bill/generate", json=form)
    assert resp.status_code == 422
    assert any(e["field"] == "vehicle_number" for e in resp.json()["detail"]["errors"])


def test_generate_reports_a_bad_challan_number(client, db, company, buyer, product):
    c = make_challan(db, company, buyer, product, number="DC-2026-0000000000001")
    resp = client.post(f"/api/delivery-challans/{c.id}/eway-bill/generate", json=form_from_precheck(client, c.id))
    assert resp.status_code == 422
    assert any(e["field"] == "challan_number" for e in resp.json()["detail"]["errors"])


def test_generate_saves_transporter_for_an_admin(client, db, challan):
    form = form_from_precheck(client, challan.id, transporter_name="Saved Freight", save_transporter=True)
    assert client.post(f"/api/delivery-challans/{challan.id}/eway-bill/generate", json=form).status_code == 200
    assert db.query(EwayBillTransporter).filter_by(transporter_name="Saved Freight").count() == 1


def test_generate_refuses_saving_a_transporter_without_permission(client, db, challan, role):
    role["value"] = UserRole.staff
    form = form_from_precheck(client, challan.id, transporter_name="Nope Freight", save_transporter=True)
    resp = client.post(f"/api/delivery-challans/{challan.id}/eway-bill/generate", json=form)
    assert resp.status_code == 403
    assert db.query(EwayBillTransporter).filter_by(transporter_name="Nope Freight").count() == 0


def test_staff_can_still_generate_without_saving_a_transporter(client, challan, role):
    role["value"] = UserRole.staff
    resp = client.post(f"/api/delivery-challans/{challan.id}/eway-bill/generate", json=form_from_precheck(client, challan.id))
    assert resp.status_code == 200


def test_generate_tracks_the_analytics_event(client, challan, monkeypatch):
    from src.api.routes import eway_bill

    events = []
    monkeypatch.setattr(eway_bill, "track", lambda event, distinct_id, props=None: events.append((event, props)))
    resp = client.post(f"/api/delivery-challans/{challan.id}/eway-bill/generate", json=form_from_precheck(client, challan.id))
    assert resp.status_code == 200
    assert events == [(
        "delivery_challan_eway_bill_generated",
        {"challan_id": challan.id, "purpose": "job_work", "sub_supply_type": "4"},
    )]


def test_generate_does_not_track_when_validation_fails(client, challan, monkeypatch):
    from src.api.routes import eway_bill

    events = []
    monkeypatch.setattr(eway_bill, "track", lambda *a, **k: events.append(a))
    form = form_from_precheck(client, challan.id, vehicle_number="")
    assert client.post(f"/api/delivery-challans/{challan.id}/eway-bill/generate", json=form).status_code == 422
    assert events == []
