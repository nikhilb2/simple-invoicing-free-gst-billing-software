"""Blank e-way transporter names must be rejected (Related to #814)."""

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from fastapi.testclient import TestClient

from app_main import app
from src.api.deps import get_current_user, get_active_company
from src.db.base import Base
from src.db.session import get_db
from src.models.company import CompanyProfile
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
        return User(id=1, email="test@example.com", role=UserRole.admin)

    def override_get_active_company():
        return company

    saved = dict(app.dependency_overrides)
    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_current_user] = override_get_current_user
    app.dependency_overrides[get_active_company] = override_get_active_company
    yield TestClient(app)
    app.dependency_overrides = saved


def test_transporter_name_rejects_blank_or_whitespace(client):
    for content in ("", "   ", "\t"):
        resp = client.post("/api/eway-bill/transporters", json={"transporter_name": content})
        assert resp.status_code == 422, resp.text
    assert client.get("/api/eway-bill/transporters").json() == []

    created = client.post(
        "/api/eway-bill/transporters",
        json={"transporter_name": "  Keep Me  "},
    )
    assert created.status_code == 200, created.text
    assert created.json()["transporter_name"] == "Keep Me"
    transporter_id = created.json()["id"]

    for content in ("", "   "):
        resp = client.put(
            f"/api/eway-bill/transporters/{transporter_id}",
            json={"transporter_name": content},
        )
        assert resp.status_code == 422, resp.text
    still = client.get("/api/eway-bill/transporters").json()
    assert len(still) == 1
    assert still[0]["transporter_name"] == "Keep Me"
