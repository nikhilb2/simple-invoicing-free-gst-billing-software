"""Tests for /api/invoice-series/ routes (issue #484).

Covers list, the financial_year_id filter, update, unknown-id 404,
company isolation, admin-only role checks, and unauthenticated access,
using the shared TestClient + db_session fixtures from tests/conftest.py.
"""

from contextlib import contextmanager

from datetime import date

import pytest
from fastapi.testclient import TestClient

from app_main import app
from src.api.deps import get_current_user
from src.models.company import CompanyProfile
from src.models.financial_year import FinancialYear
from src.models.invoice_series import InvoiceSeries
from src.models.user import User, UserRole


def _seed_company(db_session, company_id, name):
    company = CompanyProfile(
        id=company_id,
        name=name,
        address="",
        gst="",
        phone_number="",
        currency_code="USD",
        email="",
        website="",
        bank_name="",
        branch_name="",
        account_name="",
        account_number="",
        ifsc_code="",
    )
    db_session.add(company)
    db_session.commit()
    return company


def _seed_series(
    db_session,
    series_id,
    company_id,
    voucher_type="sales",
    financial_year_id=None,
    prefix="INV",
):
    series = InvoiceSeries(
        id=series_id,
        company_id=company_id,
        voucher_type=voucher_type,
        financial_year_id=financial_year_id,
        prefix=prefix,
        suffix="",
        include_year=True,
        year_format="YYYY",
        separator="-",
        next_sequence=1,
        pad_digits=3,
    )
    db_session.add(series)
    db_session.commit()
    return series


@contextmanager
def as_role(role):
    """Swap the conftest admin override for another role."""
    previous = app.dependency_overrides.get(get_current_user)
    app.dependency_overrides[get_current_user] = lambda: User(
        id=1, email="test@example.com", role=role
    )
    try:
        yield
    finally:
        app.dependency_overrides[get_current_user] = previous


def _update_payload():
    return {
        "prefix": " inv ",
        "suffix": " -x ",
        "include_year": False,
        "year_format": "FY",
        "separator": "/",
        "pad_digits": 4,
        "next_sequence": 42,
    }


def test_list_returns_only_the_active_company_in_id_order(
    client, db_session
):
    _seed_company(db_session, 1, "Company A")
    _seed_company(db_session, 2, "Company B")
    _seed_series(db_session, 2, 1, voucher_type="purchase", prefix="PINV")
    _seed_series(db_session, 1, 1, voucher_type="sales", prefix="INV")
    _seed_series(db_session, 3, 2, voucher_type="sales", prefix="INV")

    response = client.get("/api/invoice-series/")
    assert response.status_code == 200, response.text
    payload = response.json()
    assert [item["id"] for item in payload] == [1, 2]
    assert [item["prefix"] for item in payload] == ["INV", "PINV"]


def test_list_financial_year_filter_narrows_results(client, db_session):
    _seed_company(db_session, 1, "Company A")
    _seed_series(db_session, 1, 1, voucher_type="sales", financial_year_id=10)
    _seed_series(
        db_session, 2, 1, voucher_type="purchase", financial_year_id=20
    )

    response = client.get("/api/invoice-series/", params={"financial_year_id": 20})
    assert response.status_code == 200, response.text
    assert [item["id"] for item in response.json()] == [2]


def test_update_applies_fields_with_prefix_suffix_normalization(
    client, db_session
):
    _seed_company(db_session, 1, "Company A")
    _seed_series(db_session, 1, 1)

    response = client.put("/api/invoice-series/1", json=_update_payload())
    assert response.status_code == 200, response.text
    updated = response.json()
    assert updated["prefix"] == "INV"
    assert updated["suffix"] == "-X"
    assert updated["include_year"] is False
    assert updated["year_format"] == "FY"
    assert updated["separator"] == "/"
    assert updated["pad_digits"] == 4
    assert updated["next_sequence"] == 42


def test_update_unknown_id_returns_404(client, db_session):
    _seed_company(db_session, 1, "Company A")

    response = client.put("/api/invoice-series/999", json=_update_payload())
    assert response.status_code == 404, response.text
    assert response.json()["detail"] == "Invoice series 999 not found"


@pytest.mark.parametrize("next_sequence", [1_000_000_000, 2_147_483_648, 3_000_000_000])
def test_update_rejects_counter_over_limit_without_changing_series(
    client, db_session, next_sequence
):
    _seed_company(db_session, 1, "Company A")
    series = _seed_series(db_session, 1, 1)

    response = client.put("/api/invoice-series/1", json={
        **_update_payload(), "prefix": "CHANGED", "next_sequence": next_sequence,
    })
    assert response.status_code == 422, response.text
    error = response.json()["detail"][0]
    assert error["loc"] == ["body", "next_sequence"]
    assert error["type"] == "less_than_equal"
    assert error["ctx"]["le"] == 999_999_999
    db_session.refresh(series)
    assert series.next_sequence == 1
    assert series.prefix == "INV"

    valid = client.put("/api/invoice-series/1", json=_update_payload())
    assert valid.status_code == 200, valid.text
    assert valid.json()["next_sequence"] == 42


