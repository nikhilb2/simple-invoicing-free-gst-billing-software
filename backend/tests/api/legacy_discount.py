"""Invoices as they were saved before #1154: the bill discount taken after GST.

The API only creates documents that take the discount before GST now. Tests that pin
how an old document totals, prints, files and reports make one the way a migrated
database has them: the stored mode set to 'after_tax', then the document saved again,
which keeps the stored mode and works its figures out the old way.
"""

from src.db.session import get_db
from src.models.invoice import Invoice
from src.models.quotation import Quotation


def _set_after_tax(client, model, document_id: int) -> None:
    sessions = client.app.dependency_overrides[get_db]()
    db = next(sessions)
    try:
        db.query(model).filter(model.id == document_id).update({model.discount_mode: "after_tax"})
        db.commit()
    finally:
        sessions.close()


def save_invoice_after_gst(client, invoice: dict, payload: dict) -> dict:
    """Turn an invoice the API just created from ``payload`` into an old after-GST one."""
    _set_after_tax(client, Invoice, invoice["id"])
    response = client.put(f"/api/invoices/{invoice['id']}", json=payload)
    assert response.status_code == 200, response.text
    saved = response.json()
    assert saved["discount_mode"] == "after_tax"
    return saved


def create_invoice_after_gst(client, payload: dict) -> dict:
    """POST ``payload`` with any bill discount left off, then save it with the discount after GST.

    Created without the discount first: a flat discount larger than the subtotal, which
    an old invoice could carry (it was capped at the total), is refused before GST.
    """
    plain = {key: value for key, value in payload.items() if key not in ("discount_type", "discount_value")}
    response = client.post("/api/invoices/", json=plain)
    assert response.status_code == 200, response.text
    return save_invoice_after_gst(client, response.json(), payload)


def create_quotation_after_gst(client, payload: dict) -> dict:
    """The same for a quotation: created plain, then saved with its discount after GST."""
    plain = {key: value for key, value in payload.items() if key not in ("discount_type", "discount_value", "document_type")}
    plain["document_type"] = payload.get("document_type", "quotation")
    response = client.post("/api/quotations/", json=plain)
    assert response.status_code in (200, 201), response.text
    quotation = response.json()
    _set_after_tax(client, Quotation, quotation["id"])
    update = {key: value for key, value in payload.items() if key != "document_type"}
    response = client.put(f"/api/quotations/{quotation['id']}", json=update)
    assert response.status_code == 200, response.text
    saved = response.json()
    assert saved["discount_mode"] == "after_tax"
    return saved
