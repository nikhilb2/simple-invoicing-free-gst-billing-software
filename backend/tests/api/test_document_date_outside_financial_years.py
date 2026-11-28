"""A document dated outside every financial year is refused, not numbered into another one (#1132).

Numbers run per financial year. Before the fix a document dated after the last
year, or before the first, fell back to the active year's series: an invoice
dated 1 April of a year nobody had added came out as INV-<last year>-021, and
GSTR-1 counted it in that April. Now the company has to add the year (or pick a
date in one), for every numbered voucher type, on create and on a date edit.

The years are built around today, so the tests keep working as time passes:
the previous and the current April-to-March year exist, the current one active.
"""

from datetime import date, timedelta
from types import SimpleNamespace

import pytest
from quotation_helpers import GST_MH, create_ledger, create_product, ok, quotation_payload

from src.models.invoice_series import InvoiceSeries
from src.services.gst_tax_service import india_today


def _fy_start(day: date) -> date:
    return date(day.year if day.month >= 4 else day.year - 1, 4, 1)


def _label(start: date) -> str:
    return f"{start.year}-{str(start.year + 1)[-2:]}"


def _add_year(client, start: date) -> dict:
    return ok(client.post("/api/financial-years/", json={
        "label": _label(start),
        "start_date": start.isoformat(),
        "end_date": date(start.year + 1, 3, 31).isoformat(),
    }), 201)


def _company(client) -> None:
    ok(client.put("/api/company/", json={
        "name": "Acme Traders",
        "address": "1 Market Road",
        "gst": GST_MH,
        "phone_number": "9876543210",
        "currency_code": "INR",
        "email": "hello@acme.example",
        "website": "",
        "bank_name": "",
        "branch_name": "",
        "account_name": "",
        "account_number": "",
        "ifsc_code": "",
    }))


@pytest.fixture
def two_years(client):
    """Previous and current FY, the current one active."""
    _company(client)
    current = _fy_start(india_today())
    previous = date(current.year - 1, 4, 1)
    _add_year(client, previous)
    ok(client.put(f"/api/financial-years/{_add_year(client, current)['id']}/activate"))
    return SimpleNamespace(
        client=client,
        ledger=create_ledger(client)["id"],
        product=create_product(client)["id"],
        previous=previous,
        current=current,
        # 1 April after the last year, and 31 March before the first.
        after_last=date(current.year + 1, 4, 1),
        before_first=previous - timedelta(days=1),
        refusal=lambda day: (
            f"This date is in FY {_label(_fy_start(day))}, which isn't set up yet. An admin can add it "
            f"from the side menu (Financial Year \u2192 + New FY). Or pick a date in FY {_label(current)}."
        ),
    )


def _sequences(db_session) -> list[int]:
    db_session.expire_all()
    return sorted(row.next_sequence for row in db_session.query(InvoiceSeries).all())


def _invoice(s, day: date, voucher_type: str = "sales"):
    body = {
        "ledger_id": s.ledger,
        "voucher_type": voucher_type,
        "invoice_date": day.isoformat(),
        "items": [{"product_id": s.product, "quantity": 1, "unit_price": 100}],
    }
    if voucher_type == "purchase":
        body["supplier_invoice_number"] = f"SUP-{day.isoformat()}"
    return s.client.post("/api/invoices/", json=body)


def _quotation(s, day: date, document_type: str):
    return s.client.post("/api/quotations/", json=quotation_payload(
        s.ledger, s.product, document_type=document_type, quotation_date=day.isoformat(), valid_until=None,
    ))


def _challan(s, day: date, **extra):
    return s.client.post("/api/delivery-challans/", json={
        "ledger_id": s.ledger,
        "challan_date": day.isoformat(),
        "items": [{"product_id": s.product, "quantity": 1, "unit_price": 100}],
        **extra,
    })


def _voucher(s, day: date, voucher_type: str = "receipt"):
    return s.client.post("/api/payments/", json={
        "ledger_id": s.ledger,
        "voucher_type": voucher_type,
        "amount": 100,
        "date": f"{day.isoformat()}T10:00:00",
        "mode": "bank",
    })


# ---------------------------------------------------------------------------
# Create: refused on both sides of the range, for every numbered voucher
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("side", ["after_last", "before_first"])
@pytest.mark.parametrize("make", [
    pytest.param(lambda s, day: _invoice(s, day), id="sales"),
    pytest.param(lambda s, day: _invoice(s, day, "purchase"), id="purchase"),
    pytest.param(lambda s, day: _quotation(s, day, "quotation"), id="quotation"),
    pytest.param(lambda s, day: _quotation(s, day, "proforma"), id="proforma"),
    pytest.param(lambda s, day: _challan(s, day), id="challan"),
    pytest.param(lambda s, day: _challan(s, day, challan_number="DC-TYPED-1"), id="challan-typed-number"),
    pytest.param(lambda s, day: _voucher(s, day, "receipt"), id="receipt"),
    pytest.param(lambda s, day: _voucher(s, day, "payment"), id="payment"),
])
def test_a_date_no_financial_year_covers_is_refused(two_years, db_session, side, make):
    s = two_years
    day = getattr(s, side)
    before = _sequences(db_session)

    response = make(s, day)

    assert response.status_code == 400, response.text
    assert response.json()["detail"] == s.refusal(day)
    # Nothing was numbered: no counter moved.
    assert _sequences(db_session) == before


