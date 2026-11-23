"""The credit note registry, once it holds both directions.

A supplier's note is found by their number, not the one we assigned it — that
is what the user has in front of them when reconciling against GSTR-2B.
"""
from contextlib import contextmanager
from datetime import date, datetime, timedelta
from uuid import uuid4

import pytest
from fastapi import Depends
from sqlalchemy.orm import Session

from app_main import app
from src.api.deps import get_current_user, get_db
from src.models.buyer import Buyer
from src.models.company import CompanyProfile
from src.models.credit_note import CreditNote
from src.models.invoice import InvoiceItem
from src.models.user import User, UserRole
from src.services.gst_tax_service import india_today
from tests.api.test_product_performance import _create_ledger, _create_product


@pytest.fixture
def seeded(db_session):
    user = User(
        email="admin@example.com",
        full_name="Admin",
        hashed_password="secret",
        role=UserRole.admin,
    )
    ledger = Buyer(
        name="Northwind Traders",
        address="1 Dock Road",
        gst="29ABCDE1234F1ZW",
        phone_number="9999999999",
    )
    db_session.add_all([user, ledger])
    db_session.commit()

    outward = CreditNote(
        credit_note_number="CN-2026-001",
        ledger_id=ledger.id,
        created_by=user.id,
        credit_note_type="return",
        direction="outward",
        status="active",
        taxable_amount=100, cgst_amount=9, sgst_amount=9, igst_amount=0,
        total_amount=118,
        created_at=datetime(2026, 6, 1),
    )
    inward = CreditNote(
        credit_note_number="DN-2026-001",
        ledger_id=ledger.id,
        created_by=user.id,
        credit_note_type="return",
        direction="inward",
        supplier_credit_note_number="SUP/CN/12",
        supplier_credit_note_date=date(2026, 6, 2),
        status="active",
        taxable_amount=50, cgst_amount=4.5, sgst_amount=4.5, igst_amount=0,
        total_amount=59,
        created_at=datetime(2026, 6, 2),
    )
    # A row from before the column existed.
    legacy = CreditNote(
        credit_note_number="CN-2025-099",
        ledger_id=ledger.id,
        created_by=user.id,
        credit_note_type="return",
        direction=None,
        status="active",
        taxable_amount=10, cgst_amount=0, sgst_amount=0, igst_amount=0,
        total_amount=10,
        created_at=datetime(2026, 6, 3),
    )
    db_session.add_all([outward, inward, legacy])
    db_session.commit()
    return user, ledger


def _list(client, **params):
    response = client.get("/api/credit-notes/", params=params)
    assert response.status_code == 200, response.text
    return response.json()


def _numbers(payload):
    return sorted(item["credit_note_number"] for item in payload["items"])


def test_direction_filter_separates_the_two_registries(client, seeded):
    inward = _list(client, direction="inward")
    assert _numbers(inward) == ["DN-2026-001"]

    outward = _list(client, direction="outward")
    # The legacy NULL row counts as outward — nothing before the column was inward.
    assert _numbers(outward) == ["CN-2025-099", "CN-2026-001"]


def test_unfiltered_listing_returns_both(client, seeded):
    result = _list(client)
    assert _numbers(result) == ["CN-2025-099", "CN-2026-001", "DN-2026-001"]


def test_date_to_includes_the_whole_selected_day(client, db_session, seeded):
    """date_to=2026-06-02 must cover notes created any time that day, not just
    at midnight — created_at is a timestamp and the To day used to be cut off.
    A note stamped 15:30 on the To day is the regression: with the old
    `<= midnight` cut-off it disappears from the listing."""
    user, ledger = seeded
    afternoon = CreditNote(
        credit_note_number="CN-2026-002",
        ledger_id=ledger.id,
        created_by=user.id,
        credit_note_type="return",
        direction="outward",
        status="active",
        taxable_amount=20, cgst_amount=1.8, sgst_amount=1.8, igst_amount=0,
        total_amount=23.6,
        created_at=datetime(2026, 6, 2, 15, 30),
    )
    db_session.add(afternoon)
    db_session.commit()

    result = _list(client, date_from="2026-06-02", date_to="2026-06-02")
    assert _numbers(result) == ["CN-2026-002", "DN-2026-001"]


def test_date_range_covers_each_side_of_the_boundary(client, seeded):
    result = _list(client, date_from="2026-06-02", date_to="2026-06-03")
    assert _numbers(result) == ["CN-2025-099", "DN-2026-001"]


def test_malformed_date_value_returns_422(client, seeded):
    response = client.get("/api/credit-notes/", params={"date_to": "garbage"})
    assert response.status_code == 422


def test_date_from_after_date_to_returns_400(client, seeded):
    response = client.get(
        "/api/credit-notes/",
        params={"date_from": "2026-06-03", "date_to": "2026-06-02"},
    )
    assert response.status_code == 400
    assert "date_from must be before or equal to date_to" in response.text


def test_search_matches_the_suppliers_own_number(client, seeded):
    result = _list(client, search="SUP/CN")
    assert _numbers(result) == ["DN-2026-001"]
    assert result["items"][0]["supplier_credit_note_number"] == "SUP/CN/12"
    assert result["items"][0]["supplier_credit_note_date"] == "2026-06-02"


def test_search_still_matches_our_own_number(client, seeded):
    result = _list(client, search="CN-2026")
    assert _numbers(result) == ["CN-2026-001"]


def test_a_legacy_row_reads_back_as_outward(client, seeded):
    """CreditNoteOut must not blow up on a NULL direction."""
    result = _list(client, search="CN-2025-099")
    assert result["items"][0]["direction"] == "outward"


