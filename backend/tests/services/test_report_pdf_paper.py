"""A5 paper for the report PDFs: ledger statement, day book, tax ledger, GSTR-1 and GSTR-3B.

A4 output must not change (the existing template tests cover its content); here the
page size is read back from WeasyPrint's laid-out document and every box on the page
is checked to stay inside the page width, since a wide table that overflows A5 is
cut off silently when printed.
"""

from datetime import date, datetime
from decimal import Decimal

import pytest
import weasyprint

from src.api.routes import ledgers as ledgers_routes
from src.api.routes.ledgers import _build_tax_ledger_pdf_html, _build_tax_ledger_totals
from src.models.buyer import Buyer as Ledger
from src.models.company import CompanyProfile
from src.models.user import User, UserRole
from src.schemas.gstr3b import Gstr3bWorksheetOut
from src.schemas.ledger import DayBookEntry, LedgerStatementEntry, TaxLedgerEntry, TaxLiability
from src.services.gst_returns.classification import InvoiceDoc, InvoiceLine
from src.services.gst_returns.gstr3b import build_worksheet, resolve_return_period
from src.services.pdf_paper import render_pdf
from src.services.pdf_templates.gstr3b_template import build_gstr3b_worksheet_html
from src.services.pdf_templates.ledger_template import _build_day_book_html, _build_statement_html

PX_PER_MM = 96 / 25.4
SIZES_MM = {"a4": (210, 297), "a5": (148, 210)}


def _company() -> CompanyProfile:
    return CompanyProfile(
        id=1,
        name="Respawn Pvt Ltd",
        address="1 Billing Street, Indiranagar, Bengaluru 560038",
        gst="29RESP1234N1Z1",
        phone_number="9999999999",
        email="accounts@respawn.in",
        website="https://respawn.in",
        currency_code="INR",
    )


def _ledger() -> Ledger:
    return Ledger(
        id=1, company_id=1, name="Acme Stores", address="42 Market Road", gst="29ABCDE1234F1ZW",
        phone_number="9899001009", email="books@acme.in",
    )


def _statement_html(paper: str, rows: int = 40) -> str:
    entries = [
        LedgerStatementEntry(
            entry_id=i, entry_type="invoice", date=datetime(2025, 4, 1 + i % 28), voucher_type="Sales",
            reference_number=f"INV-2025-{i:04d}", particulars="Acme Stores and Associates Trading Company",
            debit=123456.78 * (i + 1), credit=0.0, notes="Paid by cheque" if i % 5 == 0 else None,
        )
        for i in range(rows)
    ]
    return _build_statement_html(
        ledger=_ledger(), company=_company(), from_date=date(2025, 4, 1), to_date=date(2026, 3, 31),
        opening_balance=1234567.89, period_debit=9876543.21, period_credit=1234567.89,
        closing_balance=9876543.21, entries=entries, paper=paper,
    )


def _day_book_html(paper: str, rows: int = 40) -> str:
    entries = [
        DayBookEntry(
            entry_id=i, entry_type="invoice", date=datetime(2025, 4, 1 + i % 28), voucher_type="Sales",
            reference_number=f"INV-2025-{i:04d}", ledger_name="Acme Stores and Associates",
            particulars="Sales Invoice with a fairly long particulars text", debit=123456.78, credit=0.0,
        )
        for i in range(rows)
    ]
    return _build_day_book_html(
        company=_company(), from_date=date(2025, 4, 1), to_date=date(2025, 4, 30), entries=entries,
        total_debit=1234567.89, total_credit=234567.89, paper=paper,
    )


