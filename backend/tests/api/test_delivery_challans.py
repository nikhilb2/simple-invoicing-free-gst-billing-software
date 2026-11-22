"""Delivery challans (#840): create, edit, list, numbering, validation and scoping."""

from datetime import date, timedelta
from types import SimpleNamespace

import pytest
from challan_helpers import (
    GST_KA,
    GST_MH,
    challan_payload,
    create_challan,
    create_ledger,
    create_product,
    get_challan,
    iso_today,
    ok,
    seed_company,
    series_counters,
    update_challan,
)
from test_tenant_isolation import (  # noqa: F401 -- fixtures
    _create_company,
    _create_ledger,
    _create_product,
    _ids,
    _ok,
    _user,
    act_as,
    shared_hosting,
)

from src.models.delivery_challan import DeliveryChallan, PURPOSE_LABELS
from src.models.invoice import Invoice
from src.models.ledger_address import LedgerAddress
from src.services.gst_tax_service import india_today


@pytest.fixture
def setup(client):
    seed_company(client)
    ledger = create_ledger(client)
    product = create_product(client)
    return SimpleNamespace(client=client, ledger=ledger["id"], product=product["id"])


def _post(client, body):
    return client.post("/api/delivery-challans/", json=body)


# ---------------------------------------------------------------------------
# Create
# ---------------------------------------------------------------------------

def test_create_with_defaults(setup):
    s = setup
    challan = create_challan(s.client, s.ledger, [(s.product, 2)])
    year = india_today().year
    assert challan["challan_number"] == f"DC-{year}-001"
    assert challan["status"] == "open"
    assert challan["purpose"] == "supply_on_approval"
    assert challan["purpose_label"] == "Supply on approval"
    assert challan["challan_date"] == iso_today()
    assert challan["financial_year_id"] is not None
    assert challan["age_days"] == 0
    assert challan["ledger_name"] == "Customer One"
    assert challan["ledger_gst"] == GST_MH
    assert challan["company_name"] == "Acme Traders"
    assert challan["company_gst"] == GST_MH
    assert challan["company_currency_code"] == "INR"
    assert challan["place_of_supply"] == "27"
    assert challan["invoice_id"] is None and challan["invoices"] == []

    (item,) = challan["items"]
    assert item["product_name"] == "Widget WID-1"
    assert item["unit"] == "Pieces"
    assert item["hsn_sac"] == "84713010"
    assert item["quantity"] == 2 and item["unit_price"] == 100 and item["gst_rate"] == 18
    assert item["taxable_amount"] == 200
    assert item["cgst_amount"] == 18 and item["sgst_amount"] == 18 and item["igst_amount"] == 0
    assert item["line_total"] == 236

    assert challan["taxable_amount"] == 200
    assert challan["total_tax_amount"] == 36
    assert challan["cgst_amount"] == 18 and challan["sgst_amount"] == 18 and challan["igst_amount"] == 0
    assert challan["total_amount"] == 236


def test_numbers_come_from_their_own_series(setup):
    s = setup
    before = series_counters(s.client)
    first = create_challan(s.client, s.ledger, [(s.product, 1)])
    second = create_challan(s.client, s.ledger, [(s.product, 1)])
    assert first["challan_number"].endswith("-001") and second["challan_number"].endswith("-002")
    after = series_counters(s.client)
    assert after["delivery_challan"] == before["delivery_challan"] + 2
    for voucher_type in ("sales", "quotation", "proforma"):
        assert after[voucher_type] == before[voucher_type]


def test_a_typed_number_is_kept_and_leaves_the_counter_alone(setup):
    s = setup
    before = series_counters(s.client)["delivery_challan"]
    challan = create_challan(s.client, s.ledger, [(s.product, 1)], challan_number="  JW/24-25/7 ")
    assert challan["challan_number"] == "JW/24-25/7"
    assert series_counters(s.client)["delivery_challan"] == before


