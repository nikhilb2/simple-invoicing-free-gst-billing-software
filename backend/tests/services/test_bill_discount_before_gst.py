"""The bill discount comes off the taxable value, before GST (#1154).

The worked examples from the issue, through the real processor, then the reporting
helpers, the PDFs (A4, A5, thermal) and the rule that an after-GST document keeps
its old arithmetic. ``frontend/src/utils/invoiceTotals.test.ts`` checks the composer's
preview against the same figures.
"""

import re
from datetime import datetime
from decimal import Decimal

import pytest
from fastapi import HTTPException

from src.models.buyer import Buyer
from src.models.company import CompanyProfile
from src.models.inventory import Inventory
from src.models.invoice import Invoice
from src.models.product import Product
from src.models.user import User, UserRole
from src.schemas.invoice import InvoiceCreate, InvoiceItemCreate
from src.services.document_totals import resolve_discount_mode
from src.services.invoice_discounts import (
    bill_discount_total,
    build_invoice_discount_totals,
    discounted_line_amounts,
    invoice_discount_amount,
    item_discount_amount,
)
from src.services.invoice_processor import InvoiceProcessor
from src.services.pdf_templates.invoice_template import _build_invoice_html
from src.services.pdf_templates.thermal_template import _build_thermal_html, thermal_invoice_doc

SELLER = "27AAACM1234A1Z5"
BUYER_SAME_STATE = "27ABCDE1234F1Z0"
BUYER_OTHER_STATE = "29ABCDE1234F1Z0"


@pytest.fixture
def processor(db_session):
    return InvoiceProcessor(db_session)


@pytest.fixture
def ledger(db_session):
    db_session.add_all([
        User(email="admin@test.com", full_name="Admin", hashed_password="x", role=UserRole.admin),
        CompanyProfile(name="Meera Sweets (demo)", address="Pune", gst=SELLER, phone_number="1", currency_code="INR"),
    ])
    buyer = Buyer(name="Demo Customer", address="Pune", gst=BUYER_SAME_STATE, phone_number="2")
    db_session.add(buyer)
    db_session.flush()
    return buyer


def _product(db_session, name, gst_rate, price=100.0):
    product = Product(sku=name.upper().replace(" ", "-"), name=name, price=price, gst_rate=gst_rate)
    db_session.add(product)
    db_session.flush()
    db_session.add(Inventory(product_id=product.id, quantity=100))
    db_session.flush()
    return product


def _apply(db_session, processor, ledger, *, lines, mode=None, **fields):
    """``lines`` are (product, quantity, unit price, extra line fields)."""
    invoice = Invoice(total_amount=0, created_by=1, invoice_date=datetime(2026, 11, 28))
    if mode:
        invoice.discount_mode = mode
    db_session.add(invoice)
    db_session.flush()
    payload = InvoiceCreate(
        ledger_id=ledger.id,
        voucher_type="sales",
        items=[
            InvoiceItemCreate(product_id=product.id, quantity=quantity, unit_price=price, **extra)
            for product, quantity, price, extra in lines
        ],
        **fields,
    )
    processor.apply_payload(invoice, payload, created_by=1, regenerate_number=False)
    db_session.flush()
    db_session.refresh(invoice)
    return invoice


def _f(value) -> float:
    return float(value)


def _lines(invoice):
    return sorted(invoice.items, key=lambda item: item.id)