def test_voucher_type_cannot_be_flipped_under_a_credit_note(client, db_session, seeded):
    """Direction is settled at creation; flipping the invoice would strand it.

    It drives numbering, the stock effect and whether the note is filed in
    GSTR-1 — all three would silently go wrong.
    """
    from src.models.credit_note import CreditNoteItem
    from src.models.invoice import Invoice, InvoiceItem
    from src.services.invoice_processor import InvoiceProcessor
    from src.schemas.invoice import InvoiceCreate, InvoiceItemCreate
    from src.models.product import Product
    from fastapi import HTTPException

    user, ledger = seeded
    product = Product(sku="P-FLIP", name="Widget", price=100, gst_rate=18)
    db_session.add(product)
    db_session.flush()

    invoice = Invoice(
        invoice_number="INV-FLIP-001",
        ledger_id=ledger.id,
        voucher_type="sales",
        status="active",
        created_by=user.id,
        taxable_amount=100, cgst_amount=9, sgst_amount=9, igst_amount=0,
        total_amount=118,
        created_at=datetime(2026, 6, 1),
    )
    db_session.add(invoice)
    db_session.flush()
    item = InvoiceItem(
        invoice_id=invoice.id, product_id=product.id, quantity=1, unit_price=100,
        gst_rate=18, taxable_amount=100, tax_amount=18, line_total=118,
    )
    db_session.add(item)
    db_session.flush()

    note = db_session.query(CreditNote).filter(CreditNote.credit_note_number == "CN-2026-001").one()
    db_session.add(CreditNoteItem(
        credit_note_id=note.id, invoice_id=invoice.id, invoice_item_id=item.id,
        product_id=product.id, quantity=1, unit_price=100, gst_rate=18,
        taxable_amount=100, tax_amount=18, line_total=118,
    ))
    db_session.commit()

    payload = InvoiceCreate(
        ledger_id=ledger.id,
        voucher_type="purchase",
        items=[InvoiceItemCreate(product_id=product.id, quantity=1, unit_price=100)],
    )

    with pytest.raises(HTTPException) as exc_info:
        InvoiceProcessor(db_session).apply_payload(invoice, payload, regenerate_number=False)
    assert exc_info.value.status_code == 400
    assert "credit notes against it" in exc_info.value.detail


# ─────────────────────────────────────────────────────────────────────────────
# Numbering: a taken credit_note_number must be skipped, not 500 (issue regression)
# ─────────────────────────────────────────────────────────────────────────────
# credit_note_number is unique database-wide while each company (and each new
# financial year) starts its CN series at 1. generate_next_number used to check
# the invoices table only, so the second company's note died with an
# IntegrityError-500 — and stayed dead, because the rollback reverts the
# counter too.

def _this_year() -> int:
    from datetime import datetime

    return datetime.now().year


@contextmanager
def as_persistent_admin(db_session):
    """Swap the conftest detached-admin override for a real User row.

    Creating a company persists the active company on the signed-in user and
    refreshes it, so a transient instance would fail; the user is fetched from
    the request's own session so it stays persistent through the request.
    """
    user = User(
        email="admin@example.com",
        full_name="Admin",
        hashed_password="secret",
        role=UserRole.admin,
    )
    db_session.add(user)
    db_session.commit()

    def override(db: Session = Depends(get_db)) -> User:
        found = db.query(User).filter(User.email == user.email).first()
        if found is None:
            found = user
        return found

    previous = app.dependency_overrides.get(get_current_user)
    app.dependency_overrides[get_current_user] = override
    try:
        yield user
    finally:
        app.dependency_overrides[get_current_user] = previous


def _bootstrap_company(client, name: str) -> tuple[int, dict]:
    """Create a company through the API and give it an issuable invoice.

    Returns (company_id, headers). Each company seeds its own financial year,
    so both CN series start at number 1 in the same year — the collision state.
    """
    response = client.post(
        "/api/company/companies",
        json={"name": name, "address": "1 MG Road", "gst": "27ABCDE1234F1Z0"},
    )
    assert response.status_code < 400, f"company create failed: {response.text}"
    company_id = response.json()["id"]
    headers = {"X-Company-Id": str(company_id)}

    response = client.get("/api/financial-years/", headers=headers)
    assert response.status_code == 200, response.text
    financial_year, = response.json()
    assert financial_year["is_active"]

    response = client.post(
        "/api/ledgers/",
        headers=headers,
        json={
            "name": f"Buyer of {name}",
            "address": "1 Dock Road",
            "gst": "29ABCDE1234F1ZW",
            "phone_number": "9999999999",
        },
    )
    assert response.status_code < 400, f"ledger create failed: {response.text}"
    buyer_id = response.json()["id"]

    response = client.post(
        "/api/products/",
        headers=headers,
        json={"sku": f"SKU-{company_id}", "name": "Widget", "price": 100, "initial_quantity": 100},
    )
    assert response.status_code < 400, f"product create failed: {response.text}"
    product_id = response.json()["id"]

    response = client.post(
        "/api/invoices/",
        headers=headers,
        json={
            "ledger_id": buyer_id,
            "voucher_type": "sales",
            "items": [{"product_id": product_id, "quantity": 5, "unit_price": 100}],
        },
    )
    assert response.status_code < 400, f"invoice create failed: {response.text}"
    inventory = response.json()
    return company_id, headers, buyer_id, inventory


def _issue_credit_note(client, headers, buyer_id, invoice) -> tuple[int, str | None]:
    response = client.post(
        "/api/credit-notes/",
        headers=headers,
        json={
            "ledger_id": buyer_id,
            "invoice_ids": [invoice["id"]],
            "credit_note_type": "return",
            "direction": "outward",
            "items": [{
                "invoice_id": invoice["id"],
                "invoice_item_id": invoice["items"][0]["id"],
                "quantity": 1,
            }],
        },
    )
    number = response.json().get("credit_note_number") if response.status_code == 200 or response.status_code == 201 else None
    return response.status_code, number


