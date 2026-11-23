"""Only a ledger's name is required; phone and address are optional (#955).

A shop billing a walk-in customer often has neither, and the "Add a customer"
dialog on the invoice form could not be saved without them. The columns stay
NOT NULL, so "none" is stored as "", and everything that prints a party's
address or phone has to cope with that.
"""
from datetime import date

from src.models.buyer import Buyer as Ledger
from src.models.company import CompanyProfile
from src.models.invoice import Invoice
from src.services.pdf_templates.invoice_template import _build_invoice_html
from src.services.pdf_templates.ledger_template import _build_statement_html
from src.services.pdf_templates.thermal_template import build_thermal_copies, thermal_invoice_doc


def _create(client, **payload):
    return client.post("/api/ledgers/", json=payload)


def test_create_with_only_a_name(client):
    response = _create(client, name="Walk-in customer")
    assert response.status_code == 200, response.text
    created = response.json()
    assert created["name"] == "Walk-in customer"
    assert created["address"] == ""
    assert created["phone_number"] == ""


def test_create_accepts_null_and_blank_phone_and_address(client):
    response = _create(client, name="Null contact", address=None, phone_number=None)
    assert response.status_code == 200, response.text
    assert response.json()["address"] == ""
    assert response.json()["phone_number"] == ""

    response = _create(client, name="Blank contact", address="  \n ", phone_number="  ")
    assert response.status_code == 200, response.text
    assert response.json()["address"] == ""
    assert response.json()["phone_number"] == ""


def test_create_keeps_a_given_phone_and_address_trimmed(client):
    response = _create(client, name="Sharma Traders", address=" 12 MG Road ", phone_number=" +91 98765 43210 ")
    assert response.status_code == 200, response.text
    assert response.json()["address"] == "12 MG Road"
    assert response.json()["phone_number"] == "+91 98765 43210"


def test_name_is_still_required(client):
    missing = _create(client, address="12 MG Road")
    assert missing.status_code == 422, missing.text
    assert missing.json()["detail"][0]["loc"][-1] == "name"

    blank = _create(client, name="   ")
    assert blank.status_code == 422, blank.text
    assert blank.json()["detail"][0]["loc"][-1] == "name"


def test_update_can_clear_phone_and_address(client):
    ledger_id = _create(client, name="Clearable", address="12 MG Road", phone_number="9876543210").json()["id"]

    response = client.put(f"/api/ledgers/{ledger_id}", json={"name": "Clearable", "address": "", "phone_number": None})
    assert response.status_code == 200, response.text
    assert response.json()["address"] == ""
    assert response.json()["phone_number"] == ""


def test_update_that_leaves_them_out_keeps_them(client):
    ledger_id = _create(client, name="Partial", address="12 MG Road", phone_number="9876543210").json()["id"]

    response = client.put(f"/api/ledgers/{ledger_id}", json={"name": "Partial renamed"})
    assert response.status_code == 200, response.text
    assert response.json()["name"] == "Partial renamed"
    assert response.json()["address"] == "12 MG Road"
    assert response.json()["phone_number"] == "9876543210"


def test_update_adds_phone_and_address_later(client):
    ledger_id = _create(client, name="Later").json()["id"]

    response = client.put(
        f"/api/ledgers/{ledger_id}",
        json={"name": "Later", "address": " 4 Station Road ", "phone_number": " 9123456789 "},
    )
    assert response.status_code == 200, response.text
    assert response.json()["address"] == "4 Station Road"
    assert response.json()["phone_number"] == "9123456789"


def test_ledger_search_still_works_with_empty_phone(client):
    _create(client, name="Searchable walk-in")
    response = client.get("/api/ledgers/", params={"search": "walk-in"})
    assert response.status_code == 200, response.text
    assert [item["name"] for item in response.json()["items"]] == ["Searchable walk-in"]


def test_first_invoice_for_a_customer_with_no_phone_or_address(client, db_session):
    ledger = _create(client, name="Walk-in customer").json()
    product = client.post("/api/products/", json={
        "sku": "WALKIN-1", "name": "Tea", "price": 10, "gst_rate": 0, "maintain_inventory": False,
    })
    assert product.status_code == 200, product.text
    created = client.post("/api/invoices/", json={
        "ledger_id": ledger["id"], "invoice_date": date.today().isoformat(),
        "items": [{"product_id": product.json()["id"], "quantity": 1, "unit_price": 10, "gst_rate": 0}],
    })
    assert created.status_code == 200, created.text

    invoice = db_session.get(Invoice, created.json()["id"])
    assert invoice.ledger_address == ""
    assert invoice.ledger_phone == ""

    html = _build_invoice_html(invoice, [])
    bill_to = html.split("Bill to", 1)[1]
    assert "None" not in bill_to
    assert "Phone:" not in bill_to

    thermal, = build_thermal_copies([thermal_invoice_doc(invoice, [])], "thermal80")
    assert "None" not in thermal
    assert "Ph " not in thermal

    period = {"from_date": "2000-01-01", "to_date": "2100-12-31"}
    statement = client.get(f"/api/ledgers/{ledger['id']}/statement", params=period)
    assert statement.status_code == 200, statement.text
    assert statement.json()["ledger"]["address"] == ""

    csv = client.get(f"/api/ledgers/{ledger['id']}/statement/csv", params=period)
    assert csv.status_code == 200, csv.text
    assert "None" not in csv.text


def test_statement_pdf_html_with_no_phone_or_address():
    ledger = Ledger(id=1, company_id=1, name="Walk-in customer", address="", phone_number="", gst=None)
    company = CompanyProfile(id=1, name="Seller", address="1 Billing Street", currency_code="INR")
    html = _build_statement_html(
        ledger=ledger,
        company=company,
        from_date=date(2025, 4, 1),
        to_date=date(2026, 3, 31),
        opening_balance=0.0,
        period_debit=0.0,
        period_credit=0.0,
        closing_balance=0.0,
        entries=[],
    )
    ledger_info = html.split('class="ledger-info"', 1)[1].split("</section>", 1)[0]
    assert "Walk-in customer" in ledger_info
    assert "None" not in ledger_info
    assert "Phone:" not in ledger_info