def test_a_blank_number_means_the_next_in_the_series(setup):
    s = setup
    challan = create_challan(s.client, s.ledger, [(s.product, 1)], challan_number="   ")
    assert challan["challan_number"].startswith("DC-")


@pytest.mark.parametrize("number", ["-DC1", "DC 1", "DC#1", "ABCDEFGHIJKLMNOPQ", "DC.1"])
def test_a_number_breaking_rule_55_is_refused(setup, number):
    s = setup
    response = _post(s.client, challan_payload(s.ledger, [(s.product, 1)], challan_number=number))
    assert response.status_code == 400, response.text
    assert response.json()["detail"] == (
        'Challan number must be at most 16 characters, starting with a letter or digit and using only '
        'letters, digits, "-" and "/".'
    )


def test_sixteen_characters_is_allowed(setup):
    s = setup
    challan = create_challan(s.client, s.ledger, [(s.product, 1)], challan_number="ABCDEFGHIJKLMNOP")
    assert challan["challan_number"] == "ABCDEFGHIJKLMNOP"


def test_a_number_in_use_is_refused_and_nothing_moves(setup):
    s = setup
    first = create_challan(s.client, s.ledger, [(s.product, 1)], challan_number="DC-77")
    response = _post(s.client, challan_payload(s.ledger, [(s.product, 5)], challan_number="DC-77"))
    assert response.status_code == 409
    assert response.json()["detail"] == {
        "code": "challan_number_taken",
        "message": "Challan number DC-77 is already used. Pick another.",
    }
    assert ok(s.client.get("/api/delivery-challans/"))["total"] == 1
    # The auto series skips a number someone typed.
    assert first["challan_number"] == "DC-77"


def test_the_series_skips_numbers_typed_by_hand(setup):
    s = setup
    year = india_today().year
    create_challan(s.client, s.ledger, [(s.product, 1)], challan_number=f"DC-{year}-001")
    auto = create_challan(s.client, s.ledger, [(s.product, 1)])
    assert auto["challan_number"] == f"DC-{year}-002"


def test_a_series_too_long_for_rule_55_is_refused_with_advice(client):
    seed_company(client, gst="")
    ledger = create_ledger(client, gst="")["id"]
    product = create_product(client)["id"]
    series = next(row for row in ok(client.get("/api/invoice-series/")) if row["voucher_type"] == "delivery_challan")
    ok(client.put(f"/api/invoice-series/{series['id']}", json={
        "prefix": "DELIVERY-CHALLAN",
        "suffix": "",
        "include_year": True,
        "year_format": "YYYY",
        "separator": "-",
        "pad_digits": 3,
    }))
    response = _post(client, challan_payload(ledger, [(product, 1)]))
    assert response.status_code == 400
    detail = response.json()["detail"]
    assert detail.startswith(f"The delivery challan series gives numbers like DELIVERY-CHALLAN-{india_today().year}-001")
    assert detail.endswith("Shorten the format in Settings > Company, or type a number.")
    # Typing one still works.
    ok(_post(client, challan_payload(ledger, [(product, 1)], challan_number="DC-1")))


def test_series_settings_refuse_a_challan_format_too_long_for_a_gst_company(setup):
    s = setup
    series = next(row for row in ok(s.client.get("/api/invoice-series/")) if row["voucher_type"] == "delivery_challan")
    assert series["prefix"] == "DC"
    response = s.client.put(f"/api/invoice-series/{series['id']}", json={
        "prefix": "DELIVERY-CHALLAN",
        "suffix": "",
        "include_year": True,
        "year_format": "YYYY",
        "separator": "-",
        "pad_digits": 3,
    })
    assert response.status_code == 400


@pytest.mark.parametrize("purpose", list(PURPOSE_LABELS))
def test_every_purpose(setup, purpose):
    s = setup
    challan = create_challan(s.client, s.ledger, [(s.product, 1)], purpose=purpose)
    assert challan["purpose"] == purpose
    assert challan["purpose_label"] == PURPOSE_LABELS[purpose]


