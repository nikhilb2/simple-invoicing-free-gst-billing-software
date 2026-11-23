"""A cancelled thermal document prints the India date of cancelled_at, not the UTC one.

The fixtures come from the A4 template tests for each document, so the thermal
output is checked against the same records.
"""
from datetime import datetime

import pytest

from src.services.pdf_templates.thermal_template import (
    build_thermal_copies,
    thermal_challan_doc,
    thermal_credit_note_doc,
    thermal_quotation_doc,
)
from test_credit_note_pdf_template import make_note
from test_delivery_challan_pdf_template import make_challan
from test_quotation_pdf_template import make_quotation

# 20:00 UTC on 20 Nov is 01:30 IST on 21 Nov.
CANCELLED_AT_UTC = datetime(2026, 11, 20, 20, 0)


@pytest.mark.parametrize("paper", ["thermal80", "thermal58"])
def test_thermal_credit_note_cancelled_date_is_the_india_date(paper):
    note, invoices, products, ledger = make_note(status="cancelled")
    note.cancelled_at = CANCELLED_AT_UTC
    html = build_thermal_copies([thermal_credit_note_doc(note, invoices, products, None, ledger)], paper)[0]
    assert "Cancelled on 21 Nov 2026" in html
    assert "20 Nov 2026" not in html


@pytest.mark.parametrize("paper", ["thermal80", "thermal58"])
def test_thermal_delivery_challan_cancelled_date_is_the_india_date(paper):
    challan = make_challan(status="cancelled", cancelled_at=CANCELLED_AT_UTC)
    html = build_thermal_copies([thermal_challan_doc(challan, [], copy_label="Original")], paper)[0]
    assert "Cancelled on 21 Nov 2026" in html
    assert "20 Nov 2026" not in html


@pytest.mark.parametrize("paper", ["thermal80", "thermal58"])
def test_thermal_quotation_cancelled_date_is_the_india_date(paper):
    quotation = make_quotation(status="cancelled", cancelled_at=CANCELLED_AT_UTC)
    html = build_thermal_copies([thermal_quotation_doc(quotation, [])], paper)[0]
    assert "Cancelled on 21 Nov 2026" in html
    assert "20 Nov 2026" not in html