@pytest.mark.parametrize("next_sequence", [1, 999_999_999])
def test_update_accepts_counter_boundaries(client, db_session, next_sequence):
    _seed_company(db_session, 1, "Company A")
    series = _seed_series(db_session, 1, 1)
    response = client.put("/api/invoice-series/1", json={
        **_update_payload(), "next_sequence": next_sequence,
    })
    assert response.status_code == 200, response.text
    assert response.json()["next_sequence"] == next_sequence
    db_session.refresh(series)
    assert series.next_sequence == next_sequence


@pytest.mark.parametrize("counter", [{}, {"next_sequence": None}])
def test_update_without_counter_keeps_current_value(client, db_session, counter):
    _seed_company(db_session, 1, "Company A")
    series = _seed_series(db_session, 1, 1)
    series.next_sequence = 42
    db_session.commit()
    response = client.put("/api/invoice-series/1", json={"prefix": "INV", **counter})
    assert response.status_code == 200, response.text
    assert response.json()["next_sequence"] == 42


def test_invoice_allocation_can_increment_counter_at_settings_limit(client, db_session):
    _seed_company(db_session, 1, "Company A")
    series = _seed_series(db_session, 1, 1)
    response = client.put("/api/invoice-series/1", json={
        "prefix": "INV", "include_year": False, "next_sequence": 999_999_999,
    })
    assert response.status_code == 200, response.text
    product = client.post("/api/products/", json={
        "sku": "COUNTER", "name": "Service", "price": 1, "gst_rate": 0,
        "maintain_inventory": False,
    })
    assert product.status_code == 200, product.text
    ledger = client.post("/api/ledgers/", json={
        "name": "Customer", "address": "1 Market St", "phone_number": "1234567890",
    })
    assert ledger.status_code == 200, ledger.text
    invoice = client.post("/api/invoices/", json={
        "voucher_type": "sales", "ledger_id": ledger.json()["id"],
        "items": [{"product_id": product.json()["id"], "quantity": 1, "unit_price": 1, "gst_rate": 0}],
    })
    assert invoice.status_code == 200, invoice.text
    assert invoice.json()["invoice_number"] == "INV-999999999"
    db_session.refresh(series)
    assert series.next_sequence == 1_000_000_000


def test_update_other_company_series_returns_404(client, db_session):
    _seed_company(db_session, 1, "Company A")
    _seed_company(db_session, 2, "Company B")
    _seed_series(db_session, 5, 2)

    response = client.put("/api/invoice-series/5", json=_update_payload())
    assert response.status_code == 404, response.text


def test_non_admin_user_gets_403_on_list_and_update(client, db_session):
    _seed_company(db_session, 1, "Company A")
    _seed_series(db_session, 1, 1)

    with as_role(UserRole.staff):
        listed = client.get("/api/invoice-series/")
        assert listed.status_code == 403, listed.text
        assert listed.json()["detail"] == "Insufficient permissions"
        updated = client.put("/api/invoice-series/1", json=_update_payload())
        assert updated.status_code == 403, updated.text


def test_unauthenticated_request_gets_401(db_session):
    _seed_company(db_session, 1, "Company A")
    saved_override = app.dependency_overrides.pop(get_current_user, None)
    try:
        response = TestClient(app).get("/api/invoice-series/")
        assert response.status_code == 401
    finally:
        if saved_override is not None:
            app.dependency_overrides[get_current_user] = saved_override


@pytest.mark.parametrize(
    ("voucher_type", "overrides"),
    [
        ("sales", {"prefix": "VERY-LONG-PREFIX", "include_year": True}),
        ("sales", {"separator": "_"}),
        ("credit_note", {"prefix": "CREDIT.NOTE"}),
    ],
)
def test_update_refuses_a_format_gstr1_rejects(client, db_session, voucher_type, overrides):
    _seed_company(db_session, 1, "Company A").gst = "29AAAAA0000A1Z5"
    prefix_before = _seed_series(db_session, 1, 1, voucher_type=voucher_type).prefix

    response = client.put("/api/invoice-series/1", json={**_update_payload(), **overrides})

    assert response.status_code == 400
    assert "GSTR-1" in response.json()["detail"]
    db_session.expire_all()
    assert db_session.get(InvoiceSeries, 1).prefix == prefix_before


