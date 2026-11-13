"""Optional TCS on sales invoices (#769)."""

import importlib.util
import json
from datetime import date
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

import pytest

from src.models.buyer import Buyer
from src.models.company import CompanyProfile
from src.models.invoice import Invoice
from src.models.tax_withholding_section import TaxWithholdingSection
from src.services.invoice_discounts import invoice_discount_amount

MIGRATION = Path(__file__).resolve().parents[2] / "migrations" / "20261107000001_add_tax_withholding_foundation.py"
SELLER_GSTIN = "29AAAAA0000A1Z5"
BUYER_GSTIN = "29ABCDE1234F1ZW"  # Same state: CGST + SGST.
APRIL = "2026-04-15"
MARCH = "2026-03-25"


def _seed_sections(db) -> None:
    """The section catalogue exactly as the #767 migration seeds it."""
    spec = importlib.util.spec_from_file_location("foundation_migration", MIGRATION)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    keys = ("kind", "act", "section_ref", "legacy_code", "nature", "rate_individual_huf", "rate_other",
            "rate_no_pan", "threshold_single", "threshold_aggregate", "threshold_note", "base",
            "effective_from", "effective_to")
    for row in module._SECTIONS:
        values = dict(zip(keys, row))
        values["effective_from"] = date.fromisoformat(values["effective_from"])
        values["effective_to"] = date.fromisoformat(values["effective_to"]) if values["effective_to"] else None
        for key in ("rate_individual_huf", "rate_other", "rate_no_pan"):
            values[key] = Decimal(str(values[key]))
        db.add(TaxWithholdingSection(**values))
    db.commit()


@pytest.fixture
def sections(db_session):
    _seed_sections(db_session)


@pytest.fixture
def company(client, db_session, sections):
    assert client.get("/api/company/").status_code == 200
    profile = db_session.query(CompanyProfile).first()
    profile.gst = SELLER_GSTIN
    profile.enable_tcs = True
    db_session.commit()
    return profile


def _section_id(db, section_ref: str) -> int:
    return db.query(TaxWithholdingSection.id).filter(TaxWithholdingSection.section_ref == section_ref).scalar()


def _ok(response, status=200):
    assert response.status_code == status, response.text
    return response.json()


def _ledger(client, *, gst="", pan=None, declaration=False, name="Scrap Buyer"):
    return _ok(client.post("/api/ledgers/", json={
        "name": name, "address": "Bengaluru", "gst": gst, "pan": pan, "phone_number": "9999999999",
        "tcs_declaration_received": declaration,
    }))["id"]


def _product(client, *, price=100000, gst_rate=18, sku="SCRAP-1"):
    return _ok(client.post("/api/products/", json={
        "sku": sku, "name": f"Scrap {sku}", "price": price, "gst_rate": gst_rate,
        "hsn_sac": "7204", "maintain_inventory": False,
    }))["id"]


def _invoice(client, ledger, product, *, when=APRIL, quantity=1, unit_price=100000, method="post", invoice_id=None, **extra):
    body = {
        "ledger_id": ledger, "voucher_type": "sales", "invoice_date": when,
        "items": [{"product_id": product, "quantity": quantity, "unit_price": unit_price}],
        **extra,
    }
    if method == "put":
        return client.put(f"/api/invoices/{invoice_id}", json=body)
    return client.post("/api/invoices/", json=body)


SCRAP_2025 = "394(1) Sl. No. 4"
SCRAP_1961 = "206C(1) Sl. No. (vi)"


# ── The scrap example from the issue ─────────────────────────────────────────


def test_scrap_example_collects_2360_and_totals_120360(client, db_session, company):
    ledger = _ledger(client, gst=BUYER_GSTIN)
    product = _product(client)

    body = _ok(_invoice(client, ledger, product, tcs_section_id=_section_id(db_session, SCRAP_2025)))

    assert body["taxable_amount"] == 100000
    assert body["total_tax_amount"] == 18000
    assert (body["cgst_amount"], body["sgst_amount"], body["igst_amount"]) == (9000, 9000, 0)
    assert body["tcs_section_ref"] == SCRAP_2025
    assert body["tcs_rate"] == 2
    assert body["tcs_base_amount"] == 118000
    assert body["tcs_amount"] == 2360
    assert body["total_amount"] == 120360
    assert body["remaining_amount"] == 120360


