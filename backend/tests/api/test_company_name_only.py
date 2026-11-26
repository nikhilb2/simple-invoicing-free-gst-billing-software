"""The first business can defer its address without preventing an invoice or PDF."""
from datetime import datetime

import pytest

from src.core.config import settings
from src.services.gst_tax_service import india_today
from tests.api.test_company_switching import (
    _ensure_admin_user,
    _headers,
    _restore_user_override,
    _with_persistent_user_override,
)


@pytest.mark.parametrize("mode", ["single_tenant", "shared_hosting"])
def test_name_only_company_can_issue_an_invoice_and_render_every_paper(client, db_session, monkeypatch, mode):
    monkeypatch.setattr(settings, "DEPLOYMENT_MODE", mode)
    user = _ensure_admin_user(db_session)
    user.email_verified_at = datetime(2026, 11, 23)
    db_session.commit()
    old_override = _with_persistent_user_override()
    try:
        created = client.post("/api/company/companies", json={"name": "Name only shop"})
        assert created.status_code == 200, created.text
        company = created.json()
        assert company["address"] == ""
        assert company["gst"] == ""
        headers = _headers(company["id"])
        assert client.get("/api/company/", headers=headers).json()["address"] == ""

        product = client.post("/api/products/", headers=headers, json={
            "sku": "SERVICE", "name": "Repair", "price": 100, "gst_rate": 0, "maintain_inventory": False,
        })
        buyer = client.post("/api/ledgers/", headers=headers, json={"name": "First customer"})
        assert product.status_code == buyer.status_code == 200
        invoice = client.post("/api/invoices/", headers=headers, json={
            "ledger_id": buyer.json()["id"], "invoice_date": india_today().isoformat(),
            "items": [{"product_id": product.json()["id"], "quantity": 1, "unit_price": 100, "gst_rate": 0}],
        })
        assert invoice.status_code == 200, invoice.text
        assert invoice.json()["company_name"] == "Name only shop"
        assert invoice.json()["company_address"] in ("", None)
        for paper in ("a4", "a5", "thermal80", "thermal58"):
            pdf = client.get(f"/api/invoices/{invoice.json()['id']}/pdf", headers=headers, params={"paper": paper})
            assert pdf.status_code == 200, pdf.text[:500]
            assert pdf.headers["content-type"].startswith("application/pdf")
            assert pdf.content.startswith(b"%PDF-")

        # Missing company details produce editable precheck data and structured
        # validation feedback, rather than a server error or incomplete JSON.
        eway_path = f"/api/invoices/{invoice.json()['id']}/eway-bill"
        precheck = client.get(f"{eway_path}/precheck", headers=headers)
        assert precheck.status_code == 200, precheck.text
        precheck_data = precheck.json()
        assert precheck_data["valid"] is False
        assert precheck_data["form_data"]["seller_address_1"] == ""
        assert precheck_data["form_data"]["seller_state_code"] == ""
        assert "seller_pincode" in {field["field"] for field in precheck_data["missing_fields"]}
        generated = client.post(f"{eway_path}/generate", headers=headers, json=precheck_data["form_data"])
        assert generated.status_code == 422, generated.text
        assert "seller_pincode" in {field["field"] for field in generated.json()["detail"]["errors"]}
    finally:
        _restore_user_override(old_override)


def test_update_without_address_keeps_the_saved_address(client, db_session):
    """A partial PUT (e.g. an AI assistant changing only the phone) must not blank the address."""
    user = _ensure_admin_user(db_session)
    user.email_verified_at = datetime(2026, 11, 23)
    db_session.commit()
    old_override = _with_persistent_user_override()
    try:
        created = client.post("/api/company/companies", json={"name": "Address shop", "address": "12 MG Road"})
        assert created.status_code == 200, created.text
        headers = _headers(created.json()["id"])

        updated = client.put("/api/company/", headers=headers, json={"name": "Address shop", "phone_number": "9999999999"})
        assert updated.status_code == 200, updated.text
        assert updated.json()["address"] == "12 MG Road"
        assert updated.json()["phone_number"] == "9999999999"
        assert client.get("/api/company/", headers=headers).json()["address"] == "12 MG Road"

        cleared = client.put("/api/company/", headers=headers, json={"name": "Address shop", "address": ""})
        assert cleared.status_code == 200, cleared.text
        assert cleared.json()["address"] == ""
        assert client.get("/api/company/", headers=headers).json()["address"] == ""
    finally:
        _restore_user_override(old_override)