class TestWorkedExamples:
    def test_one_line_flat(self, db_session, processor, ledger):
        hamper = _product(db_session, "Demo Gift Hamper", 18, 300)
        invoice = _apply(db_session, processor, ledger, lines=[(hamper, 1, 300, {})], discount_type="net", discount_value=50)

        assert invoice.discount_mode == "before_tax"
        assert (_f(invoice.taxable_amount), _f(invoice.cgst_amount), _f(invoice.sgst_amount)) == (250.0, 22.5, 22.5)
        assert (_f(invoice.total_tax_amount), _f(invoice.total_amount)) == (45.0, 295.0)
        line = invoice.items[0]
        assert (_f(line.bill_discount_amount), _f(line.taxable_amount), _f(line.line_total)) == (50.0, 250.0, 295.0)
        assert (invoice.discount_type, _f(invoice.discount_value)) == ("net", 50.0)

    def test_one_line_percentage_with_round_off(self, db_session, processor, ledger):
        hamper = _product(db_session, "Demo Gift Hamper", 18, 300)
        invoice = _apply(
            db_session, processor, ledger, lines=[(hamper, 1, 300, {})],
            discount_type="percentage", discount_value=10, apply_round_off=True,
        )

        assert _f(invoice.items[0].bill_discount_amount) == 30.0
        assert (_f(invoice.taxable_amount), _f(invoice.cgst_amount), _f(invoice.sgst_amount)) == (270.0, 24.3, 24.3)
        # 318.60 rounds half-up to the nearest rupee, as every round off does today.
        assert (_f(invoice.round_off_amount), _f(invoice.total_amount)) == (0.4, 319.0)

    def test_mixed_rates(self, db_session, processor, ledger):
        atta = _product(db_session, "Demo Atta 5kg", 5, 200)
        hamper = _product(db_session, "Demo Gift Hamper", 18, 100)
        invoice = _apply(
            db_session, processor, ledger, lines=[(atta, 1, 200, {}), (hamper, 1, 100, {})],
            discount_type="net", discount_value=50, apply_round_off=True,
        )

        first, second = _lines(invoice)
        assert (_f(first.bill_discount_amount), _f(second.bill_discount_amount)) == (33.33, 16.67)
        assert (_f(first.taxable_amount), _f(second.taxable_amount)) == (166.67, 83.33)
        assert (_f(first.cgst_amount), _f(first.sgst_amount)) == (4.17, 4.17)
        assert (_f(second.cgst_amount), _f(second.sgst_amount)) == (7.5, 7.5)
        assert (_f(invoice.taxable_amount), _f(invoice.cgst_amount), _f(invoice.sgst_amount)) == (250.0, 11.67, 11.67)
        assert (_f(invoice.round_off_amount), _f(invoice.total_amount)) == (-0.34, 273.0)

    def test_mixed_rates_after_gst_is_what_it_was(self, db_session, processor, ledger):
        atta = _product(db_session, "Demo Atta 5kg", 5, 200)
        hamper = _product(db_session, "Demo Gift Hamper", 18, 100)
        invoice = _apply(
            db_session, processor, ledger, mode="after_tax", lines=[(atta, 1, 200, {}), (hamper, 1, 100, {})],
            discount_type="net", discount_value=50, apply_round_off=True,
        )
        assert invoice.discount_mode == "after_tax"
        assert (_f(invoice.taxable_amount), _f(invoice.total_tax_amount), _f(invoice.total_amount)) == (300.0, 28.0, 278.0)
        assert all(_f(item.bill_discount_amount) == 0 for item in invoice.items)

    def test_remainder_paisa_goes_on_the_first_of_equal_lines(self, db_session, processor, ledger):
        products = [_product(db_session, f"Demo Item {n}", 18) for n in range(3)]
        invoice = _apply(
            db_session, processor, ledger, lines=[(product, 1, 100, {}) for product in products],
            discount_type="net", discount_value=100,
        )
        assert [_f(item.bill_discount_amount) for item in _lines(invoice)] == [33.34, 33.33, 33.33]
        assert _f(invoice.taxable_amount) == 200.0

    def test_inter_state(self, db_session, processor, ledger):
        ledger.gst = BUYER_OTHER_STATE
        db_session.flush()
        hamper = _product(db_session, "Demo Gift Hamper", 18, 300)
        invoice = _apply(db_session, processor, ledger, lines=[(hamper, 1, 300, {})], discount_type="net", discount_value=50)

        assert (_f(invoice.igst_amount), _f(invoice.cgst_amount), _f(invoice.total_amount)) == (45.0, 0.0, 295.0)

    def test_line_discount_then_bill_discount(self, db_session, processor, ledger):
        hamper = _product(db_session, "Demo Gift Hamper", 18, 300)
        invoice = _apply(
            db_session, processor, ledger,
            lines=[(hamper, 1, 300, {"discount_type": "percentage", "discount_value": 10})],
            discount_type="net", discount_value=50,
        )
        line = invoice.items[0]
        assert (_f(line.bill_discount_amount), _f(invoice.taxable_amount)) == (50.0, 220.0)
        assert (_f(invoice.total_tax_amount), _f(invoice.total_amount)) == (39.6, 259.6)
        # The line's own discount stays its own: the bill's share is not part of it.
        assert item_discount_amount(line, tax_inclusive=False) == Decimal("30.00")

    def test_no_discount_is_as_today(self, db_session, processor, ledger):
        hamper = _product(db_session, "Demo Gift Hamper", 18, 300)
        invoice = _apply(db_session, processor, ledger, lines=[(hamper, 1, 300, {})])
        assert (_f(invoice.taxable_amount), _f(invoice.total_tax_amount), _f(invoice.total_amount)) == (300.0, 54.0, 354.0)
        assert _f(invoice.items[0].bill_discount_amount) == 0.0

    def test_a_discount_equal_to_the_subtotal_is_allowed(self, db_session, processor, ledger):
        hamper = _product(db_session, "Demo Gift Hamper", 18, 300)
        invoice = _apply(db_session, processor, ledger, lines=[(hamper, 1, 300, {})], discount_type="net", discount_value=300)
        assert (_f(invoice.taxable_amount), _f(invoice.total_amount)) == (0.0, 0.0)
        full = _apply(db_session, processor, ledger, lines=[(hamper, 1, 300, {})], discount_type="percentage", discount_value=100)
        assert _f(full.total_amount) == 0.0

    def test_a_discount_over_the_subtotal_is_refused(self, db_session, processor, ledger):
        hamper = _product(db_session, "Demo Gift Hamper", 18, 300)
        with pytest.raises(HTTPException) as refused:
            _apply(db_session, processor, ledger, lines=[(hamper, 1, 300, {})], discount_type="net", discount_value=350)
        assert refused.value.status_code == 400
        assert refused.value.detail == "The discount (₹350.00) is more than the subtotal (₹300.00)."

    def test_price_already_includes_gst(self, db_session, processor, ledger):
        """#611 inclusive prices: the discount still comes off the ex-GST value."""
        hamper = _product(db_session, "Demo Gift Hamper", 18, 354)
        invoice = _apply(
            db_session, processor, ledger, lines=[(hamper, 1, 354, {})],
            tax_inclusive=True, discount_type="net", discount_value=50,
        )
        assert (_f(invoice.taxable_amount), _f(invoice.total_tax_amount), _f(invoice.total_amount)) == (250.0, 45.0, 295.0)

    def test_price_already_includes_gst_with_halves_and_a_shifted_paisa(self, db_session, processor, ledger):
        """999 inclusive at 18% intrastate is 846.62 + 152.38; 10% comes off 846.62."""
        phone = _product(db_session, "Demo Phone", 18, 999)
        invoice = _apply(
            db_session, processor, ledger, lines=[(phone, 1, 999, {})],
            tax_inclusive=True, discount_type="percentage", discount_value=10,
        )
        line = invoice.items[0]
        # 846.62 x 10% = 84.662 -> 84.66; 761.96 taxable; CGST = SGST = 68.58.
        assert (_f(line.bill_discount_amount), _f(line.taxable_amount)) == (84.66, 761.96)
        assert (_f(line.cgst_amount), _f(line.sgst_amount), _f(invoice.total_amount)) == (68.58, 68.58, 899.12)