def test_round_off_is_applied_after_tcs(client, db_session, company):
    ledger = _ledger(client, gst=BUYER_GSTIN)
    product = _product(client, price=1234.56)

    body = _ok(_invoice(
        client, ledger, product, unit_price=1234.56, apply_round_off=True,
        tcs_section_id=_section_id(db_session, SCRAP_2025),
    ))

    # 1234.56 + 222.22 GST (111.11 each half) = 1456.78; TCS 2% = 29.14; 1485.92 -> 1486.
    assert body["tcs_base_amount"] == 1456.78
    assert body["tcs_amount"] == 29.14
    assert body["round_off_amount"] == 0.08
    assert body["total_amount"] == 1486
    total = Decimal(str(body["taxable_amount"])) + Decimal(str(body["total_tax_amount"])) \
        + Decimal(str(body["tcs_amount"])) + Decimal(str(body["round_off_amount"]))
    assert total == Decimal("1486")


def test_tcs_base_is_after_the_invoice_discount_and_the_discount_inverse_still_holds(client, db_session, company):
    ledger = _ledger(client, gst=BUYER_GSTIN)
    product = _product(client)

    body = _ok(_invoice(
        client, ledger, product, discount_type="net", discount_value=18000,
        tcs_section_id=_section_id(db_session, SCRAP_2025),
    ))

    assert body["tcs_base_amount"] == 100000
    assert body["tcs_amount"] == 2000
    assert body["total_amount"] == 102000
    invoice = db_session.get(Invoice, body["id"])
    assert invoice_discount_amount(invoice) == Decimal("18000.00")


def test_taxable_base_section_takes_the_pre_gst_share(client, db_session, company):
    row = db_session.query(TaxWithholdingSection).filter(TaxWithholdingSection.section_ref == SCRAP_2025).one()
    row.base = "taxable"
    db_session.commit()
    ledger = _ledger(client, gst=BUYER_GSTIN)
    product = _product(client)

    body = _ok(_invoice(client, ledger, product, tcs_section_id=row.id))

    assert body["tcs_base_amount"] == 100000
    assert body["tcs_amount"] == 2000


def test_typed_rate_and_amount_win_over_the_suggestion(client, db_session, company):
    ledger = _ledger(client, gst=BUYER_GSTIN)
    product = _product(client)
    section = _section_id(db_session, SCRAP_2025)

    rate_only = _ok(_invoice(client, ledger, product, tcs_section_id=section, tcs_rate=1))
    assert (rate_only["tcs_rate"], rate_only["tcs_amount"], rate_only["total_amount"]) == (1, 1180, 119180)

    typed = _ok(_invoice(client, ledger, product, tcs_section_id=section, tcs_rate=2, tcs_amount=2000))
    assert (typed["tcs_amount"], typed["total_amount"]) == (2000, 120000)


# ── Dates pick the Act ───────────────────────────────────────────────────────


def test_march_2026_offers_1961_sections_and_april_2026_offers_2025_sections(client, company):
    march = _ok(client.get("/api/tax-withholding-sections", params={"kind": "tcs", "date": MARCH}))
    april = _ok(client.get("/api/tax-withholding-sections", params={"kind": "tcs", "date": APRIL}))

    assert {row["act"] for row in march} == {1961}
    assert {row["act"] for row in april} == {2025}
    march_scrap = next(row for row in march if row["nature"] == "Sale of scrap")
    april_scrap = next(row for row in april if row["nature"] == "Sale of scrap")
    assert (march_scrap["section_ref"], march_scrap["rate_other"]) == (SCRAP_1961, 1)
    assert (april_scrap["section_ref"], april_scrap["rate_other"]) == (SCRAP_2025, 2)
    liquor = next(row for row in april if row["nature"].startswith("Sale of alcoholic"))
    assert liquor["rate_other"] == 2  # Finance Act 2026: was 1%.


