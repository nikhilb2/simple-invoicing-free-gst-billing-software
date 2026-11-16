"""Converting a delivery challan to a tax invoice (#840): the draft, the guards, the links."""

from datetime import datetime, timedelta, timezone

import pytest
from challan_helpers import (
    GST_KA,
    convert,
    create_challan,
    create_ledger,
    create_product,
    draft,
    get_challan,
    iso_today,
    ok,
    seed_company,
    series_counters,
    stock,
    update_challan,
)

from src.models.invoice import Invoice
from src.models.product import Product
from src.services.gst_tax_service import india_today
from src.services.pdf_templates import _build_invoice_html


@pytest.fixture
def setup(client):
    seed_company(client)
    ledger = create_ledger(client)
    product = create_product(client)
    return client, ledger["id"], product["id"]


def _codes(body: dict) -> set[str]:
    return {warning["code"] for warning in body["warnings"]}


# ---------------------------------------------------------------------------
# The draft
# ---------------------------------------------------------------------------

def test_the_draft_is_the_challan_as_an_invoice(setup):
    client, ledger, product = setup
    address = ok(client.post(f"/api/ledgers/{ledger}/addresses/", json={"label": "Site", "address": "Plot 4"}), 201)
    day = india_today() - timedelta(days=3)
    challan = create_challan(
        client, ledger, [(product, 4, 90)],
        challan_date=day.isoformat(), purpose="job_work", reference_notes="Van 7",
        shipping_address_same_as_billing=False, shipping_address_id=address["id"],
    )
    body = draft(client, challan["id"])

    assert body["challan_id"] == challan["id"]
    assert body["challan_number"] == challan["challan_number"]
    assert body["challan_date"] == day.isoformat()
    invoice = body["invoice"]
    assert invoice["challan_updated_at"] is not None
    assert invoice["ledger_id"] == ledger
    assert invoice["voucher_type"] == "sales"
    assert invoice["invoice_date"] == iso_today()
    assert invoice["place_of_supply"] == "27"
    # The challan reference prints from the link, so the free-text notes start empty.
    assert invoice["reference_notes"] is None
    assert invoice["tax_inclusive"] is False and invoice["apply_round_off"] is False
    assert invoice["discount_type"] is None and invoice["tcs_section_id"] is None
    assert invoice["shipping_address_same_as_billing"] is False
    assert invoice["shipping_address_id"] == address["id"]
    (item,) = invoice["items"]
    assert item["product_id"] == product and item["quantity"] == 4 and item["unit_price"] == 90
    # Today's product values, as on a quotation conversion.
    assert item["gst_rate"] is None and item["hsn_sac"] is None
    assert body["challan_items"] == [{"product_id": product, "product_name": "Widget WID-1", "quantity": 4}]
    assert body["warnings"] == []


def test_the_draft_reads_only(setup):
    client, ledger, product = setup
    challan = create_challan(client, ledger, [(product, 4)])
    before = get_challan(client, challan["id"])
    counters = series_counters(client)
    draft(client, challan["id"])
    assert get_challan(client, challan["id"]) == before
    assert series_counters(client) == counters
    assert stock(client, product) == 96