class TestModes:
    def test_new_documents_are_before_gst_and_cannot_ask_for_after(self):
        assert resolve_discount_mode(None, None, creating=True) == "before_tax"
        assert resolve_discount_mode(None, "before_tax", creating=True) == "before_tax"
        with pytest.raises(HTTPException) as refused:
            resolve_discount_mode(None, "after_tax", creating=True)
        assert (refused.value.status_code, refused.value.detail) == (422, "New documents take the discount before GST.")

    def test_an_edit_keeps_or_switches_forward_only(self):
        assert resolve_discount_mode("after_tax", None, creating=False) == "after_tax"
        assert resolve_discount_mode("after_tax", "after_tax", creating=False) == "after_tax"
        assert resolve_discount_mode("after_tax", "before_tax", creating=False) == "before_tax"
        assert resolve_discount_mode("before_tax", None, creating=False) == "before_tax"
        with pytest.raises(HTTPException) as refused:
            resolve_discount_mode("before_tax", "after_tax", creating=False)
        assert refused.value.status_code == 422

    def test_editing_an_old_invoice_without_switching_gives_the_old_figures(self, db_session, processor, ledger):
        hamper = _product(db_session, "Demo Gift Hamper", 18, 300)
        invoice = _apply(db_session, processor, ledger, mode="after_tax", lines=[(hamper, 1, 300, {})], discount_type="net", discount_value=50)
        assert (invoice.discount_mode, _f(invoice.total_amount)) == ("after_tax", 304.0)