def test_a_second_company_numbers_its_notes_independently(client, db_session):
    """Company B's first note starts its own sequence: no 500 and no gap."""
    from src.models.global_settings import GlobalSettings

    db_session.add(GlobalSettings(id=1, max_companies=10))
    db_session.commit()

    with as_persistent_admin(db_session):
        _, alpha_headers, alpha_buyer, alpha_invoice = _bootstrap_company(client, "Alpha Corp")
        _, beta_headers, beta_buyer, beta_invoice = _bootstrap_company(client, "Beta Corp")

        alpha_status, alpha_number = _issue_credit_note(client, alpha_headers, alpha_buyer, alpha_invoice)
        assert alpha_status == 201, alpha_number
        assert alpha_number == f"CN-{_this_year()}-001"

        beta_status, beta_number = _issue_credit_note(client, beta_headers, beta_buyer, beta_invoice)
        assert beta_status == 201, beta_number
        assert beta_number == f"CN-{_this_year()}-001"


def test_a_number_already_in_the_registry_is_skipped(client, db_session):
    """The note is created 201 even when the next series number is used."""
    year = _this_year()

    response = client.post(
        "/api/ledgers/",
        json={
            "name": "Registry Buyer",
            "address": "1 Dock Road",
            "gst": "29ABCDE1234F1ZW",
            "phone_number": "9999999999",
        },
    )
    assert response.status_code < 400, response.text
    buyer_id = response.json()["id"]

    # Two notes already hold the numbers the CN-YYYY series is about to try.
    db_session.add_all([
        CreditNote(
            credit_note_number=f"CN-{year}-001",
            ledger_id=buyer_id,
            created_by=1,
            credit_note_type="return",
            direction="outward",
            status="active",
            taxable_amount=10, cgst_amount=0, sgst_amount=0, igst_amount=0,
            total_amount=10,
            created_at=datetime(year, 1, 2),
        ),
        CreditNote(
            credit_note_number=f"CN-{year}-002",
            ledger_id=buyer_id,
            created_by=1,
            credit_note_type="return",
            direction="outward",
            status="active",
            taxable_amount=10, cgst_amount=0, sgst_amount=0, igst_amount=0,
            total_amount=10,
            created_at=datetime(year, 1, 3),
        ),
    ])
    db_session.commit()

    # A financial year seeds the CN-YYYY series (starting at 1), so the create
    # takes the series path rather than the no-series fallback and must walk
    # past both taken numbers.
    response = client.post(
        "/api/financial-years/",
        json={"label": str(year), "start_date": f"{year}-01-01", "end_date": f"{year}-12-31"},
    )
    assert response.status_code < 400, response.text

    response = client.post(
        "/api/products/",
        json={"sku": "SKU-CNREG", "name": "Widget", "price": 100, "initial_quantity": 100},
    )
    assert response.status_code < 400, response.text
    product_id = response.json()["id"]

    response = client.post(
        "/api/invoices/",
        json={
            "ledger_id": buyer_id,
            "voucher_type": "sales",
            "items": [{"product_id": product_id, "quantity": 5, "unit_price": 100}],
        },
    )
    assert response.status_code < 400, response.text
    invoice = response.json()

    status, number = _issue_credit_note(client, {}, buyer_id, invoice)
    assert status == 201, number
    # CN-2026-001 and CN-2026-002 were taken; the counter walks past both.
    assert number == f"CN-{year}-003"


# ── What a note credits (#572, #603) ───────────────────────────────────────────


@pytest.fixture
def gst_seller(client, db_session):
    """A Karnataka seller, set directly because the check digit is not under test."""
    assert client.get("/api/company/").status_code == 200
    company = db_session.query(CompanyProfile).first()
    company.gst = "29AAAAA0000A1Z5"
    db_session.commit()
    return company


def _sale(client, line, *, place_of_supply=None, product_id=None, **extra):
    """A sale of one line to an unregistered buyer, dated a few days ago."""
    product = product_id or _create_product(client, f"SKU-{uuid4().hex[:8]}", "Widget", hsn_sac="8471")
    payload = {
        "voucher_type": "sales",
        "ledger_id": _create_ledger(client, f"Walk-in {uuid4().hex[:8]}"),
        "invoice_date": (india_today() - timedelta(days=3)).isoformat(),
        "items": [{"product_id": product, **line}],
        **extra,
    }
    if place_of_supply:
        payload["place_of_supply"] = place_of_supply
    response = client.post("/api/invoices/", json=payload)
    assert response.status_code == 200, response.text
    return response.json()


def _note(client, invoice, *, note_type="return", items=None, **line):
    return client.post("/api/credit-notes/", json={
        "ledger_id": invoice["ledger_id"],
        "invoice_ids": [invoice["id"]],
        "credit_note_type": note_type,
        "direction": "outward",
        "items": items or [{"invoice_id": invoice["id"], "invoice_item_id": invoice["items"][0]["id"], **line}],
    })


def _stored(db_session, note):
    db_session.expire_all()
    return db_session.get(CreditNote, note["id"])