def test_purpose_labels_and_order():
    assert list(PURPOSE_LABELS.items()) == [
        ("supply_on_approval", "Supply on approval"),
        ("job_work", "Job work"),
        ("liquid_gas", "Supply of liquid gas (quantity not known)"),
        ("skd_ckd_lots", "SKD/CKD or in lots"),
        ("exhibition", "Exhibition or fair"),
        ("own_use", "For own use / branch transfer"),
        ("other", "Other"),
    ]


def test_an_unknown_purpose_is_a_422(setup):
    s = setup
    response = _post(s.client, challan_payload(s.ledger, [(s.product, 1)], purpose="sale"))
    assert response.status_code == 422


def test_a_back_dated_challan(setup):
    s = setup
    day = india_today() - timedelta(days=5)
    challan = create_challan(s.client, s.ledger, [(s.product, 1)], challan_date=day.isoformat())
    assert challan["challan_date"] == day.isoformat()
    assert challan["age_days"] == 5


def test_a_future_dated_challan_shows_zero_age(setup):
    s = setup
    day = india_today() + timedelta(days=5)
    challan = create_challan(s.client, s.ledger, [(s.product, 1)], challan_date=day.isoformat())
    assert challan["challan_date"] == day.isoformat()
    assert challan["age_days"] == 0
    page = ok(s.client.get("/api/delivery-challans/"))
    by_id = {row["id"]: row for row in page["items"]}
    assert by_id[challan["id"]]["age_days"] == 0


@pytest.mark.parametrize("day", ["1999-12-31", "2100-01-01"])
def test_dates_outside_the_document_range_are_refused(setup, day):
    s = setup
    response = _post(s.client, challan_payload(s.ledger, [(s.product, 1)], challan_date=day))
    assert response.status_code == 422


def test_per_line_gst_rate_and_price(setup):
    s = setup
    challan = create_challan(s.client, s.ledger, [], items=[
        {"product_id": s.product, "quantity": 3, "unit_price": 50, "gst_rate": 5, "description": "Sample lot"},
        {"product_id": s.product, "quantity": 1},
    ])
    first, second = challan["items"]
    assert first["gst_rate"] == 5 and first["taxable_amount"] == 150 and first["tax_amount"] == 7.5
    assert first["description"] == "Sample lot"
    # Left out: the product's price and rate.
    assert second["unit_price"] == 100 and second["gst_rate"] == 18
    assert challan["taxable_amount"] == 250
    assert challan["total_tax_amount"] == 25.5
    assert challan["total_amount"] == 275.5


def test_interstate_challan_carries_igst(setup):
    s = setup
    other = create_ledger(s.client, "Karnataka Buyer", gst=GST_KA)
    challan = create_challan(s.client, other["id"], [(s.product, 2)])
    assert challan["place_of_supply"] == "29"
    assert challan["igst_amount"] == 36 and challan["cgst_amount"] == 0 and challan["sgst_amount"] == 0


def test_place_of_supply_typed_wins(setup):
    s = setup
    challan = create_challan(s.client, s.ledger, [(s.product, 2)], place_of_supply="29")
    assert challan["place_of_supply"] == "29"
    assert challan["igst_amount"] == 36


def test_unregistered_buyer_takes_the_sellers_state(setup):
    s = setup
    walk_in = create_ledger(s.client, "Walk-in", gst="")
    challan = create_challan(s.client, walk_in["id"], [(s.product, 1)])
    assert challan["place_of_supply"] == "27"
    assert challan["cgst_amount"] == 9


def test_a_seller_without_gstin_has_no_place_of_supply(client):
    seed_company(client, gst="")
    ledger = create_ledger(client)
    product = create_product(client)
    challan = create_challan(client, ledger["id"], [(product["id"], 1)], place_of_supply="29")
    assert challan["place_of_supply"] is None
    assert challan["igst_amount"] == 0