def test_invoice_dated_25_march_2026_uses_the_1961_section_and_rate(client, db_session, company):
    ledger = _ledger(client, gst=BUYER_GSTIN)
    product = _product(client)

    wrong = _invoice(client, ledger, product, when=MARCH, tcs_section_id=_section_id(db_session, SCRAP_2025))
    assert wrong.status_code == 400
    assert "not in force on 2026-03-25" in wrong.json()["detail"]

    body = _ok(_invoice(client, ledger, product, when=MARCH, tcs_section_id=_section_id(db_session, SCRAP_1961)))
    assert (body["tcs_section_ref"], body["tcs_rate"], body["tcs_amount"], body["total_amount"]) == (
        SCRAP_1961, 1, 1180, 119180,
    )


# ── Who pays what ────────────────────────────────────────────────────────────


def test_buyer_without_pan_is_suggested_the_no_pan_rate(client, db_session, company):
    ledger = _ledger(client)  # No GSTIN, no PAN.
    product = _product(client)

    body = _ok(_invoice(client, ledger, product, tcs_section_id=_section_id(db_session, SCRAP_2025)))

    # s.397(2): the higher of twice 2% or 5%, capped at 20%.
    assert (body["tcs_rate"], body["tcs_amount"], body["total_amount"]) == (5, 5900, 123900)


def test_buyer_with_a_pan_but_no_gstin_gets_the_normal_rate(client, db_session, company):
    ledger = _ledger(client, pan="ABCDE1234F")
    product = _product(client)

    body = _ok(_invoice(client, ledger, product, tcs_section_id=_section_id(db_session, SCRAP_2025)))

    assert body["tcs_rate"] == 2


def test_seeded_no_pan_rates_follow_section_397_2(db_session, sections):
    rows = db_session.query(TaxWithholdingSection).filter(TaxWithholdingSection.kind == "tcs").all()
    assert rows
    for row in rows:
        expected = min(max(2 * row.rate_other, Decimal("5")), Decimal("20"))
        assert row.rate_no_pan == expected, row.section_ref


def test_declaration_received_suggests_no_tcs_on_scrap(client, db_session, company):
    ledger = _ledger(client, gst=BUYER_GSTIN, declaration=True)
    product = _product(client)

    body = _ok(_invoice(client, ledger, product, tcs_section_id=_section_id(db_session, SCRAP_2025)))

    assert (body["tcs_rate"], body["tcs_amount"], body["total_amount"]) == (0, 0, 118000)
    ledger_body = _ok(client.get(f"/api/ledgers/{ledger}"))
    assert ledger_body["tcs_declaration_received"] is True


def test_declaration_does_not_cover_motor_vehicles(db_session, sections):
    from src.services.tcs import suggest_tcs_rate

    vehicle = db_session.query(TaxWithholdingSection).filter(TaxWithholdingSection.section_ref == "394(1) Sl. No. 6").one()
    buyer = SimpleNamespace(pan="ABCDE1234F", gst=None, party_type="company", tcs_declaration_received=True)
    assert suggest_tcs_rate(vehicle, buyer) == Decimal("1")


# ── Off by default ───────────────────────────────────────────────────────────


def test_setting_is_off_by_default_and_saves_through_the_company_profile(client, db_session, sections):
    profile = _ok(client.get("/api/company/"))
    assert profile["enable_tcs"] is False
    payload = {key: profile[key] for key in ("name", "address", "gst", "phone_number")}
    assert _ok(client.put("/api/company/", json={**payload, "enable_tcs": True}))["enable_tcs"] is True
    # A client that does not know the setting keeps it.
    assert _ok(client.put("/api/company/", json=payload))["enable_tcs"] is True


def test_with_tcs_off_a_tcs_section_is_refused_and_totals_are_unchanged(client, db_session, sections):
    assert client.get("/api/company/").status_code == 200
    ledger = _ledger(client, gst=BUYER_GSTIN)
    product = _product(client)

    refused = _invoice(client, ledger, product, tcs_section_id=_section_id(db_session, SCRAP_2025))
    assert refused.status_code == 400
    assert "turned off" in refused.json()["detail"]

    body = _ok(_invoice(client, ledger, product, apply_round_off=True))
    assert (body["taxable_amount"], body["total_tax_amount"], body["total_amount"]) == (100000, 18000, 118000)
    assert (body["tcs_section_id"], body["tcs_rate"], body["tcs_base_amount"], body["tcs_amount"]) == (None, None, 0, 0)