def test_return_on_a_tax_inclusive_invoice_credits_what_was_paid(client, gst_seller, db_session):
    invoice = _sale(client, {"quantity": 1, "unit_price": 118, "gst_rate": 18}, tax_inclusive=True)

    response = _note(client, invoice, quantity=1)

    assert response.status_code == 201, response.text
    note = response.json()
    assert (note["taxable_amount"], note["cgst_amount"], note["sgst_amount"], note["total_amount"]) == (100, 9, 9, 118)
    assert (note["items"][0]["unit_price"], note["items"][0]["taxable_amount"]) == (100, 100)
    stored = _stored(db_session, note)
    assert (float(stored.taxable_amount), float(stored.total_amount)) == (100, 118)


def test_interstate_return_on_a_tax_inclusive_invoice_keeps_the_igst_head(client, gst_seller):
    invoice = _sale(client, {"quantity": 1, "unit_price": 1180, "gst_rate": 18}, tax_inclusive=True, place_of_supply="10")

    note = _note(client, invoice, quantity=1).json()

    assert (note["taxable_amount"], note["igst_amount"], note["cgst_amount"], note["total_amount"]) == (1000, 180, 0, 1180)


@pytest.mark.parametrize("tax_inclusive", [False, True])
@pytest.mark.parametrize("discount", [10, 50])
def test_return_of_a_discounted_line_credits_its_line_total(client, gst_seller, db_session, discount, tax_inclusive):
    invoice = _sale(client, {
        "quantity": 4, "unit_price": 118, "gst_rate": 18, "discount_type": "percentage", "discount_value": discount,
    }, tax_inclusive=tax_inclusive)
    line = invoice["items"][0]

    note = _note(client, invoice, quantity=4).json()

    assert note["total_amount"] == line["line_total"]
    assert note["taxable_amount"] == line["taxable_amount"]
    assert note["items"][0]["unit_price"] * 4 == pytest.approx(line["taxable_amount"])
    assert float(_stored(db_session, note).total_amount) == line["line_total"]


def test_full_return_of_an_invoice_level_discount_credits_what_was_billed(client, gst_seller):
    """#797: a 10% invoice-level discount on 1,000 @ 18% GST bills 1,062.00, not 1,180.00.

    The invoice keeps its stored taxable (1,000) and tax (180) — the discount
    never touches them. A full return must still credit only 1,062.00, split
    as 900.00 taxable / 162.00 tax: the same 90% of the GST-inclusive total
    the customer actually paid, at the line's own 18% rate.
    """
    invoice = _sale(
        client,
        {"quantity": 1, "unit_price": 1000, "gst_rate": 18},
        discount_type="percentage", discount_value=10,
    )
    assert invoice["total_amount"] == 1062.00

    note = _note(client, invoice, quantity=1).json()

    assert note["total_amount"] == 1062.00
    assert note["taxable_amount"] == 900.00
    assert (note["cgst_amount"], note["sgst_amount"]) == (81.00, 81.00)
    assert note["items"][0]["taxable_amount"] == 900.00
    assert note["items"][0]["tax_amount"] == 162.00

    statement = client.get(
        f"/api/ledgers/{invoice['ledger_id']}/statement",
        params={"from_date": "1990-01-01", "to_date": "2999-12-31"},
    )
    assert statement.status_code == 200, statement.text
    assert statement.json()["closing_balance"] == 0


def test_two_half_returns_of_a_discounted_invoice_add_up_to_its_total(client, gst_seller):
    """#797: partial returns must split the same discounted amount, not the undiscounted one."""
    invoice = _sale(
        client,
        {"quantity": 2, "unit_price": 1000, "gst_rate": 18},
        discount_type="percentage", discount_value=10,
    )

    first = _note(client, invoice, quantity=1).json()
    second = _note(client, invoice, quantity=1).json()

    assert first["total_amount"] + second["total_amount"] == pytest.approx(invoice["total_amount"])

    statement = client.get(
        f"/api/ledgers/{invoice['ledger_id']}/statement",
        params={"from_date": "1990-01-01", "to_date": "2999-12-31"},
    )
    assert statement.json()["closing_balance"] == 0


def test_fixed_invoice_discount_return_does_not_over_credit(client, gst_seller):
    """A flat (non-percentage) invoice-level discount must be honoured too."""
    invoice = _sale(
        client,
        {"quantity": 1, "unit_price": 1000, "gst_rate": 18},
        discount_type="net", discount_value=118,
    )
    assert invoice["total_amount"] == 1062.00

    note = _note(client, invoice, quantity=1).json()

    assert note["total_amount"] == 1062.00


def _closing_balance(client, invoice):
    statement = client.get(
        f"/api/ledgers/{invoice['ledger_id']}/statement",
        params={"from_date": "1990-01-01", "to_date": "2999-12-31"},
    )
    assert statement.status_code == 200, statement.text
    return statement.json()["closing_balance"]


def _credit_status(client, invoice):
    response = client.get(f"/api/invoices/{invoice['id']}")
    assert response.status_code == 200, response.text
    return response.json()["credit_status"]


def _multi_line_sale(client, lines, *, place_of_supply=None, **extra):
    """One sale of several lines, each its own product, to an unregistered buyer."""
    payload = {
        "voucher_type": "sales",
        "ledger_id": _create_ledger(client, f"Walk-in {uuid4().hex[:8]}"),
        "invoice_date": (india_today() - timedelta(days=3)).isoformat(),
        "items": [
            {"product_id": _create_product(client, f"SKU-{uuid4().hex[:8]}", "Widget", hsn_sac="8471"), **line}
            for line in lines
        ],
        **extra,
    }
    if place_of_supply:
        payload["place_of_supply"] = place_of_supply
    response = client.post("/api/invoices/", json=payload)
    assert response.status_code == 200, response.text
    return response.json()


_ROUNDED_LINES = [
    {"quantity": 3, "unit_price": 333.33, "gst_rate": 18},
    {"quantity": 7, "unit_price": 49.99, "gst_rate": 12},
    {"quantity": 1, "unit_price": 19.99, "gst_rate": 5},
]


