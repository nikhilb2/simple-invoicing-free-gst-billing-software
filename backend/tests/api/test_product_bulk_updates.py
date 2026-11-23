import csv
import io
from contextlib import contextmanager

import pytest

from app_main import app
from src.api.deps import get_current_user
from src.models.company import CompanyProfile
from src.models.product import Product
from src.models.product_bulk_update import ProductBulkUpdate
from src.models.user import User, UserRole


BASE = "/api/products/bulk-update"


def create_product(client, sku="BULK-1", name="Bulk test product"):
    response = client.post("/api/products/", json={
        "sku": sku, "name": name, "price": 100, "purchase_price": 70,
        "initial_quantity": 10, "gst_rate": 18, "hsn_sac": "01012100",
    })
    assert response.status_code == 200, response.text
    return response.json()["id"]


def preview(client, lines):
    response = client.post(f"{BASE}/preview", files={"file": ("changes.csv", lines, "text/csv")})
    assert response.status_code == 200, response.text
    return response.json()


def test_preview_zero_blank_inclusive_hsn_and_idempotent_save(client, db_session):
    product_id = create_product(client)
    exported = client.get(f"{BASE}/export")
    assert exported.status_code == 200
    rows = list(csv.DictReader(io.StringIO(exported.content.decode("utf-8-sig"))))
    assert rows[0]["Product ID"] == str(product_id)
    assert rows[0]["HSN/SAC"] == "HSN:01012100"
    assert rows[0]["Replacement Stock"] == ""

    data = preview(client,
        "Product ID,Product Name,Purchase Price,Purchase Price GST,Selling Price,"
        "Selling Price GST,HSN/SAC,Replacement Stock\n"
        f"{product_id},Name: BULK TEST PRODUCT,0,Exclusive,236,Inclusive,hsn:01012910,\n")
    assert data["errors"] == []
    assert data["changes"][0]["fields"] == {
        "purchase_price": {"old": "70.00", "new": "0.00"},
        "price": {"old": "100.00", "new": "200.00"},
        "hsn_sac": {"old": "01012100", "new": "01012910"},
    }

    movement = client.post("/api/inventory/adjust", json={"product_id": product_id, "quantity": 5})
    assert movement.status_code == 200, movement.text
    for _ in range(2):
        response = client.post(f"{BASE}/confirm", json={"token": data["token"]})
        assert response.status_code == 200, response.text
        assert response.json() == {"updated": 1}
    product = client.get("/api/products/with-inventory").json()["items"][0]
    assert (product["purchase_price"], product["selling_price"], product["hsn_sac"]) == (0, 200, "01012910")
    assert product["current_stock"] == 15
    assert db_session.query(ProductBulkUpdate).count() == 1


def test_stock_is_separate_and_stale_preview_cannot_update_any_product(client):
    first = create_product(client)
    second = create_product(client, "BULK-2", "Second")
    content = (
        "Product ID,Selling Price,Selling Price GST,Replacement Stock\n"
        f"{first},200,Exclusive,0\n{second},300,Exclusive,\n"
    )
    data = preview(client, content)
    assert data["errors"] == []
    confirmation = {"token": data["token"]}
    assert client.post(f"{BASE}/confirm", json=confirmation).status_code == 400
    assert client.post("/api/inventory/adjust", json={"product_id": first, "quantity": 1}).status_code == 200
    confirmation["confirm_stock"] = True
    assert client.post(f"{BASE}/confirm", json=confirmation).status_code == 409
    assert client.get(f"/api/products/{second}").json()["price"] == 100

    confirmation["token"] = preview(client, content)["token"]
    assert client.post(f"{BASE}/confirm", json=confirmation).status_code == 200
    products = {product["id"]: product for product in client.get("/api/products/with-inventory").json()["items"]}
    assert products[first]["current_stock"] == 0
    assert products[second]["current_stock"] == 10


def test_rejects_unknown_ambiguous_duplicate_and_invalid_rows(client):
    first = create_product(client)
    second = create_product(client, "BULK-2", "Same name")
    create_product(client, "BULK-3", "Same name")
    data = preview(client,
        "Product ID,Product Name,Purchase Price,Purchase Price GST\n"
        "999999,Bulk test product,1,Exclusive\n"
        ",Same name,1,Exclusive\n"
        ",Bulk test product,1,Exclusive\n"
        f"{first},,1,Exclusive\n{second},,-1,Exclusive\n")
    assert data["token"] is None
    assert [error["row"] for error in data["errors"]] == [2, 3, 5, 6]
    assert data["changes"][0]["id"] == first


@contextmanager
def as_role(role):
    previous = app.dependency_overrides.get(get_current_user)
    app.dependency_overrides[get_current_user] = lambda: User(id=1, email="test@example.com", role=role)
    try:
        yield
    finally:
        app.dependency_overrides[get_current_user] = previous


