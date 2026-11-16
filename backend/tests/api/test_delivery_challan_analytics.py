"""Delivery challan events fire from the backend, after commit, with no names or GSTINs."""

from datetime import timedelta

import pytest
from challan_helpers import convert, create_challan, create_ledger, create_product, ok, seed_company, update_challan

from src.core import analytics
from src.services.gst_tax_service import india_today


class RecordingClient:
    def __init__(self):
        self.captured = []

    def capture(self, event=None, distinct_id=None, properties=None, **_):
        self.captured.append((event, distinct_id, properties or {}))

    def capture_exception(self, *args, **kwargs):
        pass

    def shutdown(self):
        pass


@pytest.fixture
def events(monkeypatch):
    recorder = RecordingClient()
    monkeypatch.setattr(analytics, "_client", recorder)
    monkeypatch.setattr(analytics, "_init_attempted", True)
    yield recorder
    analytics.bind_request(None, "api")


@pytest.fixture
def setup(client):
    seed_company(client)
    return client, create_ledger(client)["id"], create_product(client)["id"], create_product(client, "B-1")["id"]


def _find(events, name):
    return [props for event, _, props in events.captured if event == name]


def _names(events):
    return [event for event, _, _ in events.captured]


def test_created_updated_cancelled(setup, events):
    client, ledger, a, b = setup
    day = india_today() - timedelta(days=4)
    challan = create_challan(client, ledger, [(a, 2), (b, 1)], purpose="job_work", challan_date=day.isoformat())
    (created,) = _find(events, "delivery_challan_created")
    assert created == {
        **created,
        "challan_id": challan["id"],
        "purpose": "job_work",
        "line_item_count": 2,
        "taxable_amount": 300,
        "number_typed": False,
    }

    ok(update_challan(client, challan, [(a, 1)], purpose="exhibition"))
    (updated,) = _find(events, "delivery_challan_updated")
    assert updated == {
        **updated,
        "challan_id": challan["id"],
        "purpose": "exhibition",
        "line_item_count": 1,
        "taxable_amount": 100,
    }

    ok(client.post(f"/api/delivery-challans/{challan['id']}/cancel"))
    (cancelled,) = _find(events, "delivery_challan_cancelled")
    assert cancelled == {**cancelled, "challan_id": challan["id"], "purpose": "exhibition", "age_days": 4}


def test_a_typed_number_is_reported_as_such(setup, events):
    client, ledger, a, _ = setup
    create_challan(client, ledger, [(a, 1)], challan_number="JW-1")
    (created,) = _find(events, "delivery_challan_created")
    assert created["number_typed"] is True


def test_converted_and_invoice_created(setup, events):
    client, ledger, a, b = setup
    day = india_today() - timedelta(days=2)
    challan = create_challan(client, ledger, [(a, 10)], challan_date=day.isoformat(), purpose="own_use")
    invoice = ok(convert(client, challan["id"], quantities={a: 8}, extra_lines=[(b, 1)]))

    (converted,) = _find(events, "delivery_challan_converted")
    assert converted == {
        **converted,
        "challan_id": challan["id"],
        "invoice_id": invoice["id"],
        "purpose": "own_use",
        "days_since_challan": 2,
        "quantity_changed": True,
        "extra_lines": 1,
    }
    (created,) = _find(events, "invoice_created")
    assert created["source"] == "delivery_challan"
    assert created["invoice_id"] == invoice["id"]
    # The invoice event first, as quotations do.
    assert _names(events).index("invoice_created") < _names(events).index("delivery_challan_converted")


def test_converted_unchanged(setup, events):
    client, ledger, a, _ = setup
    challan = create_challan(client, ledger, [(a, 3), (a, 2)])
    ok(convert(client, challan["id"]))
    (converted,) = _find(events, "delivery_challan_converted")
    assert converted["quantity_changed"] is False
    assert converted["extra_lines"] == 0
    assert converted["days_since_challan"] == 0


def test_a_dropped_line_counts_as_changed(setup, events):
    client, ledger, a, b = setup
    challan = create_challan(client, ledger, [(a, 3), (b, 2)])
    ok(convert(client, challan["id"], drop={b}))
    (converted,) = _find(events, "delivery_challan_converted")
    assert converted["quantity_changed"] is True


def test_pdf_downloaded(setup, events):
    client, ledger, a, _ = setup
    challan = create_challan(client, ledger, [(a, 1)])
    response = client.get(f"/api/delivery-challans/{challan['id']}/pdf", params={"copies": 3})
    assert response.status_code == 200, response.text[:300]
    assert response.headers["content-type"] == "application/pdf"
    assert f"delivery_challan_{challan['challan_number']}.pdf" in response.headers["content-disposition"]
    (downloaded,) = _find(events, "delivery_challan_pdf_downloaded")
    assert downloaded == {**downloaded, "challan_id": challan["id"], "copies": 3}
    assert client.get(f"/api/delivery-challans/{challan['id']}/pdf", params={"copies": 4}).status_code == 422


def test_failures_send_nothing(setup, events):
    client, ledger, a, _ = setup
    response = client.post("/api/delivery-challans/", json={
        "ledger_id": ledger, "items": [{"product_id": a, "quantity": 1000}],
    })
    assert response.status_code == 400
    assert not [name for name in _names(events) if name.startswith("delivery_challan")]


def test_no_names_or_gstins_in_any_event(setup, events):
    client, ledger, a, _ = setup
    challan = create_challan(client, ledger, [(a, 1)], reference_notes="Secret van")
    ok(update_challan(client, challan, [(a, 2)]))
    ok(convert(client, challan["id"]))
    for _, _, props in events.captured:
        text = repr(props)
        for leak in ("Customer One", "Acme", "27AADCB2230M1ZT", "Widget", "Secret van"):
            assert leak not in text, (leak, props)