@pytest.mark.parametrize("place_of_supply", [None, "27"], ids=["intrastate", "interstate"])
@pytest.mark.parametrize("discount_value", ["7.5", "3.2"], ids=["rounds-down", "rounds-up"])
def test_full_return_of_a_discounted_rounded_multi_line_invoice_closes_the_account(
    client, gst_seller, place_of_supply, discount_value,
):
    """#797 review: the invoice discount and the round-off are both shared over the lines.

    The note credits exactly the invoice's total, so the buyer's account closes at
    zero and the invoice reads fully credited, whichever way the total rounded.
    """
    invoice = _multi_line_sale(
        client, _ROUNDED_LINES, place_of_supply=place_of_supply,
        discount_type="percentage", discount_value=discount_value, apply_round_off=True,
    )
    assert invoice["round_off_amount"] != 0
    assert (invoice["round_off_amount"] > 0) == (discount_value == "3.2")

    response = _note(client, invoice, items=[
        {"invoice_id": invoice["id"], "invoice_item_id": item["id"], "quantity": item["quantity"]}
        for item in invoice["items"]
    ])

    assert response.status_code == 201, response.text
    note = response.json()
    assert note["total_amount"] == pytest.approx(invoice["total_amount"])
    assert note["cgst_amount"] == note["sgst_amount"]
    assert _closing_balance(client, invoice) == 0
    assert _credit_status(client, invoice) == "fully_credited"


@pytest.mark.parametrize("place_of_supply", [None, "27"], ids=["intrastate", "interstate"])
@pytest.mark.parametrize("unit_price", ["100.40", "999.66"], ids=["rounds-down", "rounds-up"])
def test_full_return_of_an_undiscounted_rounded_invoice_reverses_exactly_its_gst(
    client, gst_seller, place_of_supply, unit_price,
):
    """#891 review: round-off is not tax, so it never reaches the note's GST.

    With no invoice discount, a full return reverses exactly the GST the invoice
    charged; the round-off goes on the taxable value alone, so the note still
    credits the invoice's total and the buyer's account closes at zero.
    """
    invoice = _sale(
        client, {"quantity": 1, "unit_price": unit_price, "gst_rate": 18},
        place_of_supply=place_of_supply, apply_round_off=True,
    )
    assert invoice["round_off_amount"] != 0
    assert (invoice["round_off_amount"] > 0) == (unit_price == "999.66")

    response = _note(client, invoice, quantity=1)

    assert response.status_code == 201, response.text
    note = response.json()
    assert note["cgst_amount"] + note["sgst_amount"] + note["igst_amount"] == pytest.approx(invoice["total_tax_amount"])
    if place_of_supply:
        assert note["igst_amount"] == pytest.approx(invoice["total_tax_amount"])
    else:
        assert note["cgst_amount"] + note["sgst_amount"] == pytest.approx(invoice["total_tax_amount"])
    assert note["taxable_amount"] == pytest.approx(invoice["taxable_amount"] + invoice["round_off_amount"])
    assert note["total_amount"] == pytest.approx(invoice["total_amount"])
    assert _closing_balance(client, invoice) == 0
    assert _credit_status(client, invoice) == "fully_credited"


def test_returns_in_parts_of_a_discounted_rounded_invoice_close_the_account(client, gst_seller):
    """The same invoice returned a few units at a time adds back to exactly its total."""
    invoice = _multi_line_sale(
        client, _ROUNDED_LINES, discount_type="percentage", discount_value="7.5", apply_round_off=True,
    )
    first, second, third = invoice["items"]

    parts = [(first, 1), (second, 3), (first, 2), (third, 1), (second, 4)]
    totals = []
    for item, quantity in parts:
        response = _note(client, invoice, items=[
            {"invoice_id": invoice["id"], "invoice_item_id": item["id"], "quantity": quantity},
        ])
        assert response.status_code == 201, response.text
        totals.append(response.json()["total_amount"])
        if len(totals) < len(parts):
            assert _credit_status(client, invoice) == "partially_credited"

    assert sum(totals) == pytest.approx(invoice["total_amount"])
    assert _closing_balance(client, invoice) == 0
    assert _credit_status(client, invoice) == "fully_credited"


def test_discount_note_on_a_discounted_invoice_is_capped_at_what_was_billed(client, gst_seller):
    """#797 review: a discount note's limit is the line after the invoice discount, not its 1,180."""
    invoice = _sale(
        client,
        {"quantity": 1, "unit_price": 1000, "gst_rate": 18},
        discount_type="percentage", discount_value=10,
    )
    assert invoice["total_amount"] == 1062.00

    refused = _note(client, invoice, note_type="discount", discount_amount_inclusive="1062.01")
    assert refused.status_code == 400
    assert "1062.00" in refused.json()["detail"]

    assert _note(client, invoice, note_type="discount", discount_amount_inclusive="1062").status_code == 201
    assert _closing_balance(client, invoice) == 0
    assert _credit_status(client, invoice) == "fully_credited"


def test_discount_note_after_a_full_return_of_a_discounted_invoice_is_refused(client, gst_seller):
    invoice = _sale(
        client,
        {"quantity": 1, "unit_price": 1000, "gst_rate": 18},
        discount_type="percentage", discount_value=10,
    )
    assert _note(client, invoice, quantity=1).status_code == 201

    assert _note(client, invoice, note_type="discount", discount_amount_inclusive="0.01").status_code == 400