class TestReportingHelpers:
    def test_before_gst_needs_no_inverting(self, db_session, processor, ledger):
        hamper = _product(db_session, "Demo Gift Hamper", 18, 300)
        invoice = _apply(db_session, processor, ledger, lines=[(hamper, 1, 300, {})], discount_type="net", discount_value=50)

        # The after-GST inversion finds nothing to share again: credit notes, the 3B
        # warning and the analytics apportioning all stop by themselves.
        assert invoice_discount_amount(invoice) == Decimal("0.00")
        lines = discounted_line_amounts(invoice, include_round_off=True)
        assert (lines[invoice.items[0].id].taxable_amount, lines[invoice.items[0].id].tax_amount) == (Decimal("250.00"), Decimal("45.00"))
        # "Discount Given" still reports it.
        assert bill_discount_total(invoice) == Decimal("50.00")
        summary = build_invoice_discount_totals(db_session, [invoice])[invoice.id]
        assert (summary.invoice_discount_amount, summary.total_discount) == (Decimal("50.00"), Decimal("50.00"))

    def test_after_gst_discount_given_is_unchanged(self, db_session, processor, ledger):
        hamper = _product(db_session, "Demo Gift Hamper", 18, 300)
        invoice = _apply(db_session, processor, ledger, mode="after_tax", lines=[(hamper, 1, 300, {})], discount_type="net", discount_value=50)
        assert bill_discount_total(invoice) == Decimal("50.00")
        summary = build_invoice_discount_totals(db_session, [invoice])[invoice.id]
        assert summary.total_discount == Decimal("50.00")


