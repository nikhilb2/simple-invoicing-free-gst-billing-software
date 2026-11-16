"""The e-way bill service on a delivery challan: document type CHL and a sub-supply from the purpose."""

from datetime import date
from types import SimpleNamespace

import pytest

from src.core.eway_bill_codes import (
    CHALLAN_PURPOSE_SUB_SUPPLY,
    CHALLAN_SUB_SUPPLY_CODES,
    MAX_SUB_SUPPLY_DESC_LENGTH,
)
from src.models.delivery_challan import PURPOSES, DeliveryChallan, DeliveryChallanItem
from src.models.product import Product
from src.schemas.eway_bill import EwayBillFormData
from src.services.eway_bill_service import (
    challan_sub_supply,
    generate_eway_bill_json,
    pre_check,
    validate_form_against_invoice,
    validate_form_data,
    validate_invoice,
)

SELLER_GST = "27AAAAA0000A1Z2"
BUYER_GST = "29AADCB2230M1ZP"


def make_challan(*, purpose="job_work", interstate=True, number="DC-2026-001", **overrides) -> DeliveryChallan:
    item = DeliveryChallanItem(
        id=1,
        product_id=5,
        hsn_sac="84713010",
        quantity=10,
        unit_price=100,
        gst_rate=18,
        taxable_amount=1000,
        tax_amount=180,
        cgst_amount=0 if interstate else 90,
        sgst_amount=0 if interstate else 90,
        igst_amount=180 if interstate else 0,
        line_total=1180,
    )
    fields = dict(
        id=7,
        challan_number=number,
        status="open",
        purpose=purpose,
        challan_date=date(2026, 11, 15),
        company_name="Mofna Traders",
        company_address="1 Market Road\nPune\n411001",
        company_gst=SELLER_GST,
        ledger_name="Acme Sons",
        ledger_address="9 Buyer Lane\nBengaluru\n560001",
        ledger_gst=BUYER_GST if interstate else SELLER_GST,
        taxable_amount=1000,
        total_tax_amount=180,
        cgst_amount=0 if interstate else 90,
        sgst_amount=0 if interstate else 90,
        igst_amount=180 if interstate else 0,
        total_amount=1180,
        items=[item],
    )
    fields.update(overrides)
    return DeliveryChallan(**fields)


PRODUCT = Product(id=5, name="Widget", sku="WID-1", hsn_sac="84713010", price=100, gst_rate=18, unit="Pieces")
COMPANY = SimpleNamespace(
    name="Mofna Traders",
    address="1 Market Road\nPune\n411001",
    gst=SELLER_GST,
    eway_local_threshold=50000,
    eway_interstate_threshold=50000,
)


def valid_form(challan=None, **overrides) -> EwayBillFormData:
    challan = challan or make_challan()
    fields = dict(
        seller_gstin=SELLER_GST,
        seller_trade_name="Mofna Traders",
        seller_address_1="1 Market Road",
        seller_place="Maharashtra",
        seller_state_code="27",
        seller_pincode="411001",
        buyer_gstin=BUYER_GST,
        buyer_trade_name="Acme Sons",
        buyer_address_1="9 Buyer Lane",
        buyer_place="Karnataka",
        buyer_state_code="29",
        buyer_pincode="560001",
        sub_supply_type=challan_sub_supply(challan)[0],
        vehicle_number="MH12AB1234",
        distance_km=840,
    )
    fields.update(overrides)
    return EwayBillFormData(**fields)


# ── Purpose mapping ──


def test_every_purpose_maps_to_a_code_nic_allows_with_a_challan():
    assert set(CHALLAN_PURPOSE_SUB_SUPPLY) == set(PURPOSES)
    for code, desc in CHALLAN_PURPOSE_SUB_SUPPLY.values():
        assert code in CHALLAN_SUB_SUPPLY_CODES
        assert len(desc) <= MAX_SUB_SUPPLY_DESC_LENGTH
        if code == "8":
            assert desc, "NIC needs a description with Others"


@pytest.mark.parametrize(
    "purpose, code, desc",
    [
        ("job_work", "4", ""),
        ("own_use", "5", ""),
        ("exhibition", "12", ""),
        ("skd_ckd_lots", "9", ""),
        ("supply_on_approval", "8", "Supply on approval"),
        ("liquid_gas", "8", "Liquid gas"),
        ("other", "8", "Others"),
    ],
)
def test_challan_sub_supply_from_purpose(purpose, code, desc):
    assert challan_sub_supply(make_challan(purpose=purpose)) == (code, desc)


def test_unknown_purpose_falls_back_to_others():
    assert challan_sub_supply(make_challan(purpose="mystery")) == ("8", "Others")


# ── Pre-check ──


def test_precheck_presets_the_derived_sub_supply_and_labels_it():
    result = pre_check(make_challan(purpose="job_work"), COMPANY, None, make_challan().items, {5: PRODUCT})
    assert result.document_type == "CHL"
    assert result.form_data.sub_supply_type == "4"
    assert result.sub_supply_label == "Job Work"
    assert result.form_data.seller_gstin == SELLER_GST
    assert result.form_data.buyer_gstin == BUYER_GST
    assert result.form_data.seller_pincode == "411001"
    assert result.form_data.buyer_pincode == "560001"
    assert result.valid is True


def test_precheck_label_names_the_others_description():
    challan = make_challan(purpose="supply_on_approval")
    result = pre_check(challan, COMPANY, None, challan.items, {5: PRODUCT})
    assert result.form_data.sub_supply_type == "8"
    assert result.sub_supply_label == "Others (Supply on approval)"