def test_the_issue_example_reads_plainly(two_years):
    """The exact message for an invoice dated 1 April after the last year."""
    s = two_years
    response = _invoice(s, s.after_last)

    next_label = _label(s.after_last)
    assert response.json()["detail"] == (
        f"This date is in FY {next_label}, which isn't set up yet. An admin can add it from the "
        f"side menu (Financial Year \u2192 + New FY). Or pick a date in FY {_label(s.current)}."
    )


def test_adding_the_year_lets_the_document_through_in_its_own_series(two_years):
    s = two_years
    assert _invoice(s, s.after_last).status_code == 400

    _add_year(s.client, s.after_last)
    created = ok(_invoice(s, s.after_last))

    assert created["invoice_number"] == f"INV-{s.after_last.year}-001"


def test_an_opening_balance_before_the_first_year_is_still_allowed(two_years):
    """It takes no number, and opening balances are normally dated before the books start."""
    s = two_years
    response = _voucher(s, s.before_first, "opening_balance")

    assert response.status_code == 200, response.text


def test_a_credit_note_dated_in_a_year_not_set_up_is_refused(client, db_session):
    """Only last year exists: a note issued today (this year) must not take last year's number."""
    _company(client)
    current = _fy_start(india_today())
    previous_fy = _add_year(client, date(current.year - 1, 4, 1))
    ok(client.put(f"/api/financial-years/{previous_fy['id']}/activate"))
    s = SimpleNamespace(client=client, ledger=create_ledger(client)["id"], product=create_product(client)["id"])
    invoice = ok(_invoice(s, current - timedelta(days=5)))
    before = _sequences(db_session)

    response = client.post("/api/credit-notes/", json={
        "ledger_id": s.ledger,
        "invoice_ids": [invoice["id"]],
        "credit_note_type": "return",
        "items": [{"invoice_id": invoice["id"], "invoice_item_id": invoice["items"][0]["id"], "quantity": 1}],
    })

    assert response.status_code == 400, response.text
    assert response.json()["detail"].startswith(f"This date is in FY {_label(current)}, which isn't set up yet.")
    assert _sequences(db_session) == before


def test_a_company_with_no_financial_years_keeps_its_yearless_numbering(client):
    _company(client)
    s = SimpleNamespace(client=client, ledger=create_ledger(client)["id"], product=create_product(client)["id"])

    created = ok(_invoice(s, date(2020, 4, 1)))

    assert created["invoice_number"] == "INV-000001"


# ---------------------------------------------------------------------------
# The 31 March / 1 April boundary still splits between the two years
# ---------------------------------------------------------------------------

def test_the_year_boundary_still_picks_each_days_own_year(two_years):
    s = two_years
    last_day = s.current - timedelta(days=1)

    old_invoice = ok(_invoice(s, last_day))
    new_invoice = ok(_invoice(s, s.current))
    old_quote = ok(_quotation(s, last_day, "quotation"))
    new_quote = ok(_quotation(s, s.current, "quotation"))
    old_proforma = ok(_quotation(s, last_day, "proforma"))
    new_proforma = ok(_quotation(s, s.current, "proforma"))

    assert old_invoice["invoice_number"] == f"INV-{s.previous.year}-001"
    assert new_invoice["invoice_number"] == f"INV-{s.current.year}-001"
    assert old_quote["quotation_number"] == f"QT-{s.previous.year}-001"
    assert new_quote["quotation_number"] == f"QT-{s.current.year}-001"
    assert old_proforma["quotation_number"] == f"PI-{s.previous.year}-001"
    assert new_proforma["quotation_number"] == f"PI-{s.current.year}-001"
    assert old_invoice["financial_year_id"] != new_invoice["financial_year_id"]


# ---------------------------------------------------------------------------
# Edit: moving a document's date out of every year is refused too
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("side", ["after_last", "before_first"])
def test_editing_a_quotation_to_a_date_no_year_covers_is_refused(two_years, side):
    s = two_years
    quote = ok(_quotation(s, s.current, "proforma"))
    day = getattr(s, side)

    body = quotation_payload(s.ledger, s.product, quotation_date=day.isoformat(), valid_until=None)
    body.pop("document_type")  # fixed once created
    response = s.client.put(f"/api/quotations/{quote['id']}", json=body)

    assert response.status_code == 400, response.text
    assert response.json()["detail"] == s.refusal(day)
    assert ok(s.client.get(f"/api/quotations/{quote['id']}"))["quotation_date"] == s.current.isoformat()


@pytest.mark.parametrize("side", ["after_last", "before_first"])
def test_editing_a_challan_to_a_date_no_year_covers_is_refused(two_years, side):
    s = two_years
    challan = ok(_challan(s, s.current))
    day = getattr(s, side)

    response = s.client.put(f"/api/delivery-challans/{challan['id']}", json={
        "ledger_id": s.ledger,
        "challan_date": day.isoformat(),
        "items": [{"product_id": s.product, "quantity": 1, "unit_price": 100}],
    })

    assert response.status_code == 400, response.text
    assert response.json()["detail"] == s.refusal(day)


@pytest.mark.parametrize("side", ["after_last", "before_first"])
def test_editing_a_receipt_to_a_date_no_year_covers_is_refused(two_years, side):
    s = two_years
    receipt = ok(_voucher(s, s.current))
    day = getattr(s, side)

    response = s.client.put(f"/api/payments/{receipt['id']}", json={
        "voucher_type": "receipt",
        "amount": 100,
        "date": f"{day.isoformat()}T10:00:00",
        "mode": "bank",
    })

    assert response.status_code == 400, response.text
    assert response.json()["detail"] == s.refusal(day)