def test_update_leaves_series_outside_gstr1_alone(client, db_session):
    _seed_company(db_session, 1, "Company A").gst = "29AAAAA0000A1Z5"
    _seed_series(db_session, 1, 1, voucher_type="payment")

    response = client.put("/api/invoice-series/1", json={**_update_payload(), "prefix": "VERY-LONG-PAYMENT-PREFIX"})

    assert response.status_code == 200


def test_update_guard_needs_a_company_with_a_gstin(client, db_session):
    _seed_company(db_session, 1, "Company A")
    _seed_series(db_session, 1, 1)

    response = client.put("/api/invoice-series/1", json={**_update_payload(), "prefix": "ACME-WHOLESALE-TRADING"})

    assert response.status_code == 200


def test_update_can_move_the_counter_of_a_series_already_off_the_rule(client, db_session):
    _seed_company(db_session, 1, "Company A").gst = "29AAAAA0000A1Z5"
    series = _seed_series(db_session, 1, 1)
    series.prefix, series.suffix, series.include_year, series.year_format, series.separator, series.pad_digits = (
        "VERY-LONG-PREFIX", "", False, "FY", "/", 4,
    )
    db_session.commit()

    response = client.put(
        "/api/invoice-series/1",
        json={**_update_payload(), "prefix": "VERY-LONG-PREFIX", "suffix": "", "next_sequence": 60},
    )

    assert response.status_code == 200
    assert response.json()["next_sequence"] == 60


def test_update_leaves_room_for_the_counter_to_grow(client, db_session):
    _seed_company(db_session, 1, "Company A").gst = "29AAAAA0000A1Z5"
    _seed_series(db_session, 1, 1)

    response = client.put(
        "/api/invoice-series/1",
        json={
            "prefix": "ABCDEFG", "suffix": "", "include_year": True, "year_format": "YYYY",
            "separator": "-", "pad_digits": 3, "next_sequence": 999,
        },
    )

    assert response.status_code == 400


def _year(db_session, year_id, label, *, active=False):
    db_session.add(FinancialYear(
        id=year_id, company_id=1, label=label, start_date=date(2000 + year_id, 4, 1),
        end_date=date(2001 + year_id, 3, 31), is_active=active,
    ))
    db_session.commit()


def _fy_format(db_session, series_id, prefix):
    series = db_session.get(InvoiceSeries, series_id)
    series.prefix, series.year_format = prefix, "FY"
    db_session.commit()


def test_warning_on_a_past_year_judges_the_format_its_numbers_take(client, db_session):
    _seed_company(db_session, 1, "Company A").gst = "29AAAAA0000A1Z5"
    _year(db_session, 25, "2025-26", active=True)
    _year(db_session, 24, "A LONGER 2024-25")
    _seed_series(db_session, 1, 1, financial_year_id=25)
    _seed_series(db_session, 2, 1, financial_year_id=24, prefix="OLD")
    _fy_format(db_session, 1, "INVOICE")
    # The past year's own row is short, but its documents borrow the active format.
    db_session.get(InvoiceSeries, 2).include_year = False
    db_session.commit()

    rows = {row["id"]: row for row in client.get("/api/invoice-series/").json()}

    assert "GSTR-1" in (rows[2]["gstr1_warning"] or "")


def test_active_format_is_refused_when_a_past_years_label_breaks_it(client, db_session):
    _seed_company(db_session, 1, "Company A").gst = "29AAAAA0000A1Z5"
    _year(db_session, 25, "2025-26", active=True)
    _year(db_session, 24, "OLD YEAR 2024-25")
    _seed_series(db_session, 1, 1, financial_year_id=25)
    _seed_series(db_session, 2, 1, financial_year_id=24)

    response = client.put(
        "/api/invoice-series/1",
        json={"prefix": "INV", "suffix": "", "include_year": True, "year_format": "FY", "separator": "-", "pad_digits": 3},
    )

    assert response.status_code == 400
    assert "OLD YEAR 2024-25" in response.json()["detail"]


def _two_years_with_invoices(client, dates, year_format=None, db=None):
    """Two FYs through the API, then one sales invoice per (date) -> numbers."""
    for label, start, end in (
        ("2026-27", "2026-04-01", "2027-03-31"),
        ("2027-28", "2027-04-01", "2028-03-31"),
    ):
        created = client.post("/api/financial-years/", json={
            "label": label, "start_date": start, "end_date": end,
        })
        assert created.status_code == 201, created.text
        if label == "2026-27":
            assert client.put(f"/api/financial-years/{created.json()['id']}/activate").status_code == 200
    if year_format:
        for row in db.query(InvoiceSeries).all():
            row.year_format = year_format
        db.commit()
    product = client.post("/api/products/", json={
        "sku": "FYSERIES", "name": "Service", "price": 1, "gst_rate": 0,
        "maintain_inventory": False,
    })
    assert product.status_code == 200, product.text
    ledger = client.post("/api/ledgers/", json={
        "name": "Customer", "address": "1 Market St", "phone_number": "1234567890",
    })
    assert ledger.status_code == 200, ledger.text
    numbers = []
    for invoice_date in dates:
        invoice = client.post("/api/invoices/", json={
            "voucher_type": "sales", "ledger_id": ledger.json()["id"],
            "invoice_date": invoice_date,
            "items": [{"product_id": product.json()["id"], "quantity": 1, "unit_price": 1, "gst_rate": 0}],
        })
        assert invoice.status_code == 200, invoice.text
        numbers.append(invoice.json()["invoice_number"])
    return numbers


