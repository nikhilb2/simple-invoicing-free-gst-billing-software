from datetime import datetime

import pytest

from src.models.buyer import Buyer
from src.models.company import CompanyProfile
from src.models.invoice import Invoice
from src.models.user import User, UserRole


@pytest.fixture
def dues_search_data(db_session):
    company = CompanyProfile(id=1, name="Search Test Co", address="", currency_code="INR")
    user = User(
        id=1,
        email="search-test@example.com",
        full_name="Tester",
        hashed_password="x",
        role=UserRole.admin,
    )
    db_session.add_all([company, user])
    db_session.flush()

    records = [
        ("Sharma Traders", "INV-2026-004", 572.24),
        ("Demo Traders", "INV-2026-011", 310.00),
        ("100% Genuine_Co", "INV_2026%99", 150.00),
    ]
    invoices = []
    for name, number, amount in records:
        ledger = Buyer(company_id=1, name=name, address="", phone_number="")
        db_session.add(ledger)
        db_session.flush()
        invoice = Invoice(
            company_id=1,
            ledger_id=ledger.id,
            ledger_name=name,
            created_by=1,
            invoice_number=number,
            voucher_type="sales",
            status="active",
            total_amount=amount,
            invoice_date=datetime(2026, 2, 1),
            due_date=datetime(2026, 3, 1),
        )
        db_session.add(invoice)
        invoices.append(invoice)

    db_session.commit()
    return invoices


@pytest.mark.parametrize(
    "search,expected_numbers",
    [
        ("INV-2026-004", ["INV-2026-004"]),
        ("inv-2026-004", ["INV-2026-004"]),
        ("2026-0", ["INV-2026-004", "INV-2026-011"]),
        ("sharma", ["INV-2026-004"]),
        ("Demo", ["INV-2026-011"]),
        ("NONEXISTENT-999", []),
    ],
)
def test_dues_search_matches_invoice_number_and_ledger_name(
    client, dues_search_data, search, expected_numbers
):
    response = client.get("/api/invoices/dues", params={"search": search})
    assert response.status_code == 200, response.text
    body = response.json()
    assert [item["invoice_number"] for item in body["items"]] == expected_numbers


@pytest.mark.parametrize("search,expected_numbers", [("%", ["INV_2026%99"]), ("_", ["INV_2026%99"])])
def test_dues_search_escapes_sql_wildcards(client, dues_search_data, search, expected_numbers):
    response = client.get("/api/invoices/dues", params={"search": search})
    assert response.status_code == 200, response.text
    assert [item["invoice_number"] for item in response.json()["items"]] == expected_numbers


def test_dues_ageing_uses_same_invoice_number_search(client, dues_search_data):
    response = client.get("/api/invoices/dues/ageing", params={"search": "INV-2026-004"})
    assert response.status_code == 200, response.text
    assert response.json()["total_remaining"] == pytest.approx(572.24)