def test_terms_default_to_the_companys_and_can_be_blanked(setup):
    s = setup
    ok(s.client.post("/api/company/terms", json={"content": "Goods on approval for 7 days."}))
    ok(s.client.post("/api/company/terms", json={"content": "Return unsold goods."}))
    challan = create_challan(s.client, s.ledger, [(s.product, 1)])
    assert challan["terms_text"] == "1. Goods on approval for 7 days.\n2. Return unsold goods."

    blank = create_challan(s.client, s.ledger, [(s.product, 1)], terms_text="")
    assert blank["terms_text"] is None
    typed = create_challan(s.client, s.ledger, [(s.product, 1)], terms_text="Own terms", reference_notes="Van 4")
    assert typed["terms_text"] == "Own terms"
    assert typed["reference_notes"] == "Van 4"

    # Left out on edit: kept. Sent: replaced.
    kept = ok(update_challan(s.client, typed, [(s.product, 1)]))
    assert kept["terms_text"] == "Own terms"
    assert kept["reference_notes"] is None
    replaced = ok(update_challan(s.client, typed, [(s.product, 1)], terms_text="New"))
    assert replaced["terms_text"] == "New"


def test_shipping_to_a_saved_address(setup):
    s = setup
    address = ok(s.client.post(
        f"/api/ledgers/{s.ledger}/addresses/", json={"label": "Godown", "address": "7 Dock Road"}
    ), 201)
    challan = create_challan(
        s.client, s.ledger, [(s.product, 1)],
        shipping_address_same_as_billing=False, shipping_address_id=address["id"],
    )
    assert challan["shipping_address"] == "7 Dock Road"
    assert challan["shipping_address_label"] == "Godown"
    assert challan["shipping_address_id"] == address["id"]

    back = ok(update_challan(s.client, challan, [(s.product, 1)]))
    assert back["shipping_address"] is None and back["shipping_address_id"] is None


def test_a_new_shipping_address_is_saved_once(setup, db_session):
    s = setup
    body = {
        "shipping_address_same_as_billing": False,
        "new_shipping_address": {"label": "Site", "address": "Plot 9, MIDC"},
    }
    challan = create_challan(s.client, s.ledger, [(s.product, 1)], **body)
    assert challan["shipping_address"] == "Plot 9, MIDC" and challan["shipping_address_id"]
    ok(update_challan(s.client, challan, [(s.product, 1)], **body))
    assert db_session.query(LedgerAddress).count() == 1


def test_another_ledgers_address_is_refused(setup):
    s = setup
    other = create_ledger(s.client, "Other Buyer", gst="")
    address = ok(s.client.post(
        f"/api/ledgers/{other['id']}/addresses/", json={"label": "Theirs", "address": "Elsewhere"}
    ), 201)
    response = _post(s.client, challan_payload(
        s.ledger, [(s.product, 1)],
        shipping_address_same_as_billing=False, shipping_address_id=address["id"],
    ))
    assert response.status_code == 404


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

def test_no_lines_is_refused(setup):
    s = setup
    response = _post(s.client, {"ledger_id": s.ledger, "items": []})
    assert response.status_code == 400
    assert response.json()["detail"] == "Delivery challan must have at least one line item"


@pytest.mark.parametrize("item, status", [
    ({"product_id": 0, "quantity": 1}, 422),
    ({"quantity": 0}, 400),
    ({"quantity": -1}, 400),
    ({"quantity": 1.0001}, 422),
    ({"quantity": 1, "unit_price": 1.001}, 422),
    ({"quantity": 1, "unit_price": -1}, 422),
    ({"quantity": 1, "gst_rate": 101}, 422),
    ({"quantity": 1.5}, 400),  # the product is sold in whole numbers
    ({"quantity": 1_000_000_000}, 422),
])
def test_bad_lines(setup, item, status):
    s = setup
    line = {"product_id": s.product, **item}
    response = _post(s.client, {"ledger_id": s.ledger, "items": [line]})
    assert response.status_code == status, response.text
    assert ok(s.client.get("/api/delivery-challans/"))["total"] == 0