def test_partial_return_credits_its_share_of_the_line(client, gst_seller):
    invoice = _sale(client, {"quantity": 10, "unit_price": 99.99, "gst_rate": 18})
    line = invoice["items"][0]

    note = _note(client, invoice, quantity=3).json()

    assert note["taxable_amount"] == pytest.approx(line["taxable_amount"] * 3 / 10, abs=0.01)
    assert note["total_amount"] == pytest.approx(line["line_total"] * 3 / 10, abs=0.02)


def test_a_line_returned_in_parts_adds_back_to_exactly_what_it_charged(client, gst_seller):
    # 100.01 over 3 units rounds to 33.34 every time, which would come to 100.02.
    invoice = _sale(client, {"quantity": 3, "unit_price": 33.3366, "gst_rate": 18})
    line = invoice["items"][0]

    notes = [_note(client, invoice, quantity=1) for _ in range(3)]

    assert [n.status_code for n in notes] == [201, 201, 201]
    assert sum(n.json()["taxable_amount"] for n in notes) == pytest.approx(line["taxable_amount"])
    assert sum(n.json()["total_amount"] for n in notes) == pytest.approx(line["line_total"])


def test_tax_exclusive_return_is_unchanged(client, gst_seller):
    invoice = _sale(client, {"quantity": 5, "unit_price": 100, "gst_rate": 18})

    note = _note(client, invoice, quantity=2).json()

    assert (note["taxable_amount"], note["cgst_amount"], note["sgst_amount"], note["total_amount"]) == (200, 18, 18, 236)
    assert note["items"][0]["unit_price"] == 100


def test_return_on_a_line_with_only_a_total_still_credits_it(client, gst_seller, db_session):
    """Rows from before the tax columns have them at their default of 0."""
    invoice = _sale(client, {"quantity": 2, "unit_price": 100, "gst_rate": 0})
    item = db_session.get(InvoiceItem, invoice["items"][0]["id"])
    item.taxable_amount = 0
    item.tax_amount = 0
    db_session.commit()

    note = _note(client, invoice, quantity=1).json()

    assert note["total_amount"] == 100


def test_intrastate_discount_note_preserves_requested_inclusive_amount(client, gst_seller, db_session):
    invoice = _sale(
        client, {"quantity": 1, "unit_price": 999, "gst_rate": 18},
        tax_inclusive=True,
    )
    response = _note(
        client, invoice, note_type="discount", discount_amount_inclusive="100",
    )

    assert response.status_code == 201, response.text
    note = response.json()
    assert note["total_amount"] == pytest.approx(100.00)
    assert note["taxable_amount"] == pytest.approx(84.74)
    assert note["cgst_amount"] == pytest.approx(7.63)
    assert note["sgst_amount"] == pytest.approx(7.63)
    assert note["igst_amount"] == pytest.approx(0)
    assert note["taxable_amount"] + note["cgst_amount"] + note["sgst_amount"] == pytest.approx(100.00)
    assert note["items"][0]["line_total"] == pytest.approx(100.00)
    assert note["items"][0]["taxable_amount"] == pytest.approx(84.74)
    assert note["items"][0]["unit_price"] == pytest.approx(84.74)
    assert float(_stored(db_session, note).total_amount) == pytest.approx(100.00)


def test_discount_note_larger_than_the_line_is_refused_and_creates_nothing(client, gst_seller, db_session):
    invoice = _sale(client, {"quantity": 1, "unit_price": 100, "gst_rate": 18})

    response = _note(client, invoice, note_type="discount", discount_amount_inclusive="5000")

    assert response.status_code == 400
    assert "118.00" in response.json()["detail"]
    db_session.expire_all()
    assert db_session.query(CreditNote).count() == 0


def test_discount_note_equal_to_what_is_left_is_accepted(client, gst_seller):
    invoice = _sale(client, {"quantity": 1, "unit_price": 100, "gst_rate": 18})

    assert _note(client, invoice, note_type="discount", discount_amount_inclusive="59").status_code == 201
    assert _note(client, invoice, note_type="discount", discount_amount_inclusive="59").status_code == 201


def test_second_discount_note_past_the_line_total_is_refused(client, gst_seller):
    invoice = _sale(client, {"quantity": 1, "unit_price": 100, "gst_rate": 18})

    assert _note(client, invoice, note_type="discount", discount_amount_inclusive="100").status_code == 201
    assert _note(client, invoice, note_type="discount", discount_amount_inclusive="18.01").status_code == 400


def test_discount_after_a_partial_return_is_capped_at_what_is_left(client, gst_seller):
    invoice = _sale(client, {"quantity": 10, "unit_price": 100, "gst_rate": 18})
    assert _note(client, invoice, quantity=4).status_code == 201  # 472 of 1180

    assert _note(client, invoice, note_type="discount", discount_amount_inclusive="708.01").status_code == 400
    assert _note(client, invoice, note_type="discount", discount_amount_inclusive="708").status_code == 201


def test_return_after_a_discount_cannot_credit_more_than_the_line(client, gst_seller):
    invoice = _sale(client, {"quantity": 10, "unit_price": 100, "gst_rate": 18})
    assert _note(client, invoice, note_type="discount", discount_amount_inclusive="118").status_code == 201

    # The discount's placeholder quantity of 1 did not use up a unit, so all ten
    # can come back, for what is left of the line's 1,180.
    returned = _note(client, invoice, quantity=10)
    assert returned.status_code == 201
    assert returned.json()["total_amount"] == 1062