def other_company(db_session) -> int:
    company = CompanyProfile(
        name="Second Shop", address="Pune", gst="27ZZZZZ1234F1ZH",
        phone_number="8888888888", currency_code="INR",
    )
    db_session.add(company)
    db_session.commit()
    return company.id


def first_error(client, content):
    data = preview(client, content)
    assert data["token"] is None
    return data["errors"][0]["message"]


def test_product_id_from_another_company_is_unknown(client, db_session):
    create_product(client)  # creates the default company, so the second one is not the fallback
    other = other_company(db_session)
    foreign = create_product_in(client, other)
    assert first_error(
        client, f"Product ID,Selling Price,Selling Price GST\n{foreign},200,Exclusive\n"
    ) == "Unknown product ID"


def create_product_in(client, company_id, sku="OTHER-1", name="Other product"):
    response = client.post("/api/products/", headers={"X-Company-Id": str(company_id)}, json={
        "sku": sku, "name": name, "price": 100, "purchase_price": 70,
        "initial_quantity": 10, "gst_rate": 18,
    })
    assert response.status_code == 200, response.text
    return response.json()["id"]


def test_preview_from_one_company_cannot_be_confirmed_in_another(client, db_session):
    product_id = create_product(client)
    other = other_company(db_session)
    data = preview(client, f"Product ID,Selling Price,Selling Price GST\n{product_id},200,Exclusive\n")
    response = client.post(
        f"{BASE}/confirm", json={"token": data["token"]}, headers={"X-Company-Id": str(other)},
    )
    assert response.status_code == 403, response.text
    assert db_session.query(ProductBulkUpdate).count() == 0
    assert client.get(f"/api/products/{product_id}").json()["price"] == 100


def test_staff_cannot_export_preview_or_confirm(client):
    product_id = create_product(client)
    data = preview(client, f"Product ID,Selling Price,Selling Price GST\n{product_id},200,Exclusive\n")
    with as_role(UserRole.staff):
        assert client.get(f"{BASE}/export").status_code == 403
        files = {"file": ("changes.csv", "Product ID,Selling Price,Selling Price GST\n", "text/csv")}
        assert client.post(f"{BASE}/preview", files=files).status_code == 403
        assert client.post(f"{BASE}/confirm", json={"token": data["token"]}).status_code == 403
    assert client.get(f"/api/products/{product_id}").json()["price"] == 100


@pytest.mark.parametrize("flags", [{"track_serials": True}, {"maintain_inventory": False}])
def test_stock_replacement_refused_without_plain_inventory(client, db_session, flags):
    product_id = create_product(client)
    db_session.query(Product).filter(Product.id == product_id).update(flags)
    db_session.commit()
    assert first_error(
        client, f"Product ID,Replacement Stock\n{product_id},5\n"
    ) == "Stock replacement requires inventory tracking without serial numbers"


def test_fractional_stock_refused_for_whole_number_product(client):
    product_id = create_product(client)
    assert first_error(
        client, f"Product ID,Replacement Stock\n{product_id},2.5\n"
    ) == "Stock must be a whole number for this product"


def test_gst_inclusive_price_that_does_not_divide_evenly_is_rounded(client):
    product_id = create_product(client)
    data = preview(client, f"Product ID,Selling Price,Selling Price GST\n{product_id},100,Inclusive\n")
    assert data["changes"][0]["fields"]["price"] == {"old": "100.00", "new": "84.75"}
    assert client.post(f"{BASE}/confirm", json={"token": data["token"]}).status_code == 200
    assert client.get(f"/api/products/{product_id}").json()["price"] == 84.75


def test_name_matching_ignores_case_and_prefix(client):
    product_id = create_product(client)
    for cell in ("Name: bulk TEST product", "BULK test PRODUCT", "name:Bulk test product"):
        data = preview(client, f"Product Name,Selling Price,Selling Price GST\n{cell},200,Exclusive\n")
        assert data["errors"] == []
        assert data["changes"][0]["id"] == product_id


def test_name_that_disagrees_with_product_id_is_rejected(client):
    first = create_product(client)
    create_product(client, "BULK-2", "Second")
    assert first_error(
        client,
        "Product ID,Product Name,Selling Price,Selling Price GST\n"
        f"{first},Name: Second,200,Exclusive\n",
    ) == "Product name does not match the product ID"


def test_confirm_tracks_counts_only(client, monkeypatch):
    from src.api.routes import product_bulk_updates

    sent = []
    monkeypatch.setattr(product_bulk_updates, "track", lambda *args: sent.append(args))
    first = create_product(client)
    second = create_product(client, "BULK-2", "Second")
    data = preview(
        client,
        "Product ID,Selling Price,Selling Price GST,Replacement Stock\n"
        f"{first},200,Exclusive,3\n{second},300,Exclusive,\n",
    )
    response = client.post(f"{BASE}/confirm", json={"token": data["token"], "confirm_stock": True})
    assert response.status_code == 200, response.text
    assert [(event, props) for event, _, props in sent] == [
        ("products_bulk_updated", {"product_count": 2, "stock_count": 1})
    ]
