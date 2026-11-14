"""Unit tests for the INR money formatter used by PDF templates.

Covers the float-precision rounding bug that could drop a rupee from totals
(see issue #791).
"""

from src.services.pdf_templates.ledger_template import _fmt_inr
from src.api.routes.payments import _fmt_amt
from src.services.pdf_templates.builders import _fmt_currency

def test_fmt_inr_rounds_float_just_below_whole_rupee():
    # 6490.999999999999 must not become ₹6,490.00
    assert _fmt_inr(6490.999999999999) == "₹6,491.00"


def test_fmt_inr_indian_grouping_with_carry():
    assert _fmt_inr(166506.99999999997) == "₹1,66,507.00"


def test_fmt_inr_negative_balance():
    assert _fmt_inr(-1234.56) == "-₹1,234.56"


def test_fmt_inr_tiny_negative_residue_does_not_show_minus_zero():
    # A float residue that rounds to zero must not print as -₹0.00
    assert _fmt_inr(-0.0000001) == "₹0.00"
    assert _fmt_inr(-0.004) == "₹0.00"
    assert _fmt_inr(-0.005) == "-₹0.01"  # ROUND_HALF_UP


def test_fmt_inr_zero_and_positive():
    assert _fmt_inr(0.0) == "₹0.00"
    assert _fmt_inr(1000) == "₹1,000.00"
    assert _fmt_inr(1234567.89) == "₹12,34,567.89"


def test_fmt_inr_non_inr_currency():
    assert _fmt_inr(1234.5, currency="USD") == "1,234.50 USD"

def test_fmt_currency_inr_indian_grouping_and_negative_sign():
    assert _fmt_currency(1234567.5, "INR") == "₹12,34,567.50"
    assert _fmt_currency(-500, "INR") == "-₹500.00"
    assert _fmt_currency(-1234567.5, "INR") == "-₹12,34,567.50"


def test_fmt_currency_non_inr_preserves_western_grouping():
    assert _fmt_currency(1234567.5, "USD") == "$1,234,567.50"
    assert _fmt_currency(1234567.5, "EUR") == "€1,234,567.50"
    assert _fmt_currency(1234567.5, "GBP") == "£1,234,567.50"
    assert _fmt_currency(1234567.5) == "$1,234,567.50"


def test_fmt_amt_inr_indian_grouping_and_negative_sign():
    assert _fmt_amt(1234567.5, "INR") == "₹12,34,567.50"
    assert _fmt_amt(-500, "INR") == "-₹500.00"
    assert _fmt_amt(1234567.5) == "₹12,34,567.50"
    assert _fmt_amt(1234567.5, "USD") == "$1,234,567.50"