def _text(html: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", html))


class TestPdf:
    @pytest.mark.parametrize("paper", ["a4", "a5"])
    def test_a4_and_a5_name_the_share_and_put_the_discount_before_the_gst(self, db_session, processor, ledger, paper):
        hamper = _product(db_session, "Demo Gift Hamper", 18, 300)
        invoice = _apply(db_session, processor, ledger, lines=[(hamper, 1, 300, {})], discount_type="net", discount_value=50)
        html = _build_invoice_html(invoice, [hamper], [], paper=paper)

        assert '<span class="muted-text">Bill discount: -₹50.00 (taxable ₹250.00)</span>' in html
        assert "<p><b>Taxable value: ₹250.00</b></p>" in html
        totals = _text(html.split('<p class="eyebrow">Tax breakup</p>')[1].split("Authorized by")[0])
        order = ["Subtotal: ₹300.00", "Discount: -₹50.00", "Taxable value: ₹250.00", "CGST: ₹22.50", "SGST: ₹22.50",
                 "Total tax: ₹45.00", "Total due", "₹295.00"]
        positions = [totals.index(label) for label in order]
        assert positions == sorted(positions), totals
        assert "Taxable: " not in totals

    def test_a_percentage_is_named_and_round_off_follows(self, db_session, processor, ledger):
        atta = _product(db_session, "Demo Atta 5kg", 5, 200)
        hamper = _product(db_session, "Demo Gift Hamper", 18, 100)
        invoice = _apply(
            db_session, processor, ledger, lines=[(atta, 1, 200, {}), (hamper, 1, 100, {})],
            discount_type="percentage", discount_value=10, apply_round_off=True,
        )
        totals = _text(_build_invoice_html(invoice, [atta, hamper], []).split('<p class="eyebrow">Tax breakup</p>')[1])
        order = ["Subtotal: ₹300.00", "Discount (10%): -₹30.00", "Taxable value: ₹270.00", "Total tax:", "Round off:", "Total due"]
        positions = [totals.index(label) for label in order]
        assert positions == sorted(positions), totals

    def test_after_gst_prints_as_before(self, db_session, processor, ledger):
        hamper = _product(db_session, "Demo Gift Hamper", 18, 300)
        invoice = _apply(db_session, processor, ledger, mode="after_tax", lines=[(hamper, 1, 300, {})], discount_type="net", discount_value=50)
        html = _build_invoice_html(invoice, [hamper], [])
        assert "Bill discount" not in html and "Subtotal" not in html
        totals = _text(html.split('<p class="eyebrow">Tax breakup</p>')[1])
        order = ["Taxable: ₹300.00", "CGST: ₹27.00", "SGST: ₹27.00", "Total tax: ₹54.00", "Discount: -₹50.00", "₹304.00"]
        positions = [totals.index(label) for label in order]
        assert positions == sorted(positions), totals

    def test_before_gst_with_no_discount_prints_as_today(self, db_session, processor, ledger):
        hamper = _product(db_session, "Demo Gift Hamper", 18, 300)
        invoice = _apply(db_session, processor, ledger, lines=[(hamper, 1, 300, {})])
        html = _build_invoice_html(invoice, [hamper], [])
        assert "<p>Taxable: ₹300.00</p>" in html and "Subtotal" not in html and "Bill discount" not in html

    def test_thermal(self, db_session, processor, ledger):
        hamper = _product(db_session, "Demo Gift Hamper", 18, 300)
        invoice = _apply(db_session, processor, ledger, lines=[(hamper, 1, 300, {})], discount_type="net", discount_value=50)
        doc = thermal_invoice_doc(invoice, [hamper])

        # The item before GST and before its share, so the items add up to the Subtotal.
        assert [(item.price, item.amount) for item in doc.items] == [(300.0, 300.0)]
        assert doc.tax_rows == [(18.0, 250.0, 22.5, 22.5)]
        assert [label for label, _ in doc.totals] == ["Subtotal", "Discount", "Taxable value", "CGST", "SGST"]
        assert [value for _, value in doc.totals] == [300.0, -50.0, 250.0, 22.5, 22.5]
        assert doc.grand_total == 295.0
        html = _build_thermal_html(doc, 80)
        assert "Bill discount" not in html and "₹295.00" in html

    def test_thermal_after_gst_is_unchanged(self, db_session, processor, ledger):
        hamper = _product(db_session, "Demo Gift Hamper", 18, 300)
        invoice = _apply(db_session, processor, ledger, mode="after_tax", lines=[(hamper, 1, 300, {})], discount_type="net", discount_value=50)
        doc = thermal_invoice_doc(invoice, [hamper])
        assert [(item.price, item.amount) for item in doc.items] == [(300.0, 354.0)]
        assert [(label, value) for label, value in doc.totals] == [
            ("Taxable value", 300.0), ("CGST", 27.0), ("SGST", 27.0), ("Discount", -50.0),
        ]
        assert doc.grand_total == 304.0