def test_warnings_for_what_changed_since(setup, db_session):
    client, ledger, product = setup
    loose = create_product(client, "LOOSE-1", allow_decimal=True)
    address = ok(client.post(f"/api/ledgers/{ledger}/addresses/", json={"label": "Site", "address": "Plot 4"}), 201)
    challan = create_challan(
        client, ledger, [(product, 1), (loose["id"], 2.5)],
        shipping_address_same_as_billing=False, shipping_address_id=address["id"],
    )
    db_session.query(Product).filter(Product.id == product).update({"gst_rate": 12, "hsn_sac": "84719000"})
    db_session.query(Product).filter(Product.id == loose["id"]).update({"allow_decimal": False})
    db_session.commit()
    assert client.delete(f"/api/ledgers/{ledger}/addresses/{address['id']}").status_code == 204

    body = draft(client, challan["id"])
    assert _codes(body) == {"rate_changed", "hsn_changed", "quantity_not_whole", "shipping_address_gone"}
    messages = {warning["code"]: warning["message"] for warning in body["warnings"]}
    assert messages["rate_changed"] == (
        "GST on Widget WID-1 was 18% on this challan and is now 12%. The invoice uses the current rate. "
        "The price is kept, so the total changes."
    )
    assert messages["hsn_changed"] == "HSN/SAC of Widget WID-1 is now 84719000. The invoice uses the current code."
    assert messages["quantity_not_whole"] == (
        "Widget LOOSE-1 is now sold in whole numbers, but this challan has 2.5. Change the quantity before saving."
    )
    assert "this challan" in messages["shipping_address_gone"]
    assert body["invoice"]["shipping_address_same_as_billing"] is True
    assert body["invoice"]["shipping_address_id"] is None


def test_a_per_line_rate_that_differs_from_the_product_is_flagged(setup):
    client, ledger, product = setup
    challan = create_challan(client, ledger, [], items=[{"product_id": product, "quantity": 1, "gst_rate": 5}])
    assert _codes(draft(client, challan["id"])) == {"rate_changed"}


def test_tax_split_warning_when_a_gstin_moved_state(setup, db_session):
    client, ledger, product = setup
    walk_in = create_ledger(client, "Walk-in", gst="")
    challan = create_challan(client, walk_in["id"], [(product, 1)], place_of_supply=None)
    assert challan["place_of_supply"] == "27"
    assert _codes(draft(client, challan["id"])) == set()

    # A challan with no place of supply stored falls back to the GSTINs, so a buyer
    # registering in another state changes the heads.
    from src.models.buyer import Buyer
    from src.models.delivery_challan import DeliveryChallan

    db_session.query(DeliveryChallan).filter(DeliveryChallan.id == challan["id"]).update({"place_of_supply": None})
    db_session.query(Buyer).filter(Buyer.id == walk_in["id"]).update({"gst": GST_KA})
    db_session.commit()
    body = draft(client, challan["id"])
    assert _codes(body) == {"tax_split_changed"}
    assert "IGST instead of CGST + SGST" in body["warnings"][0]["message"]


# ---------------------------------------------------------------------------
# Converting
# ---------------------------------------------------------------------------

def test_convert_links_both_ways(setup, db_session):
    client, ledger, product = setup
    challan = create_challan(client, ledger, [(product, 4)])
    counters = series_counters(client)
    invoice = ok(convert(client, challan["id"]))

    assert invoice["voucher_type"] == "sales"
    assert invoice["source_challan_id"] == challan["id"]
    assert invoice["source_challan_number"] == challan["challan_number"]
    assert invoice["source_quotation_id"] is None
    assert invoice["reference_notes"] is None
    assert invoice["total_amount"] == 472
    assert series_counters(client)["sales"] == counters["sales"] + 1
    assert series_counters(client)["delivery_challan"] == counters["delivery_challan"]

    fetched = ok(client.get(f"/api/invoices/{invoice['id']}"))
    assert fetched["source_challan_number"] == challan["challan_number"]
    # The invoice view shows the date beside the number, as the PDF does.
    assert fetched["source_challan_date"] == challan["challan_date"]
    listed = ok(client.get("/api/invoices/"))["items"]
    assert listed[0]["source_challan_number"] == challan["challan_number"]
    assert listed[0]["source_challan_date"] == challan["challan_date"]

    after = get_challan(client, challan["id"])
    assert after["status"] == "invoiced"
    assert after["invoiced_at"] is not None
    assert after["age_days"] is None
    assert after["invoice_id"] == invoice["id"]
    assert after["invoice_number"] == invoice["invoice_number"]
    assert after["invoices"] == [{"id": invoice["id"], "invoice_number": invoice["invoice_number"], "status": "active"}]
    listed_challan = ok(client.get("/api/delivery-challans/"))["items"][0]
    assert listed_challan["invoice_number"] == invoice["invoice_number"]
    assert ok(client.get("/api/delivery-challans/", params={"status": "invoiced"}))["total"] == 1

    # The challan number and date reach the invoice PDF through the link.
    row = db_session.query(Invoice).filter(Invoice.id == invoice["id"]).one()
    html = _build_invoice_html(row, db_session.query(Product).all())
    assert f"Against delivery challan {challan['challan_number']} dated {india_today():%d %b %Y}" in html