def _tax_ledger_html(paper: str, rows: int = 40) -> str:
    entries = [
        TaxLedgerEntry(
            entry_id=i, entry_type="invoice", date=datetime(2025, 4, 1 + i % 28), voucher_type="Sales",
            source_voucher_type="sales", reference_number=f"INV-2025-{i:04d}",
            ledger_name="Acme Stores and Associates Trading Company", ledger_gst="29ABCDE1234F1ZW",
            particulars="x", gst_rate=18, taxable_amount=1234567.89,
            debit_taxable=1234567.89, debit_cgst=111111.11, debit_sgst=111111.11, debit_igst=0,
            debit_total_tax=222222.22, credit_cgst=0, credit_sgst=0, credit_igst=0, credit_total_tax=0,
        )
        for i in range(rows)
    ]
    return _build_tax_ledger_pdf_html(
        company=_company(), from_date=date(2025, 4, 1), to_date=date(2025, 4, 30), entries=entries,
        totals=_build_tax_ledger_totals(entries), liability=TaxLiability(output_tax=1.0), currency="INR",
        paper=paper,
    )


def _worksheet() -> Gstr3bWorksheetOut:
    lines = (InvoiceLine(
        gst_rate=Decimal("18"), taxable=Decimal("100000"), tax=Decimal("18000"),
        cgst=Decimal("9000"), sgst=Decimal("9000"), igst=Decimal("0"),
    ),)
    invoices = [
        InvoiceDoc(
            id=i, number=f"INV-{i}", voucher_type="sales", status="active", ledger_gst="27AAPFU0939F1ZV",
            lines=lines, invoice_discount=Decimal("0"), invoice_date=datetime(2026, 6, 10), place_of_supply=None,
        )
        for i in range(1, 4)
    ]
    period = resolve_return_period(date(2026, 6, 1), date(2026, 6, 30))
    return build_worksheet(period, invoices, [], company_gstin="27AAPFU0939F1ZV")


def _gstr3b_html(paper: str) -> str:
    return build_gstr3b_worksheet_html(
        _worksheet(), company_name="Respawn Pvt Ltd", company_gstin="27AAPFU0939F1ZV",
        generated_at=datetime(2026, 7, 1, 9, 30), paper=paper,
    )


BUILDERS = {
    "statement": _statement_html,
    "day_book": _day_book_html,
    "tax_ledger": _tax_ledger_html,
    "gstr3b": _gstr3b_html,
}


def _document(html: str):
    return weasyprint.HTML(string=html).render()


def _walk(box):
    yield box
    for child in getattr(box, "children", ()) or ():
        yield from _walk(child)


def _expected_mm(report: str, paper: str) -> tuple[float, float]:
    width, height = SIZES_MM[paper]
    return (height, width) if report == "gstr3b" else (width, height)


def _assert_page_size(document, expected_mm: tuple[float, float]) -> None:
    for page in document.pages:
        assert page.width == pytest.approx(expected_mm[0] * PX_PER_MM, abs=0.5 * PX_PER_MM)
        assert page.height == pytest.approx(expected_mm[1] * PX_PER_MM, abs=0.5 * PX_PER_MM)


def _assert_nothing_past_the_right_edge(document) -> None:
    for page in document.pages:
        limit = page.width + 0.5
        for box in _walk(page._page_box):
            right = box.position_x + box.margin_width()
            assert right <= limit, f"{type(box).__name__} {getattr(box, 'element_tag', '')} ends at {right}px, page is {page.width}px"


@pytest.mark.parametrize("report", sorted(BUILDERS))
@pytest.mark.parametrize("paper", ["a4", "a5"])
def test_page_size_follows_the_paper(report, paper):
    document = _document(BUILDERS[report](paper))

    assert document.pages
    _assert_page_size(document, _expected_mm(report, paper))


@pytest.mark.parametrize("report", sorted(BUILDERS))
def test_a5_content_stays_inside_the_page(report):
    document = _document(BUILDERS[report]("a5"))

    _assert_nothing_past_the_right_edge(document)


@pytest.mark.parametrize("report", sorted(BUILDERS))
def test_a4_carries_no_a5_styles(report):
    assert "A5" not in BUILDERS[report]("a4")


