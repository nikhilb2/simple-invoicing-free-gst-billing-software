"""Unit tests for the product unit to GST UQC mapping.

Plain function tests, no database needed.
"""

import pytest

from src.core.eway_bill_codes import NIC_UQC_CODES
from src.services.uqc import HSN_UQC_BY_UNIT, hsn_uqc, uqc_for_unit


@pytest.mark.parametrize("unit, expected", [
    ("Litres", "LTR"),
    ("Liters", "LTR"),
    ("Ltrs", "LTR"),
    ("litre", "LTR"),
    ("Bag", "BAG"),
    ("Bags", "BAG"),
    ("Bottle", "BTL"),
    ("Bottles", "BTL"),
    ("Packet", "PAC"),
    ("Packets", "PAC"),
    ("Quintal", "QTL"),
    ("Tonnes", "TON"),
    ("Meters", "MTR"),
    ("Metres", "MTR"),
    ("Sets", "SET"),
    ("Pairs", "PRS"),
    ("Boxes", "BOX"),
    ("Kilograms", "KGS"),
    ("Cartons", "CTN"),
])
def test_plurals_and_common_spellings_map_to_the_right_code(unit, expected):
    assert uqc_for_unit(unit) == expected


@pytest.mark.parametrize("unit", ["BAG", "CTN", "QTL", "bag", "ctn", "qtl"])
def test_a_unit_that_already_is_a_uqc_code_is_used_as_is(unit):
    assert uqc_for_unit(unit) == unit.strip().upper()


@pytest.mark.parametrize("unit", ["Ounce", "Ounces", "Hours", None, ""])
def test_an_unmapped_unit_falls_back_to_oth_not_nos(unit):
    assert uqc_for_unit(unit) == "OTH"


def test_services_still_file_as_na():
    assert hsn_uqc("998313", "Pieces") == "NA"
    assert hsn_uqc("1508", "Litres") == "LTR"


def test_every_mapped_unit_is_a_valid_nic_code():
    assert set(HSN_UQC_BY_UNIT.values()) <= NIC_UQC_CODES
