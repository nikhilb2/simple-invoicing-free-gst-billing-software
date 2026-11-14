"""
API-level tests for E-Way Bill routes.
"""

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from fastapi.testclient import TestClient
from app_main import app
from src.api.deps import get_current_user, get_active_company
from src.db.base import Base
from src.db.session import get_db
from src.models.buyer import Buyer
from src.models.company import CompanyProfile
from src.models.eway_bill import EwayBillTransporter
from src.models.invoice import Invoice, InvoiceItem
from src.models.product import Product
from src.models.user import User, UserRole


engine = create_engine(
    "sqlite://",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
TestingSessionLocal = sessionmaker(bind=engine)


@pytest.fixture(autouse=True)
def setup_db():
    Base.metadata.create_all(bind=engine)
    yield
    Base.metadata.drop_all(bind=engine)


@pytest.fixture
def db():
    db = TestingSessionLocal()
    try:
        yield db
    finally:
        db.close()


@pytest.fixture
def company(db):
    c = CompanyProfile(
        name="API Corp",
        address="123 API Road\nBangalore\n560001",
        gst="29AABCT1234Q1Z5",
        phone_number="9999999999",
        currency_code="INR",
    )
    db.add(c)
    db.flush()
    return c


@pytest.fixture
def client(db, company):
    def override_get_db():
        try:
            yield db
        finally:
            pass

    def override_get_current_user():
        return User(
            id=1,
            email="test@example.com",
            role=UserRole.admin,
        )

    def override_get_active_company():
        return company

    saved_overrides = dict(app.dependency_overrides)
    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_current_user] = override_get_current_user
    app.dependency_overrides[get_active_company] = override_get_active_company

    yield TestClient(app)

    app.dependency_overrides = saved_overrides


@pytest.fixture
def buyer_with_gst(db, company):
    b = Buyer(
        name="GST Buyer",
        address="456 Buyer Lane\nMumbai\n400001",
        gst="27BBBCD5678R2Z9",
        phone_number="8888888888",
        company_id=company.id,
    )
    db.add(b)
    db.flush()
    return b


@pytest.fixture
def product(db, company):
    p = Product(
        sku="EWB001",
        name="E-Way Product",
        price=100.0,
        gst_rate=18.0,
        unit="Pieces",
        description="Test product",
        company_id=company.id,
    )
    db.add(p)
    db.flush()
    return p


@pytest.fixture
def invoice(db, company, buyer_with_gst, product):
    inv = Invoice(
        invoice_number="EWB-API-001",
        company_id=company.id,
        ledger_id=buyer_with_gst.id,
        ledger_name=buyer_with_gst.name,
        ledger_address=buyer_with_gst.address,
        ledger_gst=buyer_with_gst.gst,
        voucher_type="sales",
        status="active",
        created_by=1,
        taxable_amount=1000.00,
        cgst_amount=0.00,
        sgst_amount=0.00,
        igst_amount=180.00,
        total_amount=1180.00,
        company_name=company.name,
        company_address=company.address,
        company_gst=company.gst,
    )
    db.add(inv)
    db.flush()

    item = InvoiceItem(
        invoice_id=inv.id,
        product_id=product.id,
        hsn_sac="85176290",
        quantity=10.0,
        unit_price=100.00,
        gst_rate=18.0,
        taxable_amount=1000.00,
        tax_amount=180.00,
        cgst_amount=0.00,
        sgst_amount=0.00,
        igst_amount=180.00,
        line_total=1180.00,
    )
    db.add(item)
    db.flush()

    return inv
