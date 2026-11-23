import pytest

from src.services.pdf_templates import _build_multi_copy_invoice_html, _build_quotation_html
from src.services.pdf_templates.builders import _fmt_currency
from src.services.pdf_templates.thermal_template import build_thermal_copies, thermal_invoice_doc, thermal_quotation_doc
from tests.services.test_pdf_paper import _products, make_invoice
from tests.services.test_quotation_pdf_template import PRODUCT, make_quotation


@pytest.mark.parametrize("currency,symbol", [(None, "₹"), ("", "₹"), ("  ", "₹"), ("INR", "₹"), ("USD", "$"), ("EUR", "€")])
def test_currency_formatter_uses_inr_only_when_unconfigured(currency, symbol):
    assert _fmt_currency(1234.5, currency) == f"{symbol}1,234.50"


@pytest.mark.parametrize("paper", ["a4", "a5", "thermal80", "thermal58"])
@pytest.mark.parametrize("kind", ["sales", "purchase", "quotation", "proforma"])
@pytest.mark.parametrize("currency,symbol", [(None, "₹"), ("", "₹"), ("  ", "₹"), ("USD", "$")])
def test_transaction_templates_preserve_configured_currency_and_default_to_inr(paper, kind, currency, symbol):
    if kind in ("sales", "purchase"):
        doc = make_invoice(1, voucher_type=kind)
        doc.company_currency_code = currency
        html = (build_thermal_copies([thermal_invoice_doc(doc, _products())], paper)
                if paper.startswith("thermal") else
                _build_multi_copy_invoice_html(doc, _products(), [], copies=1, paper=paper))
    else:
        doc = make_quotation(document_type=kind, company_currency_code=currency)
        html = (build_thermal_copies([thermal_quotation_doc(doc, [PRODUCT])], paper)
                if paper.startswith("thermal") else
                _build_quotation_html(doc, [PRODUCT], paper=paper))
    if isinstance(html, list):
        html = "".join(html)
    assert symbol in html
    assert ("$" if symbol == "₹" else "₹") not in html