def test_gstr3b_a5_keeps_its_page_header_and_footer():
    html = _gstr3b_html("a5")

    assert "@top-center" in html and "@bottom-right" in html
    assert "size: A5 landscape" in html
    assert "size: A4" not in html


def test_render_pdf_makes_a_pdf():
    assert render_pdf(_statement_html("a5", rows=3), "a5").startswith(b"%PDF")


# --- routes -----------------------------------------------------------------


@pytest.fixture
def seeded(db_session):
    user = User(id=1, email="test@example.com", full_name="Test Admin", hashed_password="x", role=UserRole.admin)
    db_session.add_all([user, _company(), _ledger()])
    db_session.commit()


PERIOD = {"from_date": "2026-06-01", "to_date": "2026-06-30"}
ROUTES = [
    "/api/ledgers/day-book/pdf",
    "/api/ledgers/1/statement/pdf",
    "/api/ledgers/tax-ledger/pdf",
    "/api/ledgers/tax-ledger/gstr1/export-pdf",
    "/api/ledgers/tax-ledger/gstr3b/export-pdf",
]


@pytest.mark.parametrize("path", ROUTES)
@pytest.mark.parametrize("paper", ["thermal80", "thermal58", "letter"])
def test_report_routes_reject_a_roll_or_unknown_paper(client, seeded, path, paper):
    response = client.get(path, params={**PERIOD, "paper": paper})

    assert response.status_code == 422


@pytest.mark.parametrize("path", ROUTES)
@pytest.mark.parametrize("paper", ["a4", "a5"])
def test_report_routes_return_a_pdf_for_a4_and_a5(client, seeded, path, paper):
    response = client.get(path, params={**PERIOD, "paper": paper})

    assert response.status_code == 200, response.text
    assert response.headers["content-type"] == "application/pdf"
    assert response.content.startswith(b"%PDF")


@pytest.mark.parametrize("path", [p for p in ROUTES if "statement" not in p])
def test_report_routes_lay_out_for_the_requested_paper(client, seeded, monkeypatch, path):
    """The route hands the builder's HTML and the resolved paper to render_pdf."""
    import src.api.routes.gstr3b as gstr3b_routes

    seen = []

    def spy(html, paper="a4"):
        seen.append((html, paper))
        return b"%PDF-spy"

    monkeypatch.setattr(ledgers_routes, "render_pdf", spy)
    monkeypatch.setattr(gstr3b_routes, "render_pdf", spy)

    for requested, expected in (("a5", "a5"), (None, "a4")):
        seen.clear()
        params = dict(PERIOD)
        if requested:
            params["paper"] = requested
        assert client.get(path, params=params).status_code == 200
        ((html, paper),) = seen
        assert paper == expected
        assert ("size: A5" in html) == (expected == "a5")


def test_gstr1_a5_html_fits_the_page(client, seeded, monkeypatch):
    seen = []
    monkeypatch.setattr(ledgers_routes, "render_pdf", lambda html, paper="a4": seen.append((html, paper)) or b"%PDF")

    response = client.get("/api/ledgers/tax-ledger/gstr1/export-pdf", params={**PERIOD, "paper": "a5"})

    assert response.status_code == 200
    ((html, _paper),) = seen
    document = _document(html)
    _assert_page_size(document, SIZES_MM["a5"])
    _assert_nothing_past_the_right_edge(document)


def test_company_default_paper_applies_when_no_paper_is_requested(client, seeded, db_session, monkeypatch):
    company = db_session.get(CompanyProfile, 1)
    if not hasattr(company, "default_pdf_paper"):
        pytest.skip("company default paper is not in this tree yet")
    company.default_pdf_paper = "a5"
    db_session.commit()
    seen = []
    monkeypatch.setattr(ledgers_routes, "render_pdf", lambda html, paper="a4": seen.append(paper) or b"%PDF")

    assert client.get("/api/ledgers/day-book/pdf", params=PERIOD).status_code == 200
    assert seen == ["a5"]
