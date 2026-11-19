import csv
from datetime import datetime
from io import StringIO

from src.models.buyer import Buyer
from src.models.company import CompanyProfile
from src.models.company_account import CompanyAccount
from src.models.invoice import Invoice
from src.models.payment import Payment
from src.models.user import User, UserRole


def _seed_day_book_rows(db_session):
    user = User(
        id=1,
        email="test@example.com",
        full_name="Test Admin",
        hashed_password="test-hash",
        role=UserRole.admin,
    )
    company = CompanyProfile(
        id=1,
        name="Respawn Pvt Ltd",
        address="1 Billing Street",
        gst="29RESP1234N1Z1",
        phone_number="9999999999",
        currency_code="INR",
        email="accounts@example.com",
        website="",
        bank_name="",
        branch_name="",
        account_name="",
        account_number="",
        ifsc_code="",
    )
    ledger = Buyer(
        id=1,
        company_id=company.id,
        name="Acme Stores",
        address="42 Market Road",
        gst="29ABCDE1234F1ZW",
        phone_number="9999999999",
        email="ledger@example.com",
    )
    invoice = Invoice(
        invoice_number="S-001",
        company_id=company.id,
        ledger_id=ledger.id,
        ledger_name=ledger.name,
        ledger_address=ledger.address,
        ledger_gst=ledger.gst,
        ledger_phone=ledger.phone_number,
        company_name=company.name,
        company_address=company.address,
        company_gst=company.gst,
        company_phone=company.phone_number,
        company_email=company.email,
        company_currency_code=company.currency_code,
        voucher_type="sales",
        status="active",
        created_by=user.id,
        taxable_amount=1000,
        total_tax_amount=0,
        cgst_amount=0,
        sgst_amount=0,
        igst_amount=0,
        total_amount=1000,
        invoice_date=datetime(2026, 4, 3, 10, 0, 0),
    )
    payment = Payment(
        company_id=company.id,
        ledger_id=ledger.id,
        voucher_type="receipt",
        amount=400,
        date=datetime(2026, 4, 4, 11, 0, 0),
        payment_number="RCPT-001",
        mode="bank",
        created_by=user.id,
        status="active",
    )

    db_session.add_all([user, company, ledger, invoice, payment])
    db_session.commit()



def test_day_book_csv_export_downloads_expected_columns(client, db_session):
    _seed_day_book_rows(db_session)

    response = client.get(
        "/api/ledgers/day-book/csv",
        params={"from_date": "2026-04-01", "to_date": "2026-04-30"},
    )

    assert response.status_code == 200, response.text
    assert "text/csv" in response.headers["content-type"]
    assert "attachment; filename=\"day_book_2026-04-01_2026-04-30.csv\"" == response.headers["content-disposition"]

    lines = response.text.splitlines()
    assert lines[0].lstrip("\ufeff") == "Date,Voucher Type,Reference,Ledger,Particulars,Debit,Credit"
    assert any("2026-04-03,Sales,S-001,Acme Stores,Sales Invoice #1,1000.00," in line for line in lines)
    assert any("2026-04-04,Receipt,RCPT-001,Acme Stores,Receipt #1 (bank),,400.00" in line for line in lines)
    assert lines[-1] == ",,,,Totals,1000.00,400.00"



def test_day_book_labels_a_payment_without_a_party_as_an_account_entry(client, db_session):
    _seed_day_book_rows(db_session)
    account = CompanyAccount(company_id=1, account_type="bank", display_name="Test Bank")
    db_session.add(account)
    db_session.flush()
    db_session.add(
        Payment(
            company_id=1,
            ledger_id=None,
            account_id=account.id,
            voucher_type="payment",
            amount=500,
            date=datetime(2026, 4, 10, 10, 0, 0),
            payment_number="PAY-REGISTER",
            mode="bank",
            created_by=1,
            status="active",
        )
    )
    db_session.commit()
    params = {"from_date": "2026-04-01", "to_date": "2026-04-30"}

    response = client.get("/api/ledgers/day-book", params=params)
    assert response.status_code == 200, response.text
    entry = next(row for row in response.json()["entries"] if row["reference_number"] == "PAY-REGISTER")
    assert entry["ledger_name"] == "Account entry"
    assert entry["account_display_name"] == "Test Bank"

    export = client.get("/api/ledgers/day-book/csv", params=params)
    assert export.status_code == 200, export.text
    rows = csv.DictReader(StringIO(export.text.lstrip("\ufeff")))
    payment_row = next(row for row in rows if row["Reference"] == "PAY-REGISTER")
    assert payment_row["Ledger"] == "Account entry"


def test_day_book_pdf_export_streams_pdf_attachment(client, db_session):
    _seed_day_book_rows(db_session)

    response = client.get(
        "/api/ledgers/day-book/pdf",
        params={"from_date": "2026-04-01", "to_date": "2026-04-30"},
    )

    assert response.status_code == 200, response.text
    assert response.headers["content-type"] == "application/pdf"
    assert "attachment; filename=\"day_book_2026-04-01_2026-04-30.pdf\"" == response.headers["content-disposition"]
    assert response.content.startswith(b"%PDF")



def test_day_book_exports_reject_invalid_date_range(client):
    csv_response = client.get(
        "/api/ledgers/day-book/csv",
        params={"from_date": "2026-05-01", "to_date": "2026-04-01"},
    )
    pdf_response = client.get(
        "/api/ledgers/day-book/pdf",
        params={"from_date": "2026-05-01", "to_date": "2026-04-01"},
    )

    assert csv_response.status_code == 400
    assert csv_response.json()["detail"] == "from_date must be before or equal to to_date"

    assert pdf_response.status_code == 400
    assert pdf_response.json()["detail"] == "from_date must be before or equal to to_date"
