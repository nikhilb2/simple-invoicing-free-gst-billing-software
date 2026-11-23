"""Section 34's outer deadline across creation and both GST reports."""

import calendar
from datetime import date, datetime, time

import pytest

from src.models.credit_note import CreditNote
from src.models.invoice import Invoice
from tests.api.test_gstr1_filing_edges import (
    _by_field, _credit_note_docs, _export, _in_period, _period, _sale,
    _summary, _validate, seller,
)
from tests.api.test_gstr3b_api import WORKSHEET, _row, _warning
from tests.api.test_place_of_supply import MAHARASHTRA_BUYER, _ledger_with_gst, _note_payload
from tests.api.test_product_performance import _create_ledger, _create_product, _line


def _date_invoice(db, invoice, when):
    db.get(Invoice, invoice["id"]).invoice_date = datetime.combine(when, time.min)
    db.commit()


def _create_note(client, invoices, **extra):
    response = client.post("/api/credit-notes/", json=_note_payload(invoices, **extra))
    assert response.status_code == 201, response.text
    return response.json()


def _worksheet(client, period=None):
    response = client.get(WORKSHEET, params=period or _period())
    assert response.status_code == 200, response.text
    return response.json()


@pytest.mark.parametrize("section", ["B2CS", "CDNR", "CDNUR"])
def test_expired_note_warns_and_does_not_reduce_gst(client, db_session, seller, section):
    product = _create_product(client, "LATE", "Widget", hsn_sac="8471")
    ledger = (_ledger_with_gst(client, "Buyer", MAHARASHTRA_BUYER)
              if section == "CDNR" else _create_ledger(client, "Walk-in"))
    extra = {"place_of_supply": "27"} if section == "CDNUR" else {}
    amount = 300000 if section == "CDNUR" else 1000
    sale = _sale(client, ledger, product, items=[_line(product, 1, amount)], **extra)
    old_date = date(date.fromisoformat(_in_period()).year - 2, 3, 10)
    _date_invoice(db_session, sale, old_date)

    note = _create_note(client, [sale], credit_note_date=_in_period())
    assert note["gst_warnings"]
    assert sale["invoice_number"] in note["gst_warnings"][0]
    assert f"{old_date.year}-11-30" in note["gst_warnings"][0]
    assert "commercial" in note["gst_warnings"][0]

    result = _validate(client)
    [warning] = _by_field(result, "Section 34 deadline")
    assert warning["severity"] == "warning"
    assert warning["invoice_number"] == note["credit_note_number"]
    assert result["status"] == "valid"
    data = _export(client)
    assert not any(key in data for key in ("cdnr", "cdnur", "b2cs", "hsn"))
    # Its issued number still belongs to the series, even with no GST reduction.
    assert _credit_note_docs(data)[0]["net_issue"] == 1
    assert _summary(client)["credit_notes"]["taxable_value"] == 0
    csv = client.get("/api/ledgers/tax-ledger/gstr1/export-csv", params=_period())
    assert csv.status_code == 200
    assert note["credit_note_number"] not in csv.text

    sheet = _worksheet(client)
    assert _row(sheet, "3.1a")["taxable_value"] == 0
    assert _row(sheet, "3.1a")["cgst"] == 0
    assert _row(sheet, "3.1a")["igst"] == 0
    [document] = _warning(sheet, "note_section_34_deadline")["documents"]
    assert document["number"] == note["credit_note_number"]
    assert sale["invoice_number"] in document["detail"]