def test_precheck_threshold_note_says_challan():
    challan = make_challan(taxable_amount=100, total_amount=118)
    result = pre_check(challan, COMPANY, None, challan.items, {5: PRODUCT})
    assert result.threshold_warning.startswith("This challan (")


def test_precheck_shipping_address_message_says_challan():
    challan = make_challan(shipping_address="Plot 4, MIDC\nNagpur\n440001")
    result = pre_check(challan, COMPANY, None, challan.items, {5: PRODUCT})
    assert any("challan's shipping address" in m.message for m in result.missing_fields)
    assert result.form_data.transaction_type == "2"


# ── Validation ──


def test_valid_challan_form_has_no_errors():
    challan = make_challan()
    assert validate_invoice(challan, challan.items, {5: PRODUCT}) == []
    assert validate_form_data(valid_form(challan), document_type="CHL") == []
    assert validate_form_against_invoice(valid_form(challan), challan) == []


def test_challan_number_too_long_is_reported_as_a_challan_problem():
    challan = make_challan(number="DC-2026-0000000000001")
    errors = validate_invoice(challan, challan.items, {5: PRODUCT})
    assert [e.field for e in errors] == ["challan_number"]
    assert errors[0].message.startswith("Challan number")


def test_missing_hsn_is_reported():
    challan = make_challan()
    challan.items[0].hsn_sac = None
    errors = validate_invoice(challan, challan.items, {5: Product(id=5, name="Widget", sku="W")})
    assert errors and "missing HSN/SAC" in errors[0].message


def test_services_only_challan_says_challan():
    challan = make_challan()
    challan.items[0].hsn_sac = "998313"
    errors = validate_invoice(challan, challan.items, {5: PRODUCT})
    assert any("This challan only has services" in e.message for e in errors)


def test_challan_accepts_nic_codes_a_tax_invoice_refuses():
    for code in CHALLAN_SUB_SUPPLY_CODES:
        assert validate_form_data(valid_form(sub_supply_type=code), document_type="CHL") == [], code
        errors = validate_form_data(valid_form(sub_supply_type=code))
        if code not in ("9",):
            assert any(e.field == "sub_supply_type" for e in errors), code


def test_challan_refuses_a_sub_supply_outside_its_list():
    for code in ("1", "3", "2", "6", "7"):
        errors = validate_form_data(valid_form(sub_supply_type=code), document_type="CHL")
        # An export code also trips NIC's export rules, which is no concern here.
        sub_errors = [e for e in errors if e.field == "sub_supply_type"]
        assert len(sub_errors) == 1, code
        assert "delivery challan" in sub_errors[0].message


def test_outward_wording_names_the_challan():
    errors = validate_form_data(valid_form(supply_type="I"), document_type="CHL")
    assert errors[0].message == "Supply type must be Outward for a delivery challan."
    invoice_errors = validate_form_data(valid_form(supply_type="I", sub_supply_type="1"))
    assert invoice_errors[0].message == "Supply type must be Outward for a sales invoice."


def test_igst_state_mismatch_says_challan():
    challan = make_challan(interstate=True)
    errors = validate_form_against_invoice(valid_form(challan, buyer_state_code="27"), challan)
    assert errors and errors[0].message.startswith("This challan charges IGST")


def test_transport_doc_date_before_the_challan_date_is_refused():
    challan = make_challan()
    form = valid_form(challan, transport_doc_date="2026-11-14")
    errors = validate_form_against_invoice(form, challan)
    assert errors and "before the challan date" in errors[0].message


# ── Generated JSON ──


@pytest.mark.parametrize(
    "purpose, sub_type, desc",
    [("job_work", 4, ""), ("exhibition", 12, ""), ("liquid_gas", 8, "Liquid gas"), ("other", 8, "Others")],
)
def test_json_is_a_challan_with_the_purpose_sub_supply(purpose, sub_type, desc):
    challan = make_challan(purpose=purpose)
    # The client's value is ignored by the route; the service uses the purpose too.
    form = valid_form(challan, sub_supply_type="1")
    bill = generate_eway_bill_json(challan, challan.items, {5: PRODUCT}, form)["billLists"][0]
    assert bill["docType"] == "CHL"
    assert bill["subSupplyType"] == sub_type
    assert bill["subSupplyDesc"] == desc
    assert bill["docNo"] == "DC-2026-001"
    assert bill["docDate"] == "15/11/2026"
    assert bill["supplyType"] == "O"


def test_json_money_and_items_come_from_the_challan():
    challan = make_challan()
    bill = generate_eway_bill_json(challan, challan.items, {5: PRODUCT}, valid_form(challan))["billLists"][0]
    assert bill["totalValue"] == 1000.0
    assert bill["igstValue"] == 180.0
    assert bill["totInvValue"] == 1180.0
    assert bill["mainHsnCode"] == "84713010"
    item = bill["itemList"][0]
    assert item["quantity"] == 10.0
    assert item["igstRate"] == 18.0 and item["cgstRate"] == 0
    assert item["taxableAmount"] == 1000.0


def test_intra_state_challan_splits_the_rate():
    challan = make_challan(interstate=False)
    form = valid_form(challan, buyer_gstin=SELLER_GST, buyer_state_code="27", buyer_pincode="411002")
    bill = generate_eway_bill_json(challan, challan.items, {5: PRODUCT}, form)["billLists"][0]
    assert bill["cgstValue"] == 90.0 and bill["sgstValue"] == 90.0 and bill["igstValue"] == 0
    assert bill["itemList"][0]["cgstRate"] == 9.0


def test_challan_number_falls_back_to_the_id_in_the_file():
    challan = make_challan(number="")
    bill = generate_eway_bill_json(challan, challan.items, {5: PRODUCT}, valid_form(challan))["billLists"][0]
    assert bill["docNo"] == "7"