def test_the_invoice_can_go_to_another_ledger(setup):
    client, ledger, product = setup
    other = create_ledger(client, "Head Office", gst=GST_KA)
    challan = create_challan(client, ledger, [(product, 1)])
    invoice = ok(convert(client, challan["id"], ledger_id=other["id"], place_of_supply=None))
    assert invoice["ledger_name"] == "Head Office"
    assert invoice["igst_amount"] == 18


def test_only_a_sales_invoice(setup):
    client, ledger, product = setup
    challan = create_challan(client, ledger, [(product, 1)])
    response = convert(client, challan["id"], voucher_type="purchase")
    assert response.status_code == 400
    assert response.json()["detail"] == "A delivery challan can only convert to a sales invoice"
    assert get_challan(client, challan["id"])["status"] == "open"


def test_a_second_conversion_is_a_409_naming_the_invoice(setup):
    client, ledger, product = setup
    challan = create_challan(client, ledger, [(product, 1)])
    payload = draft(client, challan["id"])["invoice"]
    invoice = ok(client.post(f"/api/delivery-challans/{challan['id']}/convert", json=payload))
    expected = {
        "code": "challan_already_invoiced",
        "message": f"{challan['challan_number']} was already invoiced as {invoice['invoice_number']}",
        "invoice_id": invoice["id"],
        "invoice_number": invoice["invoice_number"],
    }

    payload.pop("challan_updated_at")
    again = client.post(f"/api/delivery-challans/{challan['id']}/convert", json=payload)
    assert again.status_code == 409
    assert again.json()["detail"] == expected

    response = client.get(f"/api/delivery-challans/{challan['id']}/conversion-draft")
    assert response.status_code == 409
    assert response.json()["detail"] == expected
    assert stock(client, product) == 99


def test_a_cancelled_challan_cannot_be_invoiced(setup):
    client, ledger, product = setup
    challan = create_challan(client, ledger, [(product, 1)])
    payload = draft(client, challan["id"])["invoice"]
    ok(client.post(f"/api/delivery-challans/{challan['id']}/cancel"))
    payload.pop("challan_updated_at")
    expected = {
        "code": "challan_cancelled",
        "message": f"{challan['challan_number']} is cancelled and cannot be invoiced",
    }
    response = client.post(f"/api/delivery-challans/{challan['id']}/convert", json=payload)
    assert response.status_code == 409 and response.json()["detail"] == expected
    response = client.get(f"/api/delivery-challans/{challan['id']}/conversion-draft")
    assert response.status_code == 409 and response.json()["detail"] == expected
    assert ok(client.get("/api/invoices/"))["total"] == 0
    assert stock(client, product) == 100


def test_a_draft_older_than_the_challan_is_refused(setup):
    client, ledger, product = setup
    challan = create_challan(client, ledger, [(product, 1)])
    payload = draft(client, challan["id"])["invoice"]
    ok(update_challan(client, challan, [(product, 3)]))

    response = client.post(f"/api/delivery-challans/{challan['id']}/convert", json=payload)
    assert response.status_code == 409
    assert response.json()["detail"] == {
        "code": "challan_changed",
        "message": (
            f"{challan['challan_number']} was changed after this conversion was opened. "
            "Load the latest version and check it before saving."
        ),
    }
    assert get_challan(client, challan["id"])["status"] == "open"
    assert stock(client, product) == 97

    # A fresh draft goes through; so does one with no version at all.
    ok(convert(client, challan["id"]))


