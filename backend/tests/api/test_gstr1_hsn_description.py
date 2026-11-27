"""GSTR-1 HSN summary description and the CSV HSN/SAC column (#1131)."""
import csv
from io import StringIO

from tests.api.test_gstr1_filing_edges import _create_ledger, _create_product, _export, _line, _period, _sale, seller  # noqa: F401


def _csv_rows(client):
    response = client.get("/api/ledgers/tax-ledger/gstr1/export-csv", params=_period())
    assert response.status_code == 200, response.text
    return list(csv.DictReader(StringIO(response.content.decode("utf-8-sig"))))


def test_two_lines_of_one_hsn_use_the_product_name_and_list_the_code_once(client, seller):
    a = _create_product(client, "H-1", "Hydraulic Press", hsn_sac="8479")
    b = _create_product(client, "H-2", "Mixing Machine", hsn_sac="8479")
    _sale(client, _create_ledger(client, "Walk-in"), a, items=[_line(a, 1, 1000), _line(b, 2, 500)])

    rows = _export(client)["hsn"]["hsn_b2c"]
    assert len(rows) == 1
    assert rows[0]["hsn_sc"] == "8479"
    assert rows[0]["desc"] == "Hydraulic Press"
    assert rows[0]["txval"] == 2000.0
    assert _csv_rows(client)[0]["HSN/SAC"] == "8479"

    summary = client.get("/api/ledgers/tax-ledger/gstr1/summary", params=_period()).json()
    assert [i["description"] for i in summary["hsn_summary"]] == ["Hydraulic Press"]


def test_different_hsns_stay_comma_separated_in_order(client, seller):
    a = _create_product(client, "H-3", "Press", hsn_sac="8479")
    b = _create_product(client, "H-4", "Phone", hsn_sac="8517")
    _sale(client, _create_ledger(client, "Walk-in"), a, items=[_line(a, 1, 100), _line(b, 1, 100), _line(a, 1, 100)])

    assert _csv_rows(client)[0]["HSN/SAC"] == "8479, 8517"
    assert {r["hsn_sc"]: r["desc"] for r in _export(client)["hsn"]["hsn_b2c"]} == {"8479": "Press", "8517": "Phone"}


def test_a_line_description_still_wins_over_the_product_name(client, seller):
    a = _create_product(client, "H-5", "Press", hsn_sac="8479")
    _sale(client, _create_ledger(client, "Walk-in"), a, items=[{**_line(a, 1, 100), "description": "Custom press"}])

    assert _export(client)["hsn"]["hsn_b2c"][0]["desc"] == "Custom press"
