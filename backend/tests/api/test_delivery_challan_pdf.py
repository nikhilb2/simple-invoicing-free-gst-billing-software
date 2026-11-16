"""GET /api/delivery-challans/{id}/pdf: the route is stream A's, the rendering is here."""

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
from src.models.product import Product
from src.models.user import User, UserRole
from src.services.delivery_challan_pdf import build_delivery_challan_html, render_delivery_challan_pdf

engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
TestingSessionLocal = sessionmaker(bind=engine)


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
    c = CompanyProfile(name="PDF Corp", address="1 Road\nPune", gst="27AAAAA0000A1Z2", currency_code="INR", show_sku_on_pdf=False)
    db.add(c)
    db.flush()
    return c


@pytest.fixture
def client(db, company):
    def override_get_db():
        yield db

    saved = dict(app.dependency_overrides)
    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_current_user] = lambda: User(id=1, email="t@example.com", role=UserRole.admin)
    app.dependency_overrides[get_active_company] = lambda: company
    yield TestClient(app)
    app.dependency_overrides = saved


@pytest.fixture
def challan(db, company):
    buyer = Buyer(name="Buyer", address="2 Lane", gst="29AADCB2230M1ZP", phone_number="9000000000", company_id=company.id)
    product = Product(sku="PDF-1", name="Pdf Widget", price=100.0, gst_rate=18.0, unit="Pieces", company_id=company.id)
    db.add_all([buyer, product])
    db.flush()
    c = DeliveryChallan(
        company_id=company.id,
        challan_number="DC/2026/001",
        status="open",
        purpose="exhibition",
        challan_date=date(2026, 11, 15),
        ledger_id=buyer.id,
        ledger_name="Buyer",
        ledger_address="2 Lane",
        ledger_gst=buyer.gst,
        company_name=company.name,
        company_address=company.address,
        company_gst=company.gst,
        company_currency_code="INR",
        taxable_amount=500,
        total_tax_amount=90,
        total_amount=590,
        created_by=1,
    )
    db.add(c)
    db.flush()
    db.add(DeliveryChallanItem(
        challan_id=c.id, product_id=product.id, hsn_sac="84713010", quantity=5, unit_price=100,
        gst_rate=18, taxable_amount=500, tax_amount=90, igst_amount=90, line_total=590,
    ))
    db.flush()
    db.refresh(c)
    return c


def test_pdf_route_returns_a_pdf_with_a_safe_filename(client, challan):
    resp = client.get(f"/api/delivery-challans/{challan.id}/pdf")
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("application/pdf")
    assert resp.content.startswith(b"%PDF")
    assert "delivery_challan_DC_2026_001.pdf" in resp.headers["content-disposition"]


@pytest.mark.parametrize("copies", [1, 2, 3])
def test_pdf_route_takes_one_to_three_copies(client, challan, copies):
    assert client.get(f"/api/delivery-challans/{challan.id}/pdf?copies={copies}").status_code == 200


@pytest.mark.parametrize("copies", [0, 4])
def test_pdf_route_refuses_other_copy_counts(client, challan, copies):
    assert client.get(f"/api/delivery-challans/{challan.id}/pdf?copies={copies}").status_code == 422


def test_pdf_route_404(client):
    assert client.get("/api/delivery-challans/99999/pdf").status_code == 404


def test_html_has_the_challan_and_the_company_sku_setting(db, company, challan):
    html = build_delivery_challan_html(db, company.id, challan.id, copies=3)
    assert "Delivery Challan" in html and "DC/2026/001" in html
    assert "Pdf Widget" in html
    assert "PDF-1" not in html  # show_sku_on_pdf is off for this company
    for label in ("Original for consignee", "Duplicate for transporter", "Triplicate for consignor"):
        assert label in html


def test_another_companys_challan_is_404(db, challan):
    from fastapi import HTTPException

    with pytest.raises(HTTPException) as excinfo:
        build_delivery_challan_html(db, challan.company_id + 1, challan.id)
    assert excinfo.value.status_code == 404


def test_render_returns_pdf_bytes(db, company, challan):
    assert render_delivery_challan_pdf(db, company.id, challan.id).getvalue().startswith(b"%PDF")
