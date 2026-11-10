"""The TCS collected report (#769)."""

import csv
import io
from decimal import Decimal

from src.models.invoice import Invoice
from tests.api.test_tcs_invoices import (  # noqa: F401  (fixtures)
    BUYER_GSTIN,
    SCRAP_2025,
    _credit,
    _invoice,
    _ledger,
    _ok,
    _product,
    _section_id,
    company,
    sections,
)

URL = "/api/reports/tcs-collected"


def _tcs_invoice(client, db, ledger, product, when="2026-04-15", **extra):
    return _ok(_invoice(client, ledger, product, when=when, tcs_section_id=_section_id(db, SCRAP_2025), **extra))


def test_quarter_filter_and_row_content(client, db_session, company):
    ledger = _ledger(client, gst=BUYER_GSTIN)
    product = _product(client)
    inv = _tcs_invoice(client, db_session, ledger, product)

    q1 = _ok(client.get(URL, params={"tax_year": 2026, "quarter": 1}))
    assert [r["document_number"] for r in q1["rows"]] == [inv["invoice_number"]]
    row = q1["rows"][0]
    assert row["kind"] == "invoice"
    assert row["buyer_pan"] == "ABCDE1234F"
    assert row["section_ref"] == SCRAP_2025
    assert Decimal(row["tcs_amount"]) == Decimal("2360.00")
    assert Decimal(row["base_amount"]) == Decimal("118000.00")
    assert (q1["from_date"], q1["to_date"]) == ("2026-04-01", "2026-06-30")
    assert _ok(client.get(URL, params={"tax_year": 2026, "quarter": 2}))["rows"] == []
    assert len(_ok(client.get(URL, params={"tax_year": 2026}))["rows"]) == 1


def test_non_tcs_and_cancelled_invoices_are_excluded(client, db_session, company):
    ledger = _ledger(client, gst=BUYER_GSTIN)
    product = _product(client)
    _ok(_invoice(client, ledger, product))  # no TCS
    cancelled = _tcs_invoice(client, db_session, ledger, product)
    db_session.query(Invoice).filter(Invoice.id == cancelled["id"]).update({"status": "cancelled"})
    db_session.commit()
    report = _ok(client.get(URL, params={"tax_year": 2026}))
    assert report["rows"] == []
    assert Decimal(report["total_tcs"]) == 0


def test_credit_note_row_is_negative_and_totals_are_netted(client, db_session, company):
    ledger = _ledger(client, gst=BUYER_GSTIN)
    product = _product(client, price=500, sku="S2")
    inv = _tcs_invoice(client, db_session, ledger, product, quantity=4, unit_price=500)
    note = _credit(client, inv, 1)

    report = _ok(client.get(URL, params={"tax_year": 2026, "quarter": 1}))
    kinds = sorted(r["kind"] for r in report["rows"])
    assert kinds == ["credit_note", "invoice"]
    cn = next(r for r in report["rows"] if r["kind"] == "credit_note")
    assert Decimal(cn["tcs_amount"]) == -Decimal(str(note["tcs_amount"]))
    assert Decimal(cn["base_amount"]) < 0
    (total,) = report["totals_by_section"]
    assert total["section_ref"] == SCRAP_2025 and total["count"] == 2
    assert Decimal(total["tcs_amount"]) == Decimal(str(inv["tcs_amount"])) - Decimal(str(note["tcs_amount"]))
    assert Decimal(report["total_tcs"]) == Decimal(total["tcs_amount"])
    assert Decimal(report["total_base"]) == Decimal(total["base_amount"])


def test_return_form_switches_at_the_2026_rules(client, db_session, company):
    assert _ok(client.get(URL, params={"tax_year": 2025, "quarter": 4}))["return_form"] == "Form 27EQ"
    assert _ok(client.get(URL, params={"tax_year": 2025}))["return_form"] == "Form 27EQ"
    assert _ok(client.get(URL, params={"tax_year": 2026}))["return_form"] == "Form 143"
    assert _ok(client.get(URL, params={"tax_year": 2026, "quarter": 1}))["return_form"] == "Form 143"


def test_invalid_quarter_is_refused(client, db_session, company):
    assert client.get(URL, params={"quarter": 5}).status_code == 400


def test_csv_export(client, db_session, company):
    ledger = _ledger(client, gst=BUYER_GSTIN)
    product = _product(client)
    inv = _tcs_invoice(client, db_session, ledger, product)
    response = client.get(f"{URL}/export-csv", params={"tax_year": 2026, "quarter": 1})
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/csv")
    assert "tcs_collected_2026-27_Q1.csv" in response.headers["content-disposition"]
    rows = list(csv.reader(io.StringIO(response.content.decode("utf-8-sig"))))
    assert rows[0][:3] == ["Type", "Document", "Date"]
    assert rows[1][1] == inv["invoice_number"] and rows[1][4] == "ABCDE1234F" and rows[1][9] == "2360.00"
    assert [] in rows
    assert rows[-1] == ["Grand total", "", "", "118000.00", "2360.00"]


def test_sale_under_a_declaration_is_listed_as_not_collected(client, db_session, company):
    declared = _ledger(client, gst=BUYER_GSTIN, declaration=True, name="Mill")
    product = _product(client)
    collected = _tcs_invoice(client, db_session, _ledger(client, pan="ABCDE1234F", name="Trader"), product)
    exempt = _tcs_invoice(client, db_session, declared, product)
    assert exempt["tcs_amount"] == 0

    report = _ok(client.get(URL, params={"tax_year": 2026, "quarter": 1}))

    rows = {row["document_number"]: row for row in report["rows"]}
    assert rows[exempt["invoice_number"]]["remark"] == "Declaration – not collected"
    assert Decimal(rows[exempt["invoice_number"]]["tcs_amount"]) == 0
    assert rows[collected["invoice_number"]]["remark"] is None
    (total,) = report["totals_by_section"]
    assert total["count"] == 2
    assert Decimal(total["base_amount"]) == Decimal("118000.00")
    assert Decimal(total["not_collected_base"]) == Decimal("118000.00")
    assert Decimal(report["total_tcs"]) == Decimal("2360.00")

    csv_rows = list(csv.reader(io.StringIO(
        client.get(f"{URL}/export-csv", params={"tax_year": 2026, "quarter": 1}).content.decode("utf-8-sig")
    )))
    assert "Declaration – not collected" in [row[-1] for row in csv_rows[1:3]]


def test_csv_neutralises_formulas_in_free_text(client, db_session, company):
    ledger = _ledger(client, gst=BUYER_GSTIN, name="=HYPERLINK(\"http://x\")")
    product = _product(client)
    _tcs_invoice(client, db_session, ledger, product)
    response = client.get(f"{URL}/export-csv", params={"tax_year": 2026, "quarter": 1})
    rows = list(csv.reader(io.StringIO(response.content.decode("utf-8-sig"))))
    assert rows[1][3] == "'=HYPERLINK(\"http://x\")"
