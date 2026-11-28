"""#1154 through the API: new documents take the bill discount before GST, old ones keep theirs.

The worked example throughout: Demo Gift Hamper 1 x 300 at 18%, a flat 50 off, an
intrastate buyer. Before GST it is 250 taxable + 22.50 + 22.50 = 295.00; an invoice
saved before #1154 took the 50 off after GST, 354.00 - 50 = 304.00, and keeps it.
"""

import calendar
import json

import pytest

from src.services.gst_tax_service import india_today
from tests.api.legacy_discount import create_invoice_after_gst, create_quotation_after_gst
from tests.api.quotation_helpers import GST_KA, create_ledger, create_product, ok, seed_company
from tests.api.test_place_of_supply import MAHARASHTRA_BUYER

TODAY = india_today()


@pytest.fixture
def shop(client):
    seed_company(client)
    buyer = create_ledger(client, "Demo Customer", gst=MAHARASHTRA_BUYER)
    hamper = create_product(client, "DEMO-HAMP", name="Demo Gift Hamper", price=300, hsn_sac="2106")
    atta = create_product(client, "DEMO-ATTA", name="Demo Atta 5kg", price=200, gst_rate=5, hsn_sac="1101")
    return {"buyer": buyer["id"], "hamper": hamper["id"], "atta": atta["id"]}


def _invoice_body(shop, *, lines=None, **extra):
    return {
        "ledger_id": shop["buyer"],
        "voucher_type": "sales",
        "invoice_date": TODAY.isoformat(),
        "items": lines or [{"product_id": shop["hamper"], "quantity": 1, "unit_price": 300}],
        **extra,
    }


FLAT_50 = {"discount_type": "net", "discount_value": 50}


def _figures(document):
    return (
        document["taxable_amount"], document["cgst_amount"], document["sgst_amount"],
        document["igst_amount"], document["total_amount"],
    )


class TestCreate:
    def test_a_new_invoice_takes_the_discount_before_gst(self, client, shop):
        invoice = ok(client.post("/api/invoices/", json=_invoice_body(shop, **FLAT_50)))

        assert invoice["discount_mode"] == "before_tax"
        assert _figures(invoice) == (250, 22.5, 22.5, 0, 295)
        assert invoice["total_tax_amount"] == 45
        assert invoice["items"][0]["bill_discount_amount"] == 50
        assert (invoice["discount_type"], invoice["discount_value"]) == ("net", 50)

    def test_asking_for_after_gst_on_a_new_invoice_is_refused(self, client, shop):
        response = client.post("/api/invoices/", json=_invoice_body(shop, discount_mode="after_tax", **FLAT_50))
        assert response.status_code == 422
        assert response.json()["detail"] == "New documents take the discount before GST."

    def test_a_discount_over_the_subtotal_is_refused(self, client, shop):
        response = client.post("/api/invoices/", json=_invoice_body(shop, discount_type="net", discount_value=350))
        assert response.status_code == 400
        assert response.json()["detail"] == "The discount (₹350.00) is more than the subtotal (₹300.00)."
        assert client.get("/api/invoices/").json()["items"] == []

    def test_a_discount_equal_to_the_subtotal_saves_a_zero_invoice(self, client, shop):
        invoice = ok(client.post("/api/invoices/", json=_invoice_body(shop, discount_type="net", discount_value=300)))
        assert _figures(invoice) == (0, 0, 0, 0, 0)

    def test_a_percentage_over_100_is_refused(self, client, shop):
        response = client.post("/api/invoices/", json=_invoice_body(shop, discount_type="percentage", discount_value=101))
        assert response.status_code == 422

    def test_inter_state(self, client, shop):
        other = create_ledger(client, "Demo Bengaluru", gst=GST_KA)
        invoice = ok(client.post("/api/invoices/", json=_invoice_body({**shop, "buyer": other["id"]}, **FLAT_50)))
        assert _figures(invoice) == (250, 0, 0, 45, 295)

    def test_a_new_quotation_takes_the_discount_before_gst(self, client, shop):
        body = _invoice_body(shop, **FLAT_50)
        body.pop("voucher_type")
        body.pop("invoice_date")
        quotation = ok(client.post("/api/quotations/", json={**body, "document_type": "quotation"}))
        assert quotation["discount_mode"] == "before_tax"
        assert _figures(quotation) == (250, 22.5, 22.5, 0, 295)
        assert quotation["items"][0]["bill_discount_amount"] == 50


