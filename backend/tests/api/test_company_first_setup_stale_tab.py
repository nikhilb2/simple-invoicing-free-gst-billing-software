"""The first-run setup screen open in two tabs makes one company, not two (#1151)."""
from datetime import datetime

import pytest

from src.core.config import settings
from src.models.company import CompanyProfile
from src.models.global_settings import GlobalSettings
from src.models.user import User
from tests.api.test_company_switching import (
    _ensure_admin_user,
    _restore_user_override,
    _with_persistent_user_override,
)

FIRST_SETUP = {"first_setup": "true"}


def _prepare(db_session, monkeypatch, mode, max_companies=10):
    monkeypatch.setattr(settings, "DEPLOYMENT_MODE", mode)
    monkeypatch.setattr(settings, "MAX_COMPANIES_PER_USER", max_companies)
    row = db_session.query(GlobalSettings).filter(GlobalSettings.id == 1).first()
    if row is None:
        db_session.add(GlobalSettings(id=1, max_companies=max_companies))
    else:
        row.max_companies = max_companies
    user = _ensure_admin_user(db_session)
    user.email_verified_at = datetime(2026, 11, 28)
    db_session.commit()
    return user


@pytest.mark.parametrize("mode", ["single_tenant", "shared_hosting"])
def test_start_billing_in_a_second_tab_returns_the_company_already_made(client, db_session, monkeypatch, mode):
    _prepare(db_session, monkeypatch, mode)
    old_override = _with_persistent_user_override()
    try:
        tab_a = client.post("/api/company/companies", params=FIRST_SETUP, json={"name": "Tab A Traders"})
        assert tab_a.status_code == 200, tab_a.text

        # Tab B still shows the setup form and sends its own name.
        tab_b = client.post("/api/company/companies", params=FIRST_SETUP, json={"name": "Tab B Traders"})
        assert tab_b.status_code == 200, tab_b.text
        assert tab_b.json()["id"] == tab_a.json()["id"]
        assert tab_b.json()["name"] == "Tab A Traders"

        db_session.expire_all()
        assert db_session.query(CompanyProfile).count() == 1
        user = db_session.query(User).filter(User.email == "test@example.com").one()
        assert user.active_company_id == tab_a.json()["id"]
    finally:
        _restore_user_override(old_override)


@pytest.mark.parametrize("mode", ["single_tenant", "shared_hosting"])
def test_add_business_still_creates_another_company(client, db_session, monkeypatch, mode):
    _prepare(db_session, monkeypatch, mode)
    old_override = _with_persistent_user_override()
    try:
        first = client.post("/api/company/companies", params=FIRST_SETUP, json={"name": "First Shop"})
        assert first.status_code == 200, first.text

        # "Add business" in the company switcher (and MCP / API clients) send no flag.
        second = client.post("/api/company/companies", json={"name": "Second Shop"})
        assert second.status_code == 200, second.text
        assert second.json()["id"] != first.json()["id"]

        db_session.expire_all()
        assert db_session.query(CompanyProfile).count() == 2
    finally:
        _restore_user_override(old_override)


@pytest.mark.parametrize("mode", ["single_tenant", "shared_hosting"])
def test_a_stale_tab_at_the_company_limit_gets_the_company_not_limit_reached(client, db_session, monkeypatch, mode):
    _prepare(db_session, monkeypatch, mode, max_companies=1)
    old_override = _with_persistent_user_override()
    try:
        first = client.post("/api/company/companies", params=FIRST_SETUP, json={"name": "Only Shop"})
        assert first.status_code == 200, first.text

        stale = client.post("/api/company/companies", params=FIRST_SETUP, json={"name": "Only Shop"})
        assert stale.status_code == 200, stale.text
        assert stale.json()["id"] == first.json()["id"]

        # Without the flag the limit still applies.
        extra = client.post("/api/company/companies", json={"name": "Extra Shop"})
        assert extra.status_code == 403, extra.text
    finally:
        _restore_user_override(old_override)


def test_shared_hosting_first_setup_ignores_other_peoples_companies(client, db_session, monkeypatch):
    """A stranger's company must never be handed back: only the user's own memberships count."""
    _prepare(db_session, monkeypatch, "shared_hosting")
    db_session.add(CompanyProfile(name="Someone Else Pvt Ltd", address="", gst="", phone_number="",
                                  currency_code="INR", email="", website="", bank_name="",
                                  branch_name="", account_name="", account_number="", ifsc_code=""))
    db_session.commit()
    old_override = _with_persistent_user_override()
    try:
        created = client.post("/api/company/companies", params=FIRST_SETUP, json={"name": "My Own Shop"})
        assert created.status_code == 200, created.text
        assert created.json()["name"] == "My Own Shop"

        db_session.expire_all()
        assert db_session.query(CompanyProfile).count() == 2
    finally:
        _restore_user_override(old_override)