def test_same_line_twice_in_one_note_is_held_to_the_limits(client, gst_seller):
    invoice = _sale(client, {"quantity": 2, "unit_price": 100, "gst_rate": 18})
    twice = {"invoice_id": invoice["id"], "invoice_item_id": invoice["items"][0]["id"]}

    returned = _note(client, invoice, items=[{**twice, "quantity": 2}, {**twice, "quantity": 2}])
    discounted = _note(client, invoice, note_type="discount", items=[
        {**twice, "discount_amount_inclusive": "200"}, {**twice, "discount_amount_inclusive": "200"},
    ])

    assert (returned.status_code, discounted.status_code) == (400, 400)


def test_note_without_a_date_can_follow_a_future_dated_invoice(client, gst_seller):
    invoice = _sale(
        client, {"quantity": 1, "unit_price": 100, "gst_rate": 18},
        invoice_date=(india_today() + timedelta(days=10)).isoformat(),
    )

    response = _note(client, invoice, quantity=1)

    assert response.status_code == 201, response.text
    assert response.json()["credit_note_date"].startswith(india_today().isoformat())


# ── Cancel/edit guards: an invoice under a credit note (#602) ────────────────


def _stock(db_session, product_id):
    from src.models.inventory import Inventory

    db_session.expire_all()
    row = db_session.query(Inventory).filter(Inventory.product_id == product_id).one()
    return float(row.quantity)


def _invoice_with_return_note(client, db_session):
    """Stock 100 → sell 10 (90) → return 4 by credit note (94)."""
    product_id = _create_product(client, f"SKU-{uuid4().hex[:8]}", "Widget", stock=100)
    ledger_id = _create_ledger(client, f"Buyer {uuid4().hex[:8]}")
    response = client.post("/api/invoices/", json={
        "ledger_id": ledger_id,
        "voucher_type": "sales",
        "items": [{"product_id": product_id, "quantity": 10, "unit_price": 100}],
    })
    assert response.status_code == 200, response.text
    invoice = response.json()
    assert _stock(db_session, product_id) == 90

    response = client.post("/api/credit-notes/", json={
        "ledger_id": ledger_id,
        "invoice_ids": [invoice["id"]],
        "credit_note_type": "return",
        "direction": "outward",
        "items": [{
            "invoice_id": invoice["id"],
            "invoice_item_id": invoice["items"][0]["id"],
            "quantity": 4,
        }],
    })
    assert response.status_code == 201, response.text
    note = response.json()
    assert _stock(db_session, product_id) == 94
    return invoice, note, product_id


def test_cancelling_an_invoice_with_an_active_credit_note_is_refused(client, db_session):
    """The note already returned 4 of the 10 units; a cancel reversing all 10
    would put stock at 104 instead of 100 and orphan the active note."""
    invoice, note, product_id = _invoice_with_return_note(client, db_session)

    response = client.delete(f"/api/invoices/{invoice['id']}")
    assert response.status_code == 400, response.text
    assert "credit notes against it" in response.text
    assert _stock(db_session, product_id) == 94

    # Once the note is cancelled, the invoice cancels and stock is whole.
    response = client.post(f"/api/credit-notes/{note['id']}/cancel")
    assert response.status_code == 200, response.text
    assert _stock(db_session, product_id) == 90

    response = client.delete(f"/api/invoices/{invoice['id']}")
    assert response.status_code == 200, response.text
    assert _stock(db_session, product_id) == 100


def test_editing_an_invoice_with_a_credit_note_is_refused_not_500(client, db_session):
    """Credit note items point at the invoice's items; deleting and recreating
    them used to fail the flush on the foreign key and surface a raw 500."""
    invoice, note, product_id = _invoice_with_return_note(client, db_session)
    payload = {
        "ledger_id": invoice["ledger_id"],
        "voucher_type": "sales",
        "items": [{"product_id": product_id, "quantity": 10, "unit_price": 100}],
    }

    response = client.put(f"/api/invoices/{invoice['id']}", json=payload)
    assert response.status_code == 400, response.text
    assert "credit notes against it" in response.text


def test_editing_an_invoice_after_its_credit_note_is_cancelled_works(client, db_session):
    """A cancelled note keeps its row (#800), but its items no longer hold the
    invoice lines: the invoice is editable again, and the note is still there."""
    invoice, note, product_id = _invoice_with_return_note(client, db_session)

    response = client.post(f"/api/credit-notes/{note['id']}/cancel")
    assert response.status_code == 200, response.text

    response = client.put(f"/api/invoices/{invoice['id']}", json={
        "ledger_id": invoice["ledger_id"],
        "voucher_type": "sales",
        "items": [{"product_id": product_id, "quantity": 10, "unit_price": 100}],
    })
    assert response.status_code == 200, response.text

    kept = client.get(f"/api/credit-notes/{note['id']}").json()
    assert (kept["credit_note_number"], kept["status"]) == (note["credit_note_number"], "cancelled")
    assert kept["items"][0]["invoice_id"] == invoice["id"]
    assert kept["items"][0]["invoice_item_id"] is None


