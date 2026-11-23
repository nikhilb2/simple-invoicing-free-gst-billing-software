"""Cancelled bills cannot be sent as live invoices and retain their timestamp."""

from datetime import datetime

from src.models.share_link import ShareLink
from test_share_links import _company, _create_link, _headers, _invoice, _ledger


def test_cancelled_invoice_cannot_be_shared_or_emailed(client, db_session, monkeypatch):
    company = _company(db_session, "Cancelled invoice company")
    invoice = _invoice(db_session, company, _ledger(db_session, company))
    invoice.status = "cancelled"
    db_session.commit()

    def must_not_send(*args, **kwargs):
        raise AssertionError("A cancelled invoice must not reach the mail service")

    monkeypatch.setattr("src.api.routes.email.send_email", must_not_send)
    response = _create_link(client, company, "invoice", invoice.id)
    assert response.status_code == 400
    assert response.json()["detail"] == "Cancelled invoices cannot be shared"
    assert db_session.query(ShareLink).count() == 0
    response = client.post(
        f"/api/email/invoice/{invoice.id}",
        json={"to": "recipient@example.com"},
        headers=_headers(company),
    )
    assert response.status_code == 400
    assert response.json()["detail"] == "Cancelled invoices cannot be emailed"


def test_cancel_records_utc_time_and_restore_clears_it(client, db_session):
    company = _company(db_session, "Cancellation time company")
    invoice = _invoice(db_session, company, _ledger(db_session, company))
    before = datetime.utcnow()
    response = client.delete(f"/api/invoices/{invoice.id}", headers=_headers(company))
    assert response.status_code == 200, response.text
    recorded = datetime.fromisoformat(response.json()["cancelled_at"])
    assert before <= recorded <= datetime.utcnow()
    db_session.refresh(invoice)
    assert invoice.cancelled_at == recorded
    response = client.post(f"/api/invoices/{invoice.id}/restore", headers=_headers(company))
    assert response.status_code == 200, response.text
    assert response.json()["cancelled_at"] is None
    db_session.refresh(invoice)
    assert invoice.cancelled_at is None