def test_turning_tcs_off_keeps_an_existing_tcs_invoice_editable(client, db_session, company):
    ledger = _ledger(client, gst=BUYER_GSTIN)
    product = _product(client)
    section = _section_id(db_session, SCRAP_2025)
    created = _ok(_invoice(client, ledger, product, tcs_section_id=section))
    company.enable_tcs = False
    db_session.commit()

    edited = _ok(_invoice(
        client, ledger, product, method="put", invoice_id=created["id"], quantity=2, tcs_section_id=section,
    ))
    assert (edited["tcs_amount"], edited["total_amount"]) == (4720, 240720)


def test_purchase_invoices_cannot_carry_tcs(client, db_session, company):
    ledger = _ledger(client, gst=BUYER_GSTIN)
    product = _product(client)

    response = client.post("/api/invoices/", json={
        "ledger_id": ledger, "voucher_type": "purchase", "invoice_date": APRIL, "supplier_invoice_number": "S-1",
        "items": [{"product_id": product, "quantity": 1, "unit_price": 100}],
        "tcs_section_id": _section_id(db_session, SCRAP_2025),
    })
    assert response.status_code == 400


# ── GST returns ignore TCS ───────────────────────────────────────────────────


def _strip_values(node):
    if isinstance(node, dict):
        return {key: _strip_values(value) for key, value in node.items() if key != "val"}
    if isinstance(node, list):
        return [_strip_values(value) for value in node]
    return node


def test_gstr1_and_gstr3b_taxable_values_and_tax_are_unchanged_by_tcs(client, db_session, company):
    ledger = _ledger(client, gst=BUYER_GSTIN)
    product = _product(client)
    period = {"from_date": "2026-04-01", "to_date": "2026-04-30"}
    created = _ok(_invoice(client, ledger, product))

    gstr1_before = json.loads(_ok_raw(client.get("/api/ledgers/tax-ledger/gstr1/export-json", params=period)))
    gstr3b_before = _ok(client.get("/api/ledgers/tax-ledger/gstr3b/worksheet", params=period))

    _ok(_invoice(
        client, ledger, product, method="put", invoice_id=created["id"],
        tcs_section_id=_section_id(db_session, SCRAP_2025),
    ))
    gstr1_after = json.loads(_ok_raw(client.get("/api/ledgers/tax-ledger/gstr1/export-json", params=period)))
    gstr3b_after = _ok(client.get("/api/ledgers/tax-ledger/gstr3b/worksheet", params=period))

    assert gstr3b_after == gstr3b_before
    assert _strip_values(gstr1_after) == _strip_values(gstr1_before)
    b2b_after = gstr1_after["b2b"][0]["inv"][0]
    assert b2b_after["itms"][0]["itm_det"]["txval"] == 100000
    # The invoice value is the document's value, TCS included (see PR notes).
    assert b2b_after["val"] == 120360


def _ok_raw(response):
    assert response.status_code == 200, response.text
    return response.content


# ── Credit notes ─────────────────────────────────────────────────────────────


def _credit(client, invoice, quantity, item_index=0):
    return _ok(client.post("/api/credit-notes/", json={
        "ledger_id": invoice["ledger_id"],
        "invoice_ids": [invoice["id"]],
        "credit_note_type": "return",
        "direction": "outward",
        "credit_note_date": invoice["invoice_date"][:10],
        "items": [{"invoice_id": invoice["id"], "invoice_item_id": invoice["items"][item_index]["id"], "quantity": quantity}],
    }), 201)


def test_full_credit_note_settles_the_whole_tcs_invoice(client, db_session, company):
    ledger = _ledger(client, gst=BUYER_GSTIN)
    product = _product(client)
    invoice = _ok(_invoice(client, ledger, product, tcs_section_id=_section_id(db_session, SCRAP_2025)))

    note = _credit(client, invoice, 1)

    assert note["tcs_amount"] == 2360
    assert note["items"][0]["tcs_amount"] == 2360
    assert note["total_amount"] == 120360
    assert (note["taxable_amount"], note["cgst_amount"], note["sgst_amount"]) == (100000, 9000, 9000)
    after = _ok(client.get(f"/api/invoices/{invoice['id']}"))
    assert after["remaining_amount"] == 0
    assert after["payment_status"] == "paid"
    assert after["credit_status"] == "fully_credited"