def test_a_cancelled_credit_note_is_kept_and_no_longer_counts(client, db_session):
    """Cancelling keeps the note and its number, marked cancelled (#800). It no
    longer credits the invoice, so the same units can be credited again."""
    invoice, note, product_id = _invoice_with_return_note(client, db_session)

    response = client.post(f"/api/credit-notes/{note['id']}/cancel")
    assert response.status_code == 200, response.text
    assert response.json()["status"] == "cancelled"
    assert _stock(db_session, product_id) == 90

    listed = _list(client, invoice_id=invoice["id"])
    assert [(n["credit_note_number"], n["status"]) for n in listed["items"]] == [
        (note["credit_note_number"], "cancelled")
    ]
    assert listed["items"][0]["cancelled_at"] is not None
    assert _numbers(_list(client, invoice_id=invoice["id"], status="active")) == []
    assert client.get(f"/api/invoices/{invoice['id']}").json()["credit_status"] == "not_credited"

    # All ten units can be credited again: the cancelled note's four no longer count.
    response = client.post("/api/credit-notes/", json={
        "ledger_id": invoice["ledger_id"],
        "invoice_ids": [invoice["id"]],
        "credit_note_type": "return",
        "direction": "outward",
        "items": [{"invoice_id": invoice["id"], "invoice_item_id": invoice["items"][0]["id"], "quantity": 10}],
    })
    assert response.status_code == 201, response.text
    again = response.json()
    assert again["credit_note_number"] != note["credit_note_number"]
    assert again["total_amount"] == invoice["total_amount"]
    assert _stock(db_session, product_id) == 100
    assert client.get(f"/api/invoices/{invoice['id']}").json()["credit_status"] == "fully_credited"

    # Cancelling it twice is refused and moves no stock.
    response = client.post(f"/api/credit-notes/{note['id']}/cancel")
    assert response.status_code == 400, response.text
    assert "already cancelled" in response.text
    assert _stock(db_session, product_id) == 100


def test_a_ledger_or_product_left_with_only_a_cancelled_note_cannot_be_deleted(client, db_session):
    """Editing the invoice to another party and product after cancelling its
    note leaves the note on the old ones. Deleting them is refused, not a 500."""
    invoice, note, product_id = _invoice_with_return_note(client, db_session)
    assert client.post(f"/api/credit-notes/{note['id']}/cancel").status_code == 200
    other_ledger = _create_ledger(client, f"Buyer {uuid4().hex[:8]}")
    other_product = _create_product(client, f"SKU-{uuid4().hex[:8]}", "Gadget", stock=100)

    response = client.put(f"/api/invoices/{invoice['id']}", json={
        "ledger_id": other_ledger,
        "voucher_type": "sales",
        "items": [{"product_id": other_product, "quantity": 10, "unit_price": 100}],
    })
    assert response.status_code == 200, response.text

    response = client.delete(f"/api/ledgers/{invoice['ledger_id']}")
    assert response.status_code == 400, response.text
    assert "credit notes" in response.text

    response = client.delete(f"/api/products/{product_id}")
    assert response.status_code == 400, response.text
    assert "credit notes" in response.text


def test_date_to_at_the_end_of_the_supported_range_does_not_overflow(client, seeded):
    """date(9999, 12, 31) + one day overflows Python's date range; the final
    day must still be listable instead of returning a 500."""
    result = _list(client, date_to="9999-12-31")
    assert _numbers(result) == ["CN-2025-099", "CN-2026-001", "DN-2026-001"]


def test_page_beyond_the_supported_range_returns_422(client, seeded):
    response = client.get("/api/credit-notes/", params={"page": 9223372036854775807})
    assert response.status_code == 422


def test_fractional_return_round_trip_and_cumulative_limit(client, db_session):
    product_response = client.post("/api/products/", json={
        "sku": "FRACTIONAL-CREDIT",
        "name": "Test fabric",
        "price": 100,
        "allow_decimal": True,
        "initial_quantity": 10,
    })
    assert product_response.status_code == 200, product_response.text
    product_id = product_response.json()["id"]
    invoice = _sale(client, {"quantity": 2.5, "unit_price": 100}, product_id=product_id)
    assert _stock(db_session, product_id) == 7.5

    response = _note(client, invoice, quantity=1.125)
    assert response.status_code == 201, response.text
    note = response.json()
    assert note["items"][0]["quantity"] == 1.125
    assert note["total_amount"] == 112.5
    assert _stock(db_session, product_id) == 8.625
    assert _note(client, invoice, quantity=1.376).status_code == 400
    assert _note(client, invoice, quantity=0.0011).status_code == 422

    last = _note(client, invoice, quantity=1.375)
    assert last.status_code == 201, last.text
    assert note["total_amount"] + last.json()["total_amount"] == invoice["total_amount"]
    assert _stock(db_session, product_id) == 10

    cancelled = client.post(f"/api/credit-notes/{note['id']}/cancel")
    assert cancelled.status_code == 200, cancelled.text
    assert _stock(db_session, product_id) == 8.875


def test_fractional_return_rejects_whole_number_product(client, db_session):
    invoice = _sale(client, {"quantity": 2, "unit_price": 100})
    product_id = invoice["items"][0]["product_id"]
    before = _stock(db_session, product_id)
    response = _note(client, invoice, quantity=1.5)
    assert response.status_code == 400, response.text
    assert response.json()["detail"] == "Quantity for Widget must be a whole number"
    assert _stock(db_session, product_id) == before


@pytest.mark.parametrize("tax_inclusive", [False, True])
def test_fractional_returns_add_back_to_the_invoice_line_tax(client, gst_seller, tax_inclusive):
    product_id = client.post("/api/products/", json={
        "sku": f"FRAC-GST-{uuid4().hex[:6]}",
        "name": "Test fabric",
        "price": 33.37,
        "gst_rate": 18,
        "allow_decimal": True,
        "initial_quantity": 10,
    }).json()["id"]
    invoice = _sale(
        client, {"quantity": 2.5, "unit_price": 33.37, "gst_rate": 18}, product_id=product_id, tax_inclusive=tax_inclusive
    )
    assert invoice["cgst_amount"] > 0

    notes = [_note(client, invoice, quantity=q) for q in (1.125, 1.375)]

    assert [n.status_code for n in notes] == [201, 201], [n.text for n in notes]
    for field in ("taxable_amount", "cgst_amount", "sgst_amount", "total_amount"):
        assert sum(n.json()[field] for n in notes) == pytest.approx(invoice[field], abs=1e-9), field
