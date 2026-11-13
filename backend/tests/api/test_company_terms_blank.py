"""Blank Terms and Conditions content must be rejected (#814)."""

from fastapi import Depends
from sqlalchemy.orm import Session

from app_main import app
from src.api.deps import get_current_user
from src.db.session import get_db
from src.models.user import User, UserRole


def _company_payload(name: str, gst: str = "27ABCDE1234F1Z0"):
    return {
        "name": name,
        "address": "",
        "gst": gst,
        "phone_number": "",
        "currency_code": "USD",
        "email": "",
        "website": "",
        "bank_name": "",
        "branch_name": "",
        "account_name": "",
        "account_number": "",
        "ifsc_code": "",
    }


def _ensure_admin_user(db: Session) -> User:
    user = db.query(User).filter(User.email == "test@example.com").first()
    if user:
        user.role = UserRole.admin
        db.commit()
        db.refresh(user)
        return user

    user = User(
        email="test@example.com",
        full_name="Test Admin",
        hashed_password="test-hash",
        role=UserRole.admin,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def _override_persistent_current_user(db: Session = Depends(get_db)) -> User:
    return _ensure_admin_user(db)


def _with_persistent_user_override():
    old_override = app.dependency_overrides.get(get_current_user)
    app.dependency_overrides[get_current_user] = _override_persistent_current_user
    return old_override


def _restore_user_override(old_override):
    if old_override is None:
        app.dependency_overrides.pop(get_current_user, None)
        return
    app.dependency_overrides[get_current_user] = old_override


def _create_company(client, name: str, gst: str = "27ABCDE1234F1Z0") -> int:
    response = client.post("/api/company/companies", json=_company_payload(name, gst))
    assert response.status_code == 200, response.text
    return response.json()["id"]


class TestBlankCompanyTerms:
    def test_create_blank_term_returns_422(self, client, db_session):
        old_override = _with_persistent_user_override()
        try:
            _create_company(client, "Terms Blank Create Co")
            for content in ("", "   ", "\t"):
                resp = client.post("/api/company/terms", json={"content": content})
                assert resp.status_code == 422, resp.text
            assert client.get("/api/company/terms").json() == []
        finally:
            _restore_user_override(old_override)

    def test_update_blank_term_returns_422(self, client, db_session):
        old_override = _with_persistent_user_override()
        try:
            _create_company(client, "Terms Blank Update Co")
            created = client.post("/api/company/terms", json={"content": "Keep me"}).json()
            term_id = created["id"]
            for content in ("", "   "):
                resp = client.put(f"/api/company/terms/{term_id}", json={"content": content})
                assert resp.status_code == 422, resp.text
            still = client.get("/api/company/terms").json()
            assert len(still) == 1
            assert still[0]["content"] == "Keep me"
        finally:
            _restore_user_override(old_override)

    def test_create_term_strips_whitespace(self, client, db_session):
        old_override = _with_persistent_user_override()
        try:
            _create_company(client, "Terms Strip Co")
            resp = client.post(
                "/api/company/terms",
                json={"content": "  Payment due in 15 days  "},
            )
            assert resp.status_code == 200, resp.text
            assert resp.json()["content"] == "Payment due in 15 days"
        finally:
            _restore_user_override(old_override)
