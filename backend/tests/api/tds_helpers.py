"""Shared fixtures for the TDS on receipts (#768) and payments (#770) tests."""

from datetime import date
from decimal import Decimal
from uuid import uuid4

from src.models.company import CompanyProfile
from src.models.tax_withholding_section import TaxWithholdingSection


def add_sections(db_session) -> dict[str, TaxWithholdingSection]:
    """The rows of the #767 catalogue the tests use (SQLite has no seeded data)."""
    def row(act, ref, legacy, nature, ind, other, no_pan, single, aggregate, note, start, end):
        return TaxWithholdingSection(
            kind="tds", act=act, section_ref=ref, legacy_code=legacy, nature=nature,
            rate_individual_huf=Decimal(str(ind)), rate_other=Decimal(str(other)), rate_no_pan=Decimal(str(no_pan)),
            threshold_single=Decimal(str(single)) if single is not None else None,
            threshold_aggregate=Decimal(str(aggregate)) if aggregate is not None else None,
            threshold_note=note, base="taxable", effective_from=start, effective_to=end,
        )

    old_start, old_end, new_start = date(2025, 4, 1), date(2026, 3, 31), date(2026, 4, 1)
    sections = {
        "194J": row(1961, "194J", "194J", "Professional fees and other specified sums", 10, 10, 20, None, 50000, "per tax year", old_start, old_end),
        "194C": row(1961, "194C", "194C", "Payment to contractor", 1, 2, 20, 30000, 100000, "per bill / tax year", old_start, old_end),
        "prof": row(2025, "393(1) Sl. No. 6(iii)", "194J", "Professional fees and other specified sums", 10, 10, 20, None, 50000, "per tax year", new_start, None),
        "contractor": row(2025, "393(1) Sl. No. 6(i)", "194C", "Payment to contractor", 1, 2, 20, 30000, 100000, "per bill / tax year", new_start, None),
        "goods": row(2025, "393(1) Sl. No. 8(ii)", "194Q", "Purchase of goods above the annual threshold", 0.1, 0.1, 5, None, 5000000, "excess over threshold", new_start, None),
    }
    db_session.add_all(sections.values())
    db_session.commit()
    return sections


def create_ledger(client, name=None, *, gst=None, pan=None, party_type=None):
    payload = {
        "name": name or f"Party {uuid4().hex[:6]}",
        "address": "Mumbai",
        "phone_number": "9999999999",
    }
    if gst:
        payload["gst"] = gst
    if pan:
        payload["pan"] = pan
    if party_type:
        payload["party_type"] = party_type
    response = client.post("/api/ledgers/", json=payload)
    assert response.status_code == 200, response.text
    return response.json()["id"]


def create_product(client, price, gst_rate=18):
    response = client.post(
        "/api/products/",
        json={
            "sku": f"TDS-{uuid4().hex[:8]}",
            "name": "Professional services",
            "description": "",
            "hsn_sac": "998311",
            "price": price,
            "gst_rate": gst_rate,
        },
    )
    assert response.status_code == 200, response.text
    product_id = response.json()["id"]
    response = client.post("/api/inventory/adjust", json={"product_id": product_id, "quantity": 1000})
    assert response.status_code == 200, response.text
    return product_id


def create_invoice(client, ledger_id, taxable, invoice_date, *, voucher_type="sales", gst_rate=18, quantity=1):
    product_id = create_product(client, taxable / quantity, gst_rate)
    payload = {
        "ledger_id": ledger_id,
        "voucher_type": voucher_type,
        "tax_inclusive": False,
        "apply_round_off": False,
        "invoice_date": invoice_date,
        "items": [{"product_id": product_id, "quantity": quantity, "unit_price": taxable / quantity}],
    }
    if voucher_type == "purchase":
        payload["supplier_invoice_number"] = f"SUP-{uuid4().hex[:6]}"
    response = client.post("/api/invoices/", json=payload)
    assert response.status_code == 200, response.text
    return response.json()


def create_account(client, name="Main bank"):
    response = client.post(
        "/api/company-accounts/",
        json={"account_type": "bank", "display_name": name, "bank_name": "HDFC", "account_number": "1234567890", "ifsc_code": "HDFC0000001"},
    )
    assert response.status_code in (200, 201), response.text
    return response.json()["id"]


def post_voucher(client, ledger_id, amount, allocations, when, *, voucher_type="receipt", account_id=None):
    payload = {
        "ledger_id": ledger_id,
        "voucher_type": voucher_type,
        "amount": amount,
        "date": when,
        "mode": "bank",
        "invoice_allocations": allocations,
    }
    if account_id is not None:
        payload["account_id"] = account_id
    return client.post("/api/payments/", json=payload)


def get_invoice(client, invoice_id):
    response = client.get(f"/api/invoices/{invoice_id}")
    assert response.status_code == 200, response.text
    return response.json()


def ledger_balance(client, ledger_id):
    response = client.get("/api/ledgers/", params={"page_size": 100})
    assert response.status_code == 200, response.text
    for item in response.json()["items"]:
        if item["id"] == ledger_id:
            return item["balance"]
    raise AssertionError(f"ledger {ledger_id} not listed")


def statement(client, ledger_id, from_date="2025-04-01", to_date="2027-03-31"):
    response = client.get(f"/api/ledgers/{ledger_id}/statement", params={"from_date": from_date, "to_date": to_date})
    assert response.status_code == 200, response.text
    return response.json()


def enable_purchase_tds(db_session, tan="MUMA12345B", client=None):
    if client is not None:
        client.get("/api/company/")  # the default company is created on first use
    company = db_session.query(CompanyProfile).first()
    assert company is not None
    company.tan = tan
    company.enable_purchase_tds = True
    db_session.commit()
    return company


def set_company_pan(client, db_session, pan):
    """The company's own PAN: the deductee on a receipt (#768)."""
    client.get("/api/company/")  # the default company is created on first use
    company = db_session.query(CompanyProfile).first()
    company.pan = pan
    company.gst = None
    db_session.commit()
    return company
