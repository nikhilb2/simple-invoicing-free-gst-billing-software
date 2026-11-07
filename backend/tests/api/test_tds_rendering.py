"""How TDS shows up on statements, receipts, purchase bills and the connector (#768, #770)."""

import csv
from io import StringIO

import pytest

from src.mcp_server.connector import _render_payment
from src.models.company import CompanyProfile
from src.services.share_documents import build_invoice_html, build_receipt_html, build_statement_html
from tests.api.tds_helpers import add_sections, create_invoice, create_ledger, enable_purchase_tds, post_voucher

FROM, TO = "2025-04-01", "2027-03-31"


@pytest.fixture
def sections(db_session):
    return add_sections(db_session)


def _company_id(db_session):
    return db_session.query(CompanyProfile).first().id


def _receipt(client, sections, *, with_tds=True):
    ledger = create_ledger(client, "Acme Clients Pvt Ltd", pan="AAACA1234A", party_type="company")
    invoice = create_invoice(client, ledger, 100000, "2026-05-10")
    if with_tds:
        alloc = {"invoice_id": invoice["id"], "allocated_amount": 108000, "tds_amount": 10000, "tds_section_id": sections["prof"].id}
        cash = 108000
    else:
        alloc = {"invoice_id": invoice["id"], "allocated_amount": 118000}
        cash = 118000
    response = post_voucher(client, ledger, cash, [alloc], "2026-05-20T10:00:00")
    assert response.status_code == 200, response.text
    return ledger, invoice, response.json()


def _purchase_payment(client, db_session, sections, *, with_tds=True):
    ledger = create_ledger(client, "Supplier Co", pan="AAACS1234A", party_type="company")
    enable_purchase_tds(db_session)
    bill = create_invoice(client, ledger, 100000, "2026-05-10", voucher_type="purchase")
    if with_tds:
        alloc = {"invoice_id": bill["id"], "allocated_amount": 117000, "tds_amount": 1000, "tds_section_id": sections["contractor"].id}
        cash = 117000
    else:
        alloc = {"invoice_id": bill["id"], "allocated_amount": 118000}
        cash = 118000
    response = post_voucher(client, ledger, cash, [alloc], "2026-05-20T10:00:00", voucher_type="payment")
    assert response.status_code == 200, response.text
    return ledger, bill, response.json()


def test_statement_csv_has_the_tds_line_in_the_credit_column(client, sections):
    ledger, _, _ = _receipt(client, sections)
    response = client.get(f"/api/ledgers/{ledger}/statement/csv", params={"from_date": FROM, "to_date": TO})
    assert response.status_code == 200, response.text
    rows = list(csv.reader(StringIO(response.content.decode("utf-8-sig"))))
    tds_rows = [r for r in rows if len(r) > 1 and r[1] == "TDS"]
    assert len(tds_rows) == 1
    assert tds_rows[0][3].startswith("TDS deducted, s.393(1) Sl. No. 6(iii) on ")
    assert tds_rows[0][4] == "" and tds_rows[0][5] == "10000.00"


def test_statement_html_shows_the_tds_line(client, db_session, sections):
    import datetime
    ledger, _, _ = _receipt(client, sections)
    html = build_statement_html(db_session, _company_id(db_session), ledger, datetime.date(2025, 4, 1), datetime.date(2027, 3, 31))
    assert "TDS deducted, s.393(1) Sl. No. 6(iii) on" in html


def test_statement_html_without_tds_has_no_tds_line(client, db_session, sections):
    import datetime
    ledger, _, _ = _receipt(client, sections, with_tds=False)
    html = build_statement_html(db_session, _company_id(db_session), ledger, datetime.date(2025, 4, 1), datetime.date(2027, 3, 31))
    assert "TDS deducted" not in html


def test_public_statement_page_shows_the_tds_line(client, db_session, sections):
    ledger, _, _ = _receipt(client, sections)
    company_id = _company_id(db_session)
    created = client.post(
        "/api/share/",
        json={"resource_type": "ledger_statement", "resource_id": ledger, "from_date": "2026-04-01", "to_date": "2026-06-30"},
        headers={"X-Company-Id": str(company_id)},
    )
    assert created.status_code in (200, 201), created.text
    token = created.json()["token"]
    for path in (f"/s/{token}", f"/s/{token}/document.html"):
        page = client.get(path)
        assert page.status_code == 200
    assert "TDS deducted, s.393(1) Sl. No. 6(iii) on" in client.get(f"/s/{token}/document.html").text


def test_receipt_html_has_a_tds_column_with_tds(client, db_session, sections):
    _, _, receipt = _receipt(client, sections)
    html = build_receipt_html(db_session, _company_id(db_session), receipt["id"])
    assert "TDS deducted" in html
    assert ">Received</th>" in html
    assert "s.393(1) Sl. No. 6(iii)" in html
    assert "10,000.00" in html


def test_receipt_html_without_tds_is_unchanged(client, db_session, sections):
    _, _, receipt = _receipt(client, sections, with_tds=False)
    html = build_receipt_html(db_session, _company_id(db_session), receipt["id"])
    assert "TDS deducted" not in html
    assert ">Allocated</th>" in html


def test_payment_voucher_html_labels_cash_as_paid_to_supplier(client, db_session, sections):
    _, _, payment = _purchase_payment(client, db_session, sections)
    html = build_receipt_html(db_session, _company_id(db_session), payment["id"])
    assert "TDS deducted" in html
    assert ">Paid to supplier</th>" in html


def test_purchase_bill_html_shows_paid_and_tds_only_with_tds(client, db_session, sections):
    _, bill, _ = _purchase_payment(client, db_session, sections)
    html = build_invoice_html(db_session, _company_id(db_session), bill["id"])
    assert "Paid to supplier:" in html
    assert "TDS deducted:" in html
    assert "Balance:" in html


def test_purchase_bill_html_without_tds_has_no_block(client, db_session, sections):
    _, bill, _ = _purchase_payment(client, db_session, sections, with_tds=False)
    html = build_invoice_html(db_session, _company_id(db_session), bill["id"])
    assert "Paid to supplier" not in html
    assert "TDS deducted" not in html


def test_connector_text_mentions_tds():
    row = {
        "id": 1, "payment_number": "RCPT-1", "voucher_type": "receipt", "amount": 108000, "status": "active",
        "invoice_allocations": [
            {"invoice_number": "INV-1", "allocated_amount": 108000, "tds_amount": 10000, "tds_section_ref": "194J"},
            {"invoice_number": "INV-2", "allocated_amount": 500, "tds_amount": 0},
        ],
    }
    text = _render_payment(row)
    assert "Invoice INV-1: 108,000.00 + TDS ₹10,000.00 (s.194J)" in text
    assert "Invoice INV-2: 500.00\n" in text + "\n"