def test_credit_notes_in_parts_reverse_exactly_the_invoice_tcs(client, db_session, company):
    ledger = _ledger(client, gst=BUYER_GSTIN)
    product = _product(client, price=333.33)
    invoice = _ok(_invoice(
        client, ledger, product, quantity=3, unit_price=333.33,
        tcs_section_id=_section_id(db_session, SCRAP_2025),
    ))

    first = _credit(client, invoice, 1)
    middle = _ok(client.get(f"/api/invoices/{invoice['id']}"))
    assert middle["credit_status"] == "partially_credited"
    assert middle["remaining_amount"] > 0
    second = _credit(client, invoice, 2)

    reversed_tcs = Decimal(str(first["tcs_amount"])) + Decimal(str(second["tcs_amount"]))
    assert reversed_tcs == Decimal(str(invoice["tcs_amount"]))
    after = _ok(client.get(f"/api/invoices/{invoice['id']}"))
    assert after["remaining_amount"] == 0
    assert after["credit_status"] == "fully_credited"


# ── Copies ───────────────────────────────────────────────────────────────────


def test_duplicate_copies_the_tcs_onto_todays_section(client, db_session, company):
    ledger = _ledger(client, gst=BUYER_GSTIN)
    product = _product(client)
    march = _ok(_invoice(client, ledger, product, when=MARCH, tcs_section_id=_section_id(db_session, SCRAP_1961)))
    april = _ok(_invoice(
        client, ledger, product, tcs_section_id=_section_id(db_session, SCRAP_2025), tcs_rate=2, tcs_amount=2000,
    ))

    def duplicate(invoice):
        copy_id = _ok(client.post(f"/api/invoices/{invoice['id']}/duplicate"))["id"]
        return _ok(client.get(f"/api/invoices/{copy_id}"))

    march_copy = duplicate(march)
    april_copy = duplicate(april)

    # The 1961 row is no longer in force today, so the copy moves to the 2025 row
    # for the same goods, at its rate.
    assert (march_copy["tcs_section_ref"], march_copy["tcs_rate"], march_copy["tcs_amount"]) == (SCRAP_2025, 2, 2360)
    # Same section: the typed amount travels with it.
    assert (april_copy["tcs_section_ref"], april_copy["tcs_amount"], april_copy["total_amount"]) == (SCRAP_2025, 2000, 120000)


@pytest.mark.parametrize("old_ref", ["206C(1) Sl. No. (iii)", "206C(1) Sl. No. (iv)"])
def test_duplicate_of_a_1961_timber_invoice_moves_to_the_2025_timber_row(client, db_session, company, old_ref):
    ledger = _ledger(client, gst=BUYER_GSTIN)
    product = _product(client)
    march = _ok(_invoice(client, ledger, product, when=MARCH, tcs_section_id=_section_id(db_session, old_ref)))
    copy_id = _ok(client.post(f"/api/invoices/{march['id']}/duplicate"))["id"]
    copy = _ok(client.get(f"/api/invoices/{copy_id}"))
    assert (copy["tcs_section_ref"], copy["tcs_rate"]) == ("394(1) Sl. No. 3", 2)


def test_buyer_pan_is_kept_on_the_invoice_when_the_ledger_changes(client, db_session, company):
    ledger = _ledger(client, gst=BUYER_GSTIN)
    product = _product(client)
    inv = _ok(_invoice(client, ledger, product, tcs_section_id=_section_id(db_session, SCRAP_2025)))
    assert db_session.query(Invoice.ledger_pan).filter(Invoice.id == inv["id"]).scalar() == "ABCDE1234F"
    plain = _ok(_invoice(client, ledger, product))
    assert db_session.query(Invoice.ledger_pan).filter(Invoice.id == plain["id"]).scalar() is None
    db_session.query(Buyer).filter(Buyer.id == ledger).update({"gst": "", "pan": "ZZZZZ9999Z"})
    db_session.commit()
    report = _ok(client.get("/api/reports/tcs-collected", params={"tax_year": 2026}))
    assert [r["buyer_pan"] for r in report["rows"]] == ["ABCDE1234F"]