def test_year_part_is_the_financial_years_start_year_and_next_year_has_no_gap(client):
    numbers = _two_years_with_invoices(client, [
        "2026-04-10", "2026-12-15", "2027-01-05", "2027-03-31",
        "2027-04-01", "2027-04-02", "2027-12-01",
    ])
    assert numbers == [
        "INV-2026-001", "INV-2026-002", "INV-2026-003", "INV-2026-004",
        "INV-2027-001", "INV-2027-002", "INV-2027-003",
    ]


def test_month_year_format_keeps_the_calendar_year(client, db_session):
    numbers = _two_years_with_invoices(
        client,
        ["2027-01-05", "2027-02-10", "2027-03-31", "2027-04-02"],
        year_format="MM-YYYY", db=db_session,
    )
    assert numbers == [
        "INV-01-2027-001", "INV-02-2027-002", "INV-03-2027-003", "INV-04-2027-001",
    ]


def _fy_series(db_session, voucher_type, prefix="X", year_format="YYYY"):
    """Company 1 with FY 2026-27 (active) and FY 2027-28, one series each."""
    _seed_company(db_session, 1, "Company A")
    for year_id, (label, start, end) in {
        1: ("2026-27", date(2026, 4, 1), date(2027, 3, 31)),
        2: ("2027-28", date(2027, 4, 1), date(2028, 3, 31)),
    }.items():
        db_session.add(FinancialYear(
            id=year_id, company_id=1, label=label, start_date=start, end_date=end,
            is_active=year_id == 1,
        ))
        db_session.commit()
        series = _seed_series(
            db_session, year_id, 1, voucher_type=voucher_type,
            financial_year_id=year_id, prefix=prefix,
        )
        series.year_format = year_format
        db_session.commit()


def test_back_dated_document_is_labelled_from_its_own_year_while_the_next_is_active(db_session):
    from src.services.series import generate_next_number

    # 2027-28 is the active year; the document is back-dated into 2026-27.
    _fy_series(db_session, "sales", prefix="INV")
    for row in db_session.query(FinancialYear).all():
        row.is_active = row.id == 2
    db_session.commit()

    number = generate_next_number(
        db_session, "sales", financial_year_id=1, invoice_date=date(2027, 2, 14),
        active_financial_year_id=2, company_id=1,
    )
    assert number == "INV-2026-001"
    # The active year's own counter is untouched and labels from its own year.
    assert generate_next_number(
        db_session, "sales", financial_year_id=2, invoice_date=date(2027, 4, 1),
        active_financial_year_id=2, company_id=1,
    ) == "INV-2027-001"


@pytest.mark.parametrize("voucher_type, prefix", [("credit_note", "CN"), ("quotation", "QTN")])
def test_31_march_to_1_april_rolls_to_the_next_years_label(db_session, voucher_type, prefix):
    from src.services.series import generate_next_number

    _fy_series(db_session, voucher_type, prefix=prefix)

    def issue(year_id, day):
        return generate_next_number(
            db_session, voucher_type, financial_year_id=year_id, invoice_date=day,
            active_financial_year_id=1, company_id=1,
        )

    assert issue(1, date(2027, 3, 30)) == f"{prefix}-2026-001"
    assert issue(1, date(2027, 3, 31)) == f"{prefix}-2026-002"
    assert issue(2, date(2027, 4, 1)) == f"{prefix}-2027-001"
    assert issue(2, date(2027, 4, 2)) == f"{prefix}-2027-002"


def test_month_year_calendar_year_holds_for_non_sales_across_the_rollover(db_session):
    from src.services.series import generate_next_number

    _fy_series(db_session, "quotation", prefix="QTN", year_format="MM-YYYY")
    assert generate_next_number(
        db_session, "quotation", financial_year_id=1, invoice_date=date(2027, 3, 31),
        active_financial_year_id=1, company_id=1,
    ) == "QTN-03-2027-001"
    assert generate_next_number(
        db_session, "quotation", financial_year_id=2, invoice_date=date(2027, 4, 1),
        active_financial_year_id=1, company_id=1,
    ) == "QTN-04-2027-001"
