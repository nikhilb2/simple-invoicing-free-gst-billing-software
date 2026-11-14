"""Amount-in-words currency labels are independent of database state."""

import pytest

from src.services.pdf_templates.builders import _amount_in_words_indian


@pytest.mark.parametrize("amount, currency, expected", [
    (1250.50, "INR", "One Thousand Two Hundred Fifty Rupees and Fifty Paise Only"),
    (1250, "INR", "One Thousand Two Hundred Fifty Rupees Only"),
    (0, "INR", "Zero Rupees Only"),
    (0.05, "INR", "Zero Rupees and Five Paise Only"),
    (1.50, None, "One Rupees and Fifty Paise Only"),
    (1.50, "", "One Rupees and Fifty Paise Only"),
    (1250.50, "USD", "One Thousand Two Hundred Fifty USD and 50/100 Only"),
    (99.99, "EUR", "Ninety Nine EUR and 99/100 Only"),
    (0.05, "GBP", "Zero GBP and 05/100 Only"),
    (10.01, "CHF", "Ten CHF and 01/100 Only"),
    (123, "EUR", "One Hundred Twenty Three EUR Only"),
    (0, "USD", "Zero USD Only"),
    (10.004, "USD", "Ten USD Only"),
    (1.999, "USD", "Two USD Only"),
    (12345678.50, "USD", "One Crore Twenty Three Lakh Forty Five Thousand Six Hundred Seventy Eight USD and 50/100 Only"),
])
def test_amount_in_words_currency_fraction(amount, currency, expected):
    assert _amount_in_words_indian(amount, currency) == expected


@pytest.mark.parametrize("document", ["sales", "purchase", "quotation", "credit_note"])
def test_foreign_currency_amount_reaches_document_html(document):
    from decimal import Decimal

    from tests.services.test_credit_note_pdf_template import make_note
    from tests.services.test_purchase_pdf_template import make_purchase_invoice
    from tests.services.test_quotation_pdf_template import make_quotation
    from src.services.pdf_templates import (
        _build_credit_note_html,
        _build_invoice_html,
        _build_purchase_invoice_html,
        _build_quotation_html,
    )

    if document == "quotation":
        quotation = make_quotation(company_currency_code="USD", total_amount=1250.50)
        html = _build_quotation_html(quotation, [], [], today=quotation.quotation_date)
    elif document == "credit_note":
        note, invoices, products, ledger = make_note()
        note.total_amount = Decimal("1250.50")
        invoices[0].company_currency_code = "USD"
        html = _build_credit_note_html(note, invoices, products, None, ledger)
    else:
        invoice = make_purchase_invoice()
        invoice.company_currency_code = "USD"
        invoice.total_amount = Decimal("1250.50")
        if document == "sales":
            invoice.voucher_type = "sales"
            html = _build_invoice_html(invoice, [], [])
        else:
            html = _build_purchase_invoice_html(invoice, [])

    assert "One Thousand Two Hundred Fifty USD and 50/100 Only" in html
    assert "Paise" not in html