def test_too_large_an_amount_is_refused(setup):
    s = setup
    big = create_product(s.client, "BIG-1", price=99_999_999, initial_quantity=1000)
    response = _post(s.client, challan_payload(s.ledger, [(big["id"], 2, 99_999_999)]))
    assert response.status_code == 400
    assert "too large" in response.json()["detail"]


def test_unknown_ledger_and_product(setup):
    s = setup
    assert _post(s.client, challan_payload(9999, [(s.product, 1)])).status_code == 404
    assert _post(s.client, challan_payload(s.ledger, [(9999, 1)])).status_code == 404


def test_tax_inclusive_and_discounts_are_not_challan_fields(setup):
    s = setup
    challan = create_challan(s.client, s.ledger, [(s.product, 1)])
    response = update_challan(s.client, challan, [(s.product, 1)], tax_inclusive=True)
    assert response.status_code == 422


# ---------------------------------------------------------------------------
# Edit
# ---------------------------------------------------------------------------

def test_edit_replaces_fields_and_lines(setup):
    s = setup
    other = create_ledger(s.client, "Second Buyer", gst=GST_KA)
    challan = create_challan(s.client, s.ledger, [(s.product, 1)])
    day = india_today() - timedelta(days=2)
    updated = ok(s.client.put(f"/api/delivery-challans/{challan['id']}", json={
        "ledger_id": other["id"],
        "challan_number": "JW-5",
        "challan_date": day.isoformat(),
        "purpose": "job_work",
        "items": [{"product_id": s.product, "quantity": 4, "unit_price": 10}],
    }))
    assert updated["challan_number"] == "JW-5"
    assert updated["challan_date"] == day.isoformat()
    assert updated["purpose"] == "job_work"
    assert updated["ledger_name"] == "Second Buyer"
    assert updated["place_of_supply"] == "29"
    assert updated["taxable_amount"] == 40 and updated["igst_amount"] == 7.2
    assert len(updated["items"]) == 1
    assert updated["updated_at"] >= challan["updated_at"]


def test_edit_keeps_number_and_date_when_left_out(setup):
    s = setup
    challan = create_challan(s.client, s.ledger, [(s.product, 1)], challan_date=(india_today() - timedelta(days=3)).isoformat())
    updated = ok(update_challan(s.client, challan, [(s.product, 2)]))
    assert updated["challan_number"] == challan["challan_number"]
    assert updated["challan_date"] == challan["challan_date"]


def test_edit_to_a_number_in_use_is_refused(setup):
    s = setup
    create_challan(s.client, s.ledger, [(s.product, 1)], challan_number="DC-1")
    second = create_challan(s.client, s.ledger, [(s.product, 1)], challan_number="DC-2")
    response = update_challan(s.client, second, [(s.product, 5)], challan_number="DC-1")
    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "challan_number_taken"
    assert get_challan(s.client, second["id"])["challan_number"] == "DC-2"
    # Its own number is not "in use".
    ok(update_challan(s.client, second, [(s.product, 1)], challan_number="DC-2"))


def test_edit_to_a_date_in_another_financial_year_is_refused(setup):
    s = setup
    today = date.today()
    later = ok(s.client.post("/api/financial-years/", json={
        "label": "LATER-FY",
        "start_date": date(today.year + 2, 1, 1).isoformat(),
        "end_date": date(today.year + 2, 12, 31).isoformat(),
    }), 201)
    challan = create_challan(s.client, s.ledger, [(s.product, 1)])
    assert challan["financial_year_id"] != later["id"]
    response = update_challan(
        s.client, challan, [(s.product, 1)], challan_date=date(today.year + 2, 6, 1).isoformat()
    )
    assert response.status_code == 400
    assert "LATER-FY" in response.json()["detail"]
    kept = get_challan(s.client, challan["id"])
    assert kept["financial_year_id"] == challan["financial_year_id"]
    assert kept["challan_date"] == challan["challan_date"]


def test_edit_refuses_unknown_fields(setup):
    s = setup
    challan = create_challan(s.client, s.ledger, [(s.product, 1)])
    response = update_challan(s.client, challan, [(s.product, 1)], status="invoiced")
    assert response.status_code == 422