class TestOldInvoices:
    def test_an_old_invoice_keeps_its_total_until_it_is_switched(self, client, shop):
        body = _invoice_body(shop, **FLAT_50)
        old = create_invoice_after_gst(client, body)
        assert _figures(old) == (300, 27, 27, 0, 304)
        listed = client.get("/api/invoices/").json()["items"]
        assert [row["total_amount"] for row in listed] == [304]

        kept = ok(client.put(f"/api/invoices/{old['id']}", json=body))
        assert (kept["discount_mode"], kept["total_amount"]) == ("after_tax", 304)
        assert kept["items"][0]["bill_discount_amount"] == 0
        also_kept = ok(client.put(f"/api/invoices/{old['id']}", json={**body, "discount_mode": "after_tax"}))
        assert also_kept["total_amount"] == 304

        switched = ok(client.put(f"/api/invoices/{old['id']}", json={**body, "discount_mode": "before_tax"}))
        assert (switched["discount_mode"], switched["total_amount"]) == ("before_tax", 295)

        back = client.put(f"/api/invoices/{old['id']}", json={**body, "discount_mode": "after_tax"})
        assert back.status_code == 422

    def test_duplicating_an_old_invoice_makes_a_before_gst_one(self, client, shop):
        old = create_invoice_after_gst(client, _invoice_body(shop, **FLAT_50))
        copy = ok(client.post(f"/api/invoices/{old['id']}/duplicate"))
        duplicate = ok(client.get(f"/api/invoices/{copy['id']}"))
        assert (duplicate["discount_mode"], duplicate["total_amount"]) == ("before_tax", 295)


class TestQuotationConversion:
    def _quotation_body(self, shop):
        return {
            "document_type": "quotation",
            "ledger_id": shop["buyer"],
            "items": [{"product_id": shop["hamper"], "quantity": 1, "unit_price": 300}],
            **FLAT_50,
        }

    def test_an_old_quotation_converts_before_gst_and_the_draft_names_its_total(self, client, shop):
        old = create_quotation_after_gst(client, self._quotation_body(shop))
        assert old["total_amount"] == 304

        draft = ok(client.get(f"/api/quotations/{old['id']}/conversion-draft"))
        assert (draft["quotation_discount_mode"], draft["quotation_total_amount"]) == ("after_tax", 304)
        invoice = ok(client.post(f"/api/quotations/{old['id']}/convert", json=draft["invoice"]))
        assert (invoice["discount_mode"], invoice["total_amount"]) == ("before_tax", 295)

    def test_a_new_quotation_converts_to_the_same_figures(self, client, shop):
        quotation = ok(client.post("/api/quotations/", json=self._quotation_body(shop)))
        draft = ok(client.get(f"/api/quotations/{quotation['id']}/conversion-draft"))
        assert (draft["quotation_discount_mode"], draft["quotation_total_amount"]) == ("before_tax", 295)
        invoice = ok(client.post(f"/api/quotations/{quotation['id']}/convert", json=draft["invoice"]))
        assert _figures(invoice) == _figures(quotation)

    def test_an_old_quotation_keeps_its_way_on_edit_and_its_copy_is_before_gst(self, client, shop):
        old = create_quotation_after_gst(client, self._quotation_body(shop))
        update = {key: value for key, value in self._quotation_body(shop).items() if key != "document_type"}
        kept = ok(client.put(f"/api/quotations/{old['id']}", json=update))
        assert (kept["discount_mode"], kept["total_amount"]) == ("after_tax", 304)
        copy = ok(client.post(f"/api/quotations/{old['id']}/duplicate"))
        assert (copy["discount_mode"], copy["total_amount"]) == ("before_tax", 295)