def test_quotation_quotes_tcs_and_conversion_copies_it(client, db_session, company):
    ledger = _ledger(client, gst=BUYER_GSTIN)
    product = _product(client)
    section = _section_id(db_session, SCRAP_2025)
    quotation = _ok(client.post("/api/quotations/", json={
        "ledger_id": ledger, "quotation_date": APRIL,
        "items": [{"product_id": product, "quantity": 1, "unit_price": 100000}],
        "tcs_section_id": section,
    }))
    assert (quotation["tcs_amount"], quotation["total_amount"]) == (2360, 120360)
    assert (quotation["taxable_amount"], quotation["total_tax_amount"]) == (100000, 18000)

    draft = _ok(client.get(f"/api/quotations/{quotation['id']}/conversion-draft"))
    assert draft["invoice"]["tcs_section_id"] == section
    assert draft["invoice"]["tcs_rate"] == 2

    invoice = _ok(client.post(f"/api/quotations/{quotation['id']}/convert", json=draft["invoice"]))
    assert (invoice["tcs_amount"], invoice["total_amount"]) == (2360, 120360)


def test_quotation_without_tcs_is_unchanged(client, db_session, company):
    ledger = _ledger(client, gst=BUYER_GSTIN)
    product = _product(client)
    quotation = _ok(client.post("/api/quotations/", json={
        "ledger_id": ledger, "quotation_date": APRIL, "apply_round_off": True,
        "items": [{"product_id": product, "quantity": 1, "unit_price": 99.99}],
    }))
    assert (quotation["total_amount"], quotation["round_off_amount"], quotation["tcs_amount"]) == (118, 0.01, 0)
    draft = _ok(client.get(f"/api/quotations/{quotation['id']}/conversion-draft"))
    assert draft["invoice"]["tcs_section_id"] is None


# ── Review fixes ─────────────────────────────────────────────────────────────


def test_cancelling_a_middle_credit_note_leaves_no_paisa_behind(client, db_session, company):
    ledger = _ledger(client, gst=BUYER_GSTIN)
    product = _product(client, price=1000, gst_rate=0)
    invoice = _ok(_invoice(
        client, ledger, product, quantity=3, unit_price=1000,
        tcs_section_id=_section_id(db_session, SCRAP_2025), tcs_rate=2, tcs_amount=100.01,
    ))
    note_a = _credit(client, invoice, 1)
    _credit(client, invoice, 1)
    assert client.post(f"/api/credit-notes/{note_a['id']}/cancel").status_code == 200
    _credit(client, invoice, 2)

    from src.models.credit_note import CreditNote

    active = db_session.query(CreditNote).filter(CreditNote.status == "active").all()
    assert sum((Decimal(str(note.tcs_amount)) for note in active), Decimal("0")) == Decimal("100.01")
    after = _ok(client.get(f"/api/invoices/{invoice['id']}"))
    assert after["remaining_amount"] == 0
    assert after["credit_status"] == "fully_credited"


def test_a_rate_beyond_three_places_is_stored_and_used_as_rounded(client, db_session, company):
    ledger = _ledger(client, gst=BUYER_GSTIN)
    product = _product(client)

    body = _ok(_invoice(client, ledger, product, tcs_section_id=_section_id(db_session, SCRAP_2025), tcs_rate=1.2345))

    # 1.2345 is kept as 1.235 (NUMERIC(7,3)), and the amount comes from 1.235.
    assert body["tcs_rate"] == 1.235
    assert body["tcs_amount"] == 1457.30  # 118000 x 1.235%, not 1456.71 from 1.2345


def test_out_of_range_tcs_rate_and_amount_are_refused(client, db_session, company):
    ledger = _ledger(client, gst=BUYER_GSTIN)
    product = _product(client)
    section = _section_id(db_session, SCRAP_2025)
    assert _invoice(client, ledger, product, tcs_section_id=section, tcs_rate=101).status_code == 422
    assert _invoice(client, ledger, product, tcs_section_id=section, tcs_rate=-1).status_code == 422
    assert _invoice(client, ledger, product, tcs_section_id=section, tcs_amount=-5).status_code == 422
