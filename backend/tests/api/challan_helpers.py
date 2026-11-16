"""Shared setup for the delivery challan tests (#840)."""

from decimal import Decimal

from quotation_helpers import (  # noqa: F401 -- re-exported for the challan tests
    GST_KA,
    GST_MH,
    create_ledger,
    create_product,
    iso_today,
    ok,
    seed_company,
    seed_financial_year,
    series_counters,
)


def challan_payload(ledger_id: int, lines, **extra) -> dict:
    """``lines`` is a list of (product_id, quantity) or (product_id, quantity, unit_price)."""
    items = []
    for line in lines:
        product_id, quantity, *rest = line
        items.append({"product_id": product_id, "quantity": quantity, "unit_price": rest[0] if rest else 100})
    body = {"ledger_id": ledger_id, "items": items}
    body.update(extra)
    return body


def create_challan(client, ledger_id: int, lines, **extra) -> dict:
    return ok(client.post("/api/delivery-challans/", json=challan_payload(ledger_id, lines, **extra)))


def update_challan(client, challan: dict, lines, **extra):
    body = challan_payload(challan["ledger_id"], lines, **extra)
    return client.put(f"/api/delivery-challans/{challan['id']}", json=body)


def get_challan(client, challan_id: int) -> dict:
    return ok(client.get(f"/api/delivery-challans/{challan_id}"))


def draft(client, challan_id: int) -> dict:
    return ok(client.get(f"/api/delivery-challans/{challan_id}/conversion-draft"))


def convert(client, challan_id: int, *, quantities: dict | None = None, extra_lines=(), drop=(), **overrides):
    """Post the draft back, with invoice quantities changed per product, lines dropped or added."""
    payload = draft(client, challan_id)["invoice"]
    items = []
    for item in payload["items"]:
        if item["product_id"] in drop:
            continue
        if quantities and item["product_id"] in quantities:
            item["quantity"] = quantities[item["product_id"]]
        items.append(item)
    for product_id, quantity in extra_lines:
        items.append({"product_id": product_id, "quantity": quantity, "unit_price": 100})
    payload["items"] = items
    payload.update(overrides)
    return client.post(f"/api/delivery-challans/{challan_id}/convert", json=payload)


def stock(client, product_id: int) -> Decimal:
    """What the inventory page shows for this product."""
    rows = ok(client.get("/api/inventory/", params={"page_size": 500}))
    rows = rows["items"] if isinstance(rows, dict) else rows
    for row in rows:
        if row["product_id"] == product_id:
            return Decimal(str(row["quantity"]))
    raise AssertionError(f"no inventory row for product {product_id}")