def test_the_same_instant_with_an_offset_is_the_same_version(setup):
    client, ledger, product = setup
    challan = create_challan(client, ledger, [(product, 1)])
    payload = draft(client, challan["id"])["invoice"]
    seen = datetime.fromisoformat(payload["challan_updated_at"]).replace(tzinfo=timezone.utc)
    payload["challan_updated_at"] = seen.astimezone(timezone(timedelta(hours=5, minutes=30))).isoformat()
    ok(client.post(f"/api/delivery-challans/{challan['id']}/convert", json=payload))


def test_without_a_version_nothing_is_checked(setup):
    client, ledger, product = setup
    challan = create_challan(client, ledger, [(product, 1)])
    ok(client.post(f"/api/delivery-challans/{challan['id']}/convert", json={
        "ledger_id": ledger,
        "items": [{"product_id": product, "quantity": 1, "unit_price": 100}],
    }))
    assert get_challan(client, challan["id"])["status"] == "invoiced"


def test_reconverting_after_the_invoice_was_cancelled_keeps_the_history(setup):
    client, ledger, product = setup
    challan = create_challan(client, ledger, [(product, 2)])
    first = ok(convert(client, challan["id"]))
    ok(client.delete(f"/api/invoices/{first['id']}"))
    second = ok(convert(client, challan["id"]))
    after = get_challan(client, challan["id"])
    assert after["invoice_id"] == second["id"]
    assert [(row["id"], row["status"]) for row in after["invoices"]] == [
        (first["id"], "cancelled"), (second["id"], "active"),
    ]
    # The link is never cleared, even on the cancelled one.
    assert ok(client.get(f"/api/invoices/{first['id']}"))["source_challan_id"] == challan["id"]


def test_the_invoice_pdf_cites_the_challan_whatever_the_reference_notes_say(setup, db_session):
    client, ledger, product = setup
    challan = create_challan(client, ledger, [(product, 2)])
    invoice = ok(convert(client, challan["id"], reference_notes="PO 4471"))
    assert invoice["reference_notes"] == "PO 4471"
    row = db_session.query(Invoice).filter(Invoice.id == invoice["id"]).one()
    html = _build_invoice_html(row, db_session.query(Product).all())
    assert f"Against delivery challan {challan['challan_number']} dated {india_today():%d %b %Y}" in html
    assert "PO 4471" in html


def test_a_copy_of_the_invoice_is_not_linked_to_the_challan(setup, db_session):
    client, ledger, product = setup
    challan = create_challan(client, ledger, [(product, 2)])
    invoice = ok(convert(client, challan["id"]))
    copy = ok(client.post(f"/api/invoices/{invoice['id']}/duplicate"))
    assert ok(client.get(f"/api/invoices/{copy['id']}"))["source_challan_id"] is None
    # Nor does its PDF cite the challan it was not issued against.
    row = db_session.query(Invoice).filter(Invoice.id == copy["id"]).one()
    html = _build_invoice_html(row, db_session.query(Product).all())
    assert "delivery challan" not in html.lower()
    assert challan["challan_number"] not in html
    # A plain sale: it takes its own goods out.
    assert stock(client, product) == 96
    ok(client.delete(f"/api/invoices/{copy['id']}"))
    assert get_challan(client, challan["id"])["status"] == "invoiced"
    assert stock(client, product) == 98


def test_an_invoice_from_a_challan_cannot_turn_into_a_purchase(setup):
    client, ledger, product = setup
    challan = create_challan(client, ledger, [(product, 2)])
    invoice = ok(convert(client, challan["id"]))
    response = client.put(f"/api/invoices/{invoice['id']}", json={
        "ledger_id": ledger,
        "voucher_type": "purchase",
        "items": [{"product_id": product, "quantity": 2, "unit_price": 100}],
    })
    assert response.status_code == 400
    assert stock(client, product) == 98
