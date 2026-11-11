"""Mapping the product master's free-text unit onto a GST unit quantity code (UQC)."""

from src.core.eway_bill_codes import NIC_UQC_CODES

# Table 12 of GSTR-1 and the e-way bill both take UQC from a fixed list, so the
# product master's free-text unit has to be mapped onto it. Anything unmapped falls
# back to OTH (Others), which is on GST's UQC list; NOS would claim the quantity
# is a count, which is wrong for a weight or a volume.
HSN_UQC_BY_UNIT = {
    "pieces": "NOS", "piece": "NOS", "pcs": "PCS", "nos": "NOS", "unit": "UNT",
    "kg": "KGS", "kgs": "KGS", "kilogram": "KGS", "kilograms": "KGS",
    "kilo": "KGS", "kilos": "KGS",
    "g": "GMS", "gm": "GMS", "gram": "GMS", "grams": "GMS",
    "m": "MTR", "metre": "MTR", "meter": "MTR", "mtr": "MTR",
    "metres": "MTR", "meters": "MTR",
    "centimetre": "CMS", "centimeter": "CMS", "centimetres": "CMS",
    "centimeters": "CMS",
    "l": "LTR", "litre": "LTR", "liter": "LTR", "ltr": "LTR",
    "litres": "LTR", "liters": "LTR", "ltrs": "LTR",
    "ml": "MLT", "millilitre": "MLT", "milliliter": "MLT",
    "millilitres": "MLT", "milliliters": "MLT",
    "box": "BOX", "boxes": "BOX", "set": "SET", "sets": "SET",
    "pair": "PRS", "pairs": "PRS", "dozen": "DOZ", "dozens": "DOZ",
    "ton": "TON", "tonne": "TON", "tonnes": "TON",
    "bag": "BAG", "bags": "BAG", "bottle": "BTL", "bottles": "BTL",
    "packet": "PAC", "packets": "PAC", "quintal": "QTL", "quintals": "QTL",
    "carton": "CTN", "cartons": "CTN", "roll": "ROL", "rolls": "ROL",
    "bundle": "BDL", "bundles": "BDL",
}


def uqc_for_unit(unit: str | None) -> str:
    """The UQC for a product's free-text unit.

    A unit that already is a valid UQC code (BAG, CTN, QTL) is used as is.
    Anything else unmapped falls back to OTH.
    """
    key = (unit or "").strip().lower()
    if key in HSN_UQC_BY_UNIT:
        return HSN_UQC_BY_UNIT[key]
    code = (unit or "").strip().upper()
    if code in NIC_UQC_CODES:
        return code
    return "OTH"


def hsn_uqc(hsn: str, unit: str | None) -> str:
    """The UQC to declare for an HSN line of GSTR-1 Table 12."""
    # Services carry no quantity, so the GSTN convention is UQC "NA" with qty 0.
    if hsn.startswith("99"):
        return "NA"
    return uqc_for_unit(unit)