def test_edit_and_cancel_of_a_missing_challan_are_404(setup):
    s = setup
    assert s.client.get("/api/delivery-challans/999").status_code == 404
    assert s.client.get("/api/delivery-challans/999").json()["detail"] == "Delivery challan 999 not found"
    assert s.client.put("/api/delivery-challans/999", json=challan_payload(s.ledger, [(s.product, 1)])).status_code == 404
    assert s.client.post("/api/delivery-challans/999/cancel").status_code == 404
    assert s.client.get("/api/delivery-challans/999/conversion-draft").status_code == 404
    assert s.client.get("/api/delivery-challans/999/pdf").status_code == 404
    response = s.client.post("/api/delivery-challans/999/convert", json={
        "ledger_id": s.ledger, "items": [{"product_id": s.product, "quantity": 1}],
    })
    assert response.status_code == 404


# ---------------------------------------------------------------------------
# List
# ---------------------------------------------------------------------------

def test_list_filters_counts_and_order(setup):
    s = setup
    other = create_ledger(s.client, "Fair Organiser", gst="")
    today = india_today()
    old = create_challan(s.client, s.ledger, [(s.product, 1)], challan_date=(today - timedelta(days=10)).isoformat())
    fair = create_challan(s.client, other["id"], [(s.product, 1)], purpose="exhibition")
    gone = create_challan(s.client, s.ledger, [(s.product, 1)], purpose="job_work")
    ok(s.client.post(f"/api/delivery-challans/{gone['id']}/cancel"))

    page = ok(s.client.get("/api/delivery-challans/"))
    assert page["total"] == 3
    # Newest date first, then newest id.
    assert [row["id"] for row in page["items"]] == [gone["id"], fair["id"], old["id"]]
    assert page["status_counts"] == {"open": 2, "cancelled": 1}
    by_id = {row["id"]: row for row in page["items"]}
    assert by_id[old["id"]]["age_days"] == 10
    assert by_id[gone["id"]]["age_days"] is None

    open_only = ok(s.client.get("/api/delivery-challans/", params={"status": "open"}))
    assert {row["id"] for row in open_only["items"]} == {old["id"], fair["id"]}
    # Counts ignore the status filter itself.
    assert open_only["status_counts"] == {"open": 2, "cancelled": 1}

    assert _ids(ok(s.client.get("/api/delivery-challans/", params={"purpose": "exhibition"}))) == {fair["id"]}
    assert _ids(ok(s.client.get("/api/delivery-challans/", params={"ledger_id": other["id"]}))) == {fair["id"]}
    assert _ids(ok(s.client.get("/api/delivery-challans/", params={"search": "fair org"}))) == {fair["id"]}
    assert _ids(ok(s.client.get("/api/delivery-challans/", params={"search": old["challan_number"]}))) == {old["id"]}
    assert _ids(ok(s.client.get("/api/delivery-challans/", params={
        "date_to": (today - timedelta(days=1)).isoformat(),
    }))) == {old["id"]}
    assert _ids(ok(s.client.get("/api/delivery-challans/", params={"date_from": today.isoformat()}))) == {
        fair["id"], gone["id"],
    }
    searched = ok(s.client.get("/api/delivery-challans/", params={"search": "Customer One"}))
    assert searched["status_counts"] == {"open": 1, "cancelled": 1}

    paged = ok(s.client.get("/api/delivery-challans/", params={"page": 2, "page_size": 2}))
    assert paged["total_pages"] == 2 and [row["id"] for row in paged["items"]] == [old["id"]]

    assert s.client.get("/api/delivery-challans/", params={"status": "expired"}).status_code == 422
    assert s.client.get("/api/delivery-challans").status_code == 200


def test_empty_list(setup):
    page = ok(setup.client.get("/api/delivery-challans/"))
    assert page == {"items": [], "total": 0, "page": 1, "page_size": 20, "total_pages": 1, "status_counts": {}}