class TestReturnsAndReports:
    def _period(self):
        """The whole month the invoices are dated in: a return covers whole months."""
        last_day = calendar.monthrange(TODAY.year, TODAY.month)[1]
        return {"from_date": TODAY.replace(day=1).isoformat(), "to_date": TODAY.replace(day=last_day).isoformat()}

    def _gstr1(self, client):
        response = client.get("/api/ledgers/tax-ledger/gstr1/export-json", params=self._period())
        assert response.status_code == 200, response.text
        return json.loads(response.content)

    def test_gstr1_files_the_reduced_taxable_value(self, client, shop):
        new = ok(client.post("/api/invoices/", json=_invoice_body(shop, **FLAT_50)))

        filed = self._gstr1(client)
        [invoice] = [entry for party in filed["b2b"] for entry in party["inv"]]
        assert (invoice["inum"], invoice["val"]) == (new["invoice_number"], 295)
        [item] = invoice["itms"]
        assert (item["itm_det"]["txval"], item["itm_det"]["camt"], item["itm_det"]["samt"]) == (250, 22.5, 22.5)
        [hsn] = filed["hsn"]["hsn_b2b"]
        assert (hsn["txval"], hsn["camt"], hsn["samt"]) == (250, 22.5, 22.5)

    def test_an_old_invoice_files_as_it_always_did(self, client, shop):
        create_invoice_after_gst(client, _invoice_body(shop, **FLAT_50))

        filed = self._gstr1(client)
        [invoice] = [entry for party in filed["b2b"] for entry in party["inv"]]
        assert invoice["val"] == 304
        [item] = invoice["itms"]
        assert (item["itm_det"]["txval"], item["itm_det"]["camt"], item["itm_det"]["samt"]) == (300, 27, 27)

    def test_gstr3b_names_only_the_old_invoice(self, client, shop):
        new = ok(client.post("/api/invoices/", json=_invoice_body(shop, **FLAT_50)))
        old = create_invoice_after_gst(client, _invoice_body(shop, **FLAT_50))
        sheet = ok(client.get("/api/ledgers/tax-ledger/gstr3b/worksheet", params=self._period()))
        warning = next(w for w in sheet["warnings"] if w["code"] == "invoice_level_discount")
        numbers = [document["number"] for document in warning["documents"]]
        assert numbers == [old["invoice_number"]]
        assert new["invoice_number"] not in numbers

    def test_reports_count_the_discounted_revenue_once_and_name_the_discount(self, client, shop):
        ok(client.post("/api/invoices/", json=_invoice_body(shop, **FLAT_50)))
        params = self._period()

        sales = ok(client.get("/api/analytics/sales-by-product", params=params))
        assert sales["rows"][0]["sales_amount"] == 250
        assert sales["rows"][0]["total_revenue"] == 295
        profit = ok(client.get("/api/analytics/profit-loss", params=params))
        assert profit["totals"]["revenue"] == 250
        performance = ok(client.get("/api/analytics/product-performance", params=params))
        assert [row["revenue"] for row in performance["rows"] if row["name"] == "Demo Gift Hamper"] == [250]
        month = ok(client.get("/api/analytics/sales-by-month", params=params))
        assert (month["totals"]["taxable_value"], month["totals"]["discount_given"]) == (250, 50)

    def test_discount_given_is_50_for_the_old_and_the_new_invoice(self, client, shop):
        ok(client.post("/api/invoices/", json=_invoice_body(shop, **FLAT_50)))
        create_invoice_after_gst(client, _invoice_body(shop, **FLAT_50))
        month = ok(client.get("/api/analytics/sales-by-month", params=self._period()))
        assert month["totals"]["discount_given"] == 100
        assert month["totals"]["total_sales"] == 295 + 304