@pytest.mark.parametrize("invoice_date,note_date,eligible", [
    (date(2024, 3, 31), date(2024, 11, 30), True),
    (date(2024, 3, 31), date(2024, 12, 1), False),
    (date(2024, 4, 1), date(2025, 11, 30), True),
    (date(2024, 4, 1), date(2025, 12, 1), False),
])
def test_deadline_is_inclusive_and_follows_the_sales_financial_year(
    client, db_session, seller, invoice_date, note_date, eligible,
):
    product = _create_product(client, "BOUNDARY", "Widget", hsn_sac="8471")
    sale = _sale(client, _create_ledger(client, "Walk-in"), product)
    _date_invoice(db_session, sale, invoice_date)
    note = _create_note(client, [sale], credit_note_date=note_date.isoformat())
    assert bool(note.get("gst_warnings")) is not eligible
    period = {
        "from_date": note_date.replace(day=1).isoformat(),
        "to_date": note_date.replace(day=calendar.monthrange(note_date.year, note_date.month)[1]).isoformat(),
    }
    response = client.get("/api/ledgers/tax-ledger/gstr1/export-json", params=period)
    assert response.status_code == 200, response.text
    assert ("b2cs" in response.json()) is eligible
    sheet = _worksheet(client, period)
    assert _row(sheet, "3.1a")["taxable_value"] == (-1000 if eligible else 0)
    assert bool(_warning(sheet, "note_section_34_deadline")) is not eligible


@pytest.mark.parametrize("old_first", [True, False])
def test_any_expired_source_excludes_the_whole_note(client, db_session, seller, old_first):
    product = _create_product(client, "MIXED", "Widget", hsn_sac="8471")
    ledger = _create_ledger(client, "Walk-in")
    old = _sale(client, ledger, product)
    current = _sale(client, ledger, product)
    _date_invoice(db_session, old, date(2020, 3, 31))
    invoices = [old, current] if old_first else [current, old]
    note = _create_note(client, invoices, credit_note_date=_in_period())
    assert len(note["gst_warnings"]) == 1
    assert old["invoice_number"] in note["gst_warnings"][0]
    assert _export(client)["b2cs"][0]["txval"] == 1000
    assert _row(_worksheet(client), "3.1a")["taxable_value"] == 1000


def test_default_note_date_is_also_checked(client, db_session, seller):
    product = _create_product(client, "TODAY", "Widget", hsn_sac="8471")
    sale = _sale(client, _create_ledger(client, "Walk-in"), product)
    _date_invoice(db_session, sale, date(2020, 3, 31))
    assert _create_note(client, [sale])["gst_warnings"]


def test_selected_invoice_without_credited_items_does_not_expire_the_note(client, db_session, seller):
    product = _create_product(client, "UNUSED", "Widget", hsn_sac="8471")
    ledger = _create_ledger(client, "Walk-in")
    old = _sale(client, ledger, product)
    current = _sale(client, ledger, product)
    _date_invoice(db_session, old, date(2020, 3, 31))
    note = _create_note(client, [current], invoice_ids=[old["id"], current["id"]], credit_note_date=_in_period())
    assert note["gst_warnings"] == []
    assert "b2cs" not in _export(client)
    assert _row(_worksheet(client), "3.1a")["taxable_value"] == 0


def test_legacy_wrong_direction_does_not_bypass_deadline(client, db_session, seller):
    product = _create_product(client, "LEGACY", "Widget", hsn_sac="8471")
    sale = _sale(client, _create_ledger(client, "Walk-in"), product)
    _date_invoice(db_session, sale, date(2020, 3, 31))
    note = _create_note(client, [sale], credit_note_date=_in_period())
    db_session.get(CreditNote, note["id"]).direction = "inward"
    db_session.commit()
    assert "b2cs" not in _export(client)
    assert _row(_worksheet(client), "3.1a")["taxable_value"] == 0


def test_supplier_note_still_reverses_input_credit(client, db_session, seller):
    product = _create_product(client, "SUPPLIER", "Widget", hsn_sac="8471")
    ledger = _ledger_with_gst(client, "Supplier", MAHARASHTRA_BUYER)
    purchase = _sale(client, ledger, product, voucher_type="purchase", supplier_invoice_number="OLD-PURCHASE")
    _date_invoice(db_session, purchase, date(2020, 3, 31))
    note = _create_note(client, [purchase], direction="inward", credit_note_date=_in_period(),
                        supplier_credit_note_number="SUP-CN-1", supplier_credit_note_date=_in_period())
    assert note.get("gst_warnings", []) == []
    sheet = _worksheet(client)
    assert _warning(sheet, "note_section_34_deadline") is None
    assert _row(sheet, "4a5")["igst"] == -180