# ---------------------------------------------------------------------------
# A challan is not a bill
# ---------------------------------------------------------------------------

def test_a_challan_touches_no_invoice_payment_or_ledger_balance(setup, db_session):
    s = setup
    before = ok(s.client.get(f"/api/ledgers/{s.ledger}"))
    create_challan(s.client, s.ledger, [(s.product, 3)])
    assert db_session.query(Invoice).count() == 0
    assert ok(s.client.get("/api/invoices/"))["total"] == 0
    after = ok(s.client.get(f"/api/ledgers/{s.ledger}"))
    assert after == before


# ---------------------------------------------------------------------------
# Delete guards
# ---------------------------------------------------------------------------

def test_a_product_or_ledger_on_a_challan_cannot_be_deleted(setup):
    s = setup
    create_challan(s.client, s.ledger, [(s.product, 1)])
    product = s.client.delete(f"/api/products/{s.product}")
    assert product.status_code == 400
    assert product.json()["detail"] == "Cannot delete product linked to delivery challans"
    ledger = s.client.delete(f"/api/ledgers/{s.ledger}")
    assert ledger.status_code == 400
    assert ledger.json()["detail"] == "Cannot delete ledger linked to delivery challans"


# ---------------------------------------------------------------------------
# Not on the MCP tool list in v1
# ---------------------------------------------------------------------------

def test_challan_routes_are_not_mcp_tools():
    from src.mcp_server.overrides import EXCLUDED_PATH_PREFIXES

    assert "/api/delivery-challans" in EXCLUDED_PATH_PREFIXES


# ---------------------------------------------------------------------------
# Tenant isolation
# ---------------------------------------------------------------------------

def _body(ledger: int, product: int, **extra) -> dict:
    return {"ledger_id": ledger, "items": [{"product_id": product, "quantity": 1, "unit_price": 100}], **extra}


@pytest.fixture
def two(client, db_session, shared_hosting, act_as):  # noqa: F811
    user_a = _user(db_session, "alice@alpha.example")
    user_b = _user(db_session, "bob@beta.example")

    act_as(user_b)
    company_b = _create_company(client, "Beta Stores")
    ledger_b = _create_ledger(client, "Beta Customer")
    product_b = _create_product(client, "BETA-1")
    challan_b = _ok(client.post("/api/delivery-challans/", json=_body(ledger_b, product_b)))

    act_as(user_a)
    company_a = _create_company(client, "Alpha Traders")
    ledger_a = _create_ledger(client, "Alpha Customer")
    product_a = _create_product(client, "ALPHA-1")
    challan_a = _ok(client.post("/api/delivery-challans/", json=_body(ledger_a, product_a)))

    return SimpleNamespace(
        user_a=user_a, user_b=user_b, company_a=company_a, company_b=company_b,
        ledger_a=ledger_a, ledger_b=ledger_b, product_a=product_a, product_b=product_b,
        challan_a=challan_a, challan_b=challan_b,
    )


def test_numbering_starts_afresh_in_each_company(two):
    assert two.challan_a["challan_number"] == two.challan_b["challan_number"]


def test_a_typed_number_used_by_another_company_is_free(client, two, act_as):  # noqa: F811
    act_as(two.user_b)
    typed = _ok(client.post("/api/delivery-challans/", json=_body(
        two.ledger_b, two.product_b, challan_number=two.challan_a["challan_number"].replace("001", "009"),
    )))
    act_as(two.user_a)
    _ok(client.post("/api/delivery-challans/", json=_body(
        two.ledger_a, two.product_a, challan_number=typed["challan_number"],
    )))


def test_list_shows_only_own_challans(client, two, act_as):  # noqa: F811
    act_as(two.user_a)
    assert _ids(_ok(client.get("/api/delivery-challans/"))) == {two.challan_a["id"]}
    act_as(two.user_b)
    page = _ok(client.get("/api/delivery-challans/"))
    assert _ids(page) == {two.challan_b["id"]}
    assert page["status_counts"] == {"open": 1}
    assert _ok(client.get("/api/delivery-challans/", params={"search": "Alpha"}))["total"] == 0


