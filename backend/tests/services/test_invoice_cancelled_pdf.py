"""All invoice paper sizes retain a visible cancellation mark and India date."""

from datetime import datetime

import pytest

from src.services.pdf_templates.invoice_template import _build_invoice_html
from src.services.pdf_templates.thermal_template import build_thermal_copies, thermal_invoice_doc
from test_purchase_pdf_template import make_purchase_invoice


@pytest.mark.parametrize("voucher", ["sales", "purchase"])
@pytest.mark.parametrize("paper", ["a4", "a5", "thermal80", "thermal58"])
@pytest.mark.parametrize("cancelled_at", [None, datetime(2026, 11, 20, 20, 0)])
def test_cancelled_invoice_is_marked_without_payment_qr(voucher, paper, cancelled_at):
    invoice = make_purchase_invoice()
    invoice.voucher_type = voucher
    invoice.status = "cancelled"
    invoice.cancelled_at = cancelled_at
    if paper.startswith("thermal"):
        doc = thermal_invoice_doc(invoice, [], qr_uri="PAYMENT-QR")
        html = build_thermal_copies([doc], paper)[0]
    else:
        html = _build_invoice_html(invoice, [], paper=paper, pay_qr_html="PAYMENT-QR")
    assert "Cancelled" in html
    assert "Cancelled invoice total" in html
    assert "Total due" not in html
    assert "PAYMENT-QR" not in html
    if cancelled_at:
        assert "Cancelled on 21 Nov 2026 (IST)" in html
        assert "20 Nov 2026" not in html
    else:
        assert "Cancelled on" not in html


def test_active_invoice_is_not_marked_and_keeps_payment_qr():
    invoice = make_purchase_invoice()
    invoice.voucher_type = "sales"
    invoice.status = "active"
    html = _build_invoice_html(invoice, [], pay_qr_html="PAYMENT-QR")
    assert "Cancelled" not in html
    assert "Total due" in html
    assert "PAYMENT-QR" in html