@pytest.mark.parametrize("method, suffix, body", [
    ("get", "", None),
    ("get", "/pdf", None),
    ("get", "/conversion-draft", None),
    ("put", "", "update"),
    ("post", "/cancel", None),
    ("post", "/convert", "invoice"),
])
def test_every_route_answers_404_for_the_other_tenants_challan(client, db_session, two, act_as, method, suffix, body):  # noqa: F811
    act_as(two.user_b)
    if body == "update":
        body = _body(two.ledger_b, two.product_b)
    elif body == "invoice":
        body = {
            "ledger_id": two.ledger_b,
            "voucher_type": "sales",
            "items": [{"product_id": two.product_b, "quantity": 1, "unit_price": 100}],
        }
    kwargs = {"json": body} if body is not None else {}
    response = getattr(client, method)(f"/api/delivery-challans/{two.challan_a['id']}{suffix}", **kwargs)
    assert response.status_code == 404, response.text
    assert "Alpha" not in response.text

    db_session.expire_all()
    row = db_session.query(DeliveryChallan).filter(DeliveryChallan.id == two.challan_a["id"]).one()
    assert row.status == "open"
    assert db_session.query(Invoice).filter(Invoice.source_challan_id == row.id).count() == 0


def test_a_challan_cannot_use_the_other_tenants_ledger_product_or_address(client, db_session, two, act_as):  # noqa: F811
    act_as(two.user_a)
    address = _ok(client.post(
        f"/api/ledgers/{two.ledger_a}/addresses/", json={"label": "Warehouse", "address": "Alpha Dock"},
    ), 201)
    act_as(two.user_b)
    assert client.post("/api/delivery-challans/", json=_body(two.ledger_a, two.product_b)).status_code == 404
    assert client.post("/api/delivery-challans/", json=_body(two.ledger_b, two.product_a)).status_code == 404
    assert client.put(
        f"/api/delivery-challans/{two.challan_b['id']}", json=_body(two.ledger_a, two.product_b)
    ).status_code == 404
    response = client.post("/api/delivery-challans/", json=_body(
        two.ledger_b, two.product_b, shipping_address_same_as_billing=False, shipping_address_id=address["id"],
    ))
    assert response.status_code == 404
    assert "Alpha Dock" not in response.text


def test_conversion_and_invoice_hooks_stay_in_the_company(client, db_session, two, act_as):  # noqa: F811
    act_as(two.user_b)
    draft = _ok(client.get(f"/api/delivery-challans/{two.challan_b['id']}/conversion-draft"))
    invoice = _ok(client.post(f"/api/delivery-challans/{two.challan_b['id']}/convert", json=draft["invoice"]))
    assert invoice["source_challan_number"] == two.challan_b["challan_number"]
    _ok(client.delete(f"/api/invoices/{invoice['id']}"))
    assert _ok(client.get(f"/api/delivery-challans/{two.challan_b['id']}"))["status"] == "open"
    _ok(client.post(f"/api/invoices/{invoice['id']}/restore"))
    assert _ok(client.get(f"/api/delivery-challans/{two.challan_b['id']}"))["status"] == "invoiced"

    act_as(two.user_a)
    assert client.delete(f"/api/invoices/{invoice['id']}").status_code == 404
    db_session.expire_all()
    assert db_session.query(DeliveryChallan).filter(DeliveryChallan.id == two.challan_a["id"]).one().status == "open"


def test_delete_guards_see_only_their_own_company(client, two, act_as):  # noqa: F811
    act_as(two.user_b)
    assert client.delete(f"/api/products/{two.product_b}").status_code == 400
    assert client.delete(f"/api/ledgers/{two.ledger_b}").status_code == 400
    fresh = _create_product(client, "BETA-FRESH")
    assert client.delete(f"/api/products/{fresh}").status_code == 200
