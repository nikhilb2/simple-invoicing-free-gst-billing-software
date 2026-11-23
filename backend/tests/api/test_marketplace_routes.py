"""HTTP-layer tests: company scoping, RBAC, and the proxied connection flow.

Nothing here should reach the network — the browser never talks to the central
server directly, and neither do these tests: every outbound call goes through the
in-memory fake via the client transport override.
"""

from contextlib import contextmanager
from datetime import date, datetime
from decimal import Decimal

import pytest

from app_main import app
from src.api.deps import get_current_user
from src.models.company import CompanyProfile
from src.models.financial_year import FinancialYear
from src.models.inventory import Inventory
from src.models.marketplace import (
    MarketplaceConnection,
    MarketplaceListing,
    MarketplaceOrder,
    MarketplaceOrderItem,
)
from src.models.product import Product
from src.models.user import User, UserRole
from src.core.config import settings
from src.services.marketplace import client as client_module
from tests.fakes.fake_marketplace import FakeMarketplace

GST_A = "27AABCU9603R1ZN"
GST_B = "29ABCDE1234F1ZW"


@pytest.fixture
def fake():
    marketplace = FakeMarketplace()
    client_module.set_transport_override(marketplace.transport())
    yield marketplace
    client_module.set_transport_override(None)


@contextmanager
def as_role(role: UserRole):
    """Swap the conftest admin override for another role."""
    previous = app.dependency_overrides.get(get_current_user)
    app.dependency_overrides[get_current_user] = lambda: User(
        id=1, email="test@example.com", role=role
    )
    try:
        yield
    finally:
        app.dependency_overrides[get_current_user] = previous


def make_company(db, *, name, gst) -> CompanyProfile:
    company = CompanyProfile(
        name=name, address=f"{name} HQ", gst=gst, phone_number="9999999999", currency_code="INR"
    )
    db.add(company)
    db.flush()
    db.add(
        FinancialYear(
            company_id=company.id,
            label="2026-27",
            start_date=date(2026, 4, 1),
            end_date=date(2027, 3, 31),
            is_active=True,
        )
    )
    db.commit()
    return company


def make_product(db, company_id, sku="P1", qty=100) -> Product:
    product = Product(
        company_id=company_id,
        sku=sku,
        name=f"Product {sku}",
        price=Decimal("125.00"),
        purchase_price=Decimal("125.00"),
        gst_rate=18,
        hsn_sac="8482",
        unit="Pieces",
        maintain_inventory=True,
    )
    db.add(product)
    db.flush()
    db.add(Inventory(company_id=company_id, product_id=product.id, quantity=qty))
    db.commit()
    return product


def make_connection(db, company_id, *, credential="mk_live_seeded", **kwargs):
    connection = MarketplaceConnection(
        company_id=company_id,
        base_url="http://marketplace.test",
        remote_seller_id=kwargs.pop("remote_seller_id", "sel_seeded"),
        status="connected",
        **kwargs,
    )
    connection.credential = credential
    db.add(connection)
    db.commit()
    return connection


def headers_for(company: CompanyProfile) -> dict:
    return {"X-Company-Id": str(company.id)}


# ---------------------------------------------------------------------------
# Connection
# ---------------------------------------------------------------------------

class TestConnectionRoutes:
    def test_no_connection_returns_null(self, client, db_session, fake):
        company = make_company(db_session, name="Acme", gst=GST_A)
        response = client.get("/api/marketplace/connection", headers=headers_for(company))
        assert response.status_code == 200
        assert response.json() is None

    def test_meta_probes_the_pasted_url(self, client, db_session, fake):
        make_company(db_session, name="Acme", gst=GST_A)
        response = client.get(
            "/api/marketplace/connection/meta", params={"base_url": "http://marketplace.test"}
        )
        assert response.status_code == 200
        assert response.json()["marketplace_name"] == "Fake Marketplace"

    def test_register_stores_the_credential_encrypted_and_never_returns_it(
        self, client, db_session, fake
    ):
        company = make_company(db_session, name="Acme", gst=GST_A)

        response = client.post(
            "/api/marketplace/connection",
            json={"base_url": "http://marketplace.test", "legal_name": "Acme Traders"},
            headers=headers_for(company),
        )

        assert response.status_code == 201
        body = response.json()
        assert body["status"] == "pending_approval"
        assert body["gstin"] == GST_A
        assert body["remote_seller_id"]
        assert "credential" not in body
        assert "api_key" not in body

        connection = (
            db_session.query(MarketplaceConnection)
            .filter(MarketplaceConnection.company_id == company.id)
            .one()
        )
        assert connection._credential is not None
        # Opaque at rest, decryptable through the property.
        assert "mk_live_" not in connection._credential
        assert connection.credential.startswith("mk_live_")
        assert connection.credential_prefix.startswith("mk_live_")

    def test_registering_twice_conflicts(self, client, db_session, fake):
        company = make_company(db_session, name="Acme", gst=GST_A)
        payload = {"base_url": "http://marketplace.test"}
        client.post("/api/marketplace/connection", json=payload, headers=headers_for(company))
        second = client.post(
            "/api/marketplace/connection", json=payload, headers=headers_for(company)
        )
        assert second.status_code == 409

    def test_registering_without_a_valid_company_gstin_is_rejected(
        self, client, db_session, fake
    ):
        company = make_company(db_session, name="Acme", gst="")
        response = client.post(
            "/api/marketplace/connection",
            json={"base_url": "http://marketplace.test"},
            headers=headers_for(company),
        )
        assert response.status_code == 400
        assert fake.sellers == {}

    def test_a_claimed_gstin_surfaces_the_conflict(self, client, db_session, fake):
        first = make_company(db_session, name="Acme", gst=GST_A)
        client.post(
            "/api/marketplace/connection",
            json={"base_url": "http://marketplace.test"},
            headers=headers_for(first),
        )
        second = make_company(db_session, name="Impostor", gst=GST_A)

        response = client.post(
            "/api/marketplace/connection",
            json={"base_url": "http://marketplace.test"},
            headers=headers_for(second),
        )
        assert response.status_code == 409

    def test_patch_updates_the_automation_toggles(self, client, db_session, fake):
        company = make_company(db_session, name="Acme", gst=GST_A)
        make_connection(db_session, company.id)

        response = client.patch(
            "/api/marketplace/connection",
            json={"auto_accept": False, "auto_post": True, "auto_accept_max_amount": 5000},
            headers=headers_for(company),
        )

        assert response.status_code == 200
        body = response.json()
        assert body["auto_accept"] is False
        assert body["auto_post"] is True
        assert body["auto_accept_max_amount"] == "5000.00"

    def test_defaults_are_auto_accept_on_and_auto_post_off(self, client, db_session, fake):
        """Phase 3 posture: orders land in the Orders page and a human posts them."""
        company = make_company(db_session, name="Acme", gst=GST_A)
        client.post(
            "/api/marketplace/connection",
            json={"base_url": "http://marketplace.test"},
            headers=headers_for(company),
        )
        body = client.get(
            "/api/marketplace/connection", headers=headers_for(company)
        ).json()
        assert body["auto_accept"] is True
        assert body["auto_post"] is False

    def test_rotate_key_replaces_the_stored_credential(self, client, db_session, fake):
        company = make_company(db_session, name="Acme", gst=GST_A)
        client.post(
            "/api/marketplace/connection",
            json={"base_url": "http://marketplace.test"},
            headers=headers_for(company),
        )
        connection = (
            db_session.query(MarketplaceConnection)
            .filter(MarketplaceConnection.company_id == company.id)
            .one()
        )
        original = connection.credential

        response = client.post(
            "/api/marketplace/connection/rotate-key", headers=headers_for(company)
        )

        assert response.status_code == 200
        db_session.refresh(connection)
        assert connection.credential != original
        assert connection.credential.startswith("mk_live_")

    def test_delete_disconnects_locally_and_clears_the_credential(
        self, client, db_session, fake
    ):
        company = make_company(db_session, name="Acme", gst=GST_A)
        client.post(
            "/api/marketplace/connection",
            json={"base_url": "http://marketplace.test"},
            headers=headers_for(company),
        )

        assert (
            client.delete("/api/marketplace/connection", headers=headers_for(company)).status_code
            == 200
        )

        connection = (
            db_session.query(MarketplaceConnection)
            .filter(MarketplaceConnection.company_id == company.id)
            .one()
        )
        db_session.refresh(connection)
        assert connection.status == "disconnected"
        assert connection.credential is None

    def test_routes_404_without_a_connection(self, client, db_session, fake):
        company = make_company(db_session, name="Acme", gst=GST_A)
        for method, path in [
            ("post", "/api/marketplace/sync"),
            ("patch", "/api/marketplace/connection"),
        ]:
            call = getattr(client, method)
            kwargs = {"headers": headers_for(company)}
            if method in ("post", "patch"):
                kwargs["json"] = {}
            assert call(path, **kwargs).status_code == 404


# ---------------------------------------------------------------------------
# Default marketplace: read-only browse before registering
# ---------------------------------------------------------------------------

class TestDefaultMarketplace:
    def _seed_listing(self, client, db_session):
        seller = make_company(db_session, name="SellerCo", gst=GST_B)
        client.post(
            "/api/marketplace/connection",
            json={"base_url": "http://marketplace.test"},
            headers=headers_for(seller),
        )
        product = make_product(db_session, seller.id)
        client.post(
            "/api/marketplace/listings",
            json={"product_id": product.id, "asking_price": 125.0},
            headers=headers_for(seller),
        )

    def test_defaults_report_the_configured_url(self, client, monkeypatch):
        monkeypatch.setattr(settings, "MARKETPLACE_DEFAULT_URL", "https://marketplace.respawn.in")
        assert client.get("/api/marketplace/defaults").json() == {
            "base_url": "https://marketplace.respawn.in"
        }
        monkeypatch.setattr(settings, "MARKETPLACE_DEFAULT_URL", "")
        assert client.get("/api/marketplace/defaults").json() == {"base_url": None}

    def test_an_unregistered_company_browses_anonymously(
        self, client, db_session, fake, monkeypatch
    ):
        monkeypatch.setattr(settings, "MARKETPLACE_DEFAULT_URL", "https://marketplace.respawn.in")
        self._seed_listing(client, db_session)
        guest = make_company(db_session, name="GuestCo", gst=GST_A)

        response = client.get("/api/marketplace/catalog", headers=headers_for(guest))
        assert response.status_code == 200, response.text
        items = response.json()["items"]
        assert len(items) == 1
        assert fake.anonymous_browses == 1

        detail = client.get(
            f"/api/marketplace/catalog/{items[0]['listing_id']}", headers=headers_for(guest)
        )
        assert detail.status_code == 200, detail.text

    def test_an_unregistered_company_cannot_buy_or_sell(
        self, client, db_session, fake, monkeypatch
    ):
        monkeypatch.setattr(settings, "MARKETPLACE_DEFAULT_URL", "https://marketplace.respawn.in")
        self._seed_listing(client, db_session)
        guest = make_company(db_session, name="GuestCo", gst=GST_A)
        product = make_product(db_session, guest.id, sku="G1")
        listing_id = next(iter(fake.listings))

        assert client.post(
            "/api/marketplace/orders",
            json={"listing_id": listing_id, "quantity": 1},
            headers=headers_for(guest),
        ).status_code == 404
        assert client.post(
            "/api/marketplace/listings",
            json={"product_id": product.id, "asking_price": 10.0},
            headers=headers_for(guest),
        ).status_code == 404

    def test_a_pending_company_browses_anonymously(self, client, db_session, monkeypatch):
        """The key is refused while pending, so Browse falls back to anonymous."""
        pending_fake = FakeMarketplace(auto_approve=False)
        client_module.set_transport_override(pending_fake.transport())
        try:
            company = make_company(db_session, name="PendingCo", gst=GST_A)
            registered = client.post(
                "/api/marketplace/connection",
                json={"base_url": "http://marketplace.test"},
                headers=headers_for(company),
            )
            assert registered.json()["status"] == "pending_approval"

            response = client.get("/api/marketplace/catalog", headers=headers_for(company))
            assert response.status_code == 200, response.text
            assert pending_fake.anonymous_browses == 1
        finally:
            client_module.set_transport_override(None)

    def test_a_marketplace_without_public_browse_is_a_403_not_a_401(
        self, client, db_session, fake, monkeypatch
    ):
        """A 401 here would make the browser think its own session expired."""
        monkeypatch.setattr(settings, "MARKETPLACE_DEFAULT_URL", "https://marketplace.respawn.in")
        fake.public_browse = False
        guest = make_company(db_session, name="GuestCo", gst=GST_A)
        response = client.get("/api/marketplace/catalog", headers=headers_for(guest))
        assert response.status_code == 403

    def test_no_default_and_no_connection_404s(self, client, db_session, fake, monkeypatch):
        monkeypatch.setattr(settings, "MARKETPLACE_DEFAULT_URL", "")
        company = make_company(db_session, name="Acme", gst=GST_A)
        response = client.get("/api/marketplace/catalog", headers=headers_for(company))
        assert response.status_code == 404


# ---------------------------------------------------------------------------
# Listings and browse
# ---------------------------------------------------------------------------

class TestListingRoutes:
    def _connected(self, client, db_session, name, gst):
        company = make_company(db_session, name=name, gst=gst)
        client.post(
            "/api/marketplace/connection",
            json={"base_url": "http://marketplace.test"},
            headers=headers_for(company),
        )
        return company

    def test_publish_then_list_then_withdraw(self, client, db_session, fake):
        company = self._connected(client, db_session, "Acme", GST_A)
        product = make_product(db_session, company.id)

        created = client.post(
            "/api/marketplace/listings",
            json={"product_id": product.id, "asking_price": 125.0},
            headers=headers_for(company),
        )
        assert created.status_code == 201
        body = created.json()
        assert body["remote_listing_id"].startswith("lst_")
        assert body["status"] == "active"
        # Seller's own rate and HSN — they are what the buyer will book.
        assert body["gst_rate"] == "18.00"
        assert body["hsn_sac"] == "8482"

        listed = client.get("/api/marketplace/listings", headers=headers_for(company)).json()
        assert len(listed) == 1

        patched = client.patch(
            f"/api/marketplace/listings/{body['id']}",
            json={"asking_price": 130.0, "status": "paused"},
            headers=headers_for(company),
        )
        assert patched.json()["asking_price"] == "130.00"
        assert fake.listings[body["remote_listing_id"]]["asking_price"] == "130.0"

        assert (
            client.delete(
                f"/api/marketplace/listings/{body['id']}", headers=headers_for(company)
            ).status_code
            == 200
        )
        assert fake.listings[body["remote_listing_id"]]["status"] == "withdrawn"

    def test_listing_the_same_product_twice_conflicts(self, client, db_session, fake):
        company = self._connected(client, db_session, "Acme", GST_A)
        product = make_product(db_session, company.id)
        payload = {"product_id": product.id, "asking_price": 125.0}
        client.post("/api/marketplace/listings", json=payload, headers=headers_for(company))
        second = client.post(
            "/api/marketplace/listings", json=payload, headers=headers_for(company)
        )
        assert second.status_code == 409

    def test_listing_another_companys_product_is_a_404(self, client, db_session, fake):
        company = self._connected(client, db_session, "Acme", GST_A)
        other = make_company(db_session, name="Other", gst=GST_B)
        foreign = make_product(db_session, other.id, sku="FOREIGN")

        response = client.post(
            "/api/marketplace/listings",
            json={"product_id": foreign.id, "asking_price": 10.0},
            headers=headers_for(company),
        )
        assert response.status_code == 404

    def test_browse_excludes_your_own_listings(self, client, db_session, fake):
        seller = self._connected(client, db_session, "SellerCo", GST_A)
        buyer = self._connected(client, db_session, "BuyerCo", GST_B)
        product = make_product(db_session, seller.id)
        client.post(
            "/api/marketplace/listings",
            json={"product_id": product.id, "asking_price": 125.0},
            headers=headers_for(seller),
        )

        own = client.get("/api/marketplace/catalog", headers=headers_for(seller)).json()
        theirs = client.get("/api/marketplace/catalog", headers=headers_for(buyer)).json()

        assert own["items"] == []
        assert len(theirs["items"]) == 1
        assert theirs["items"][0]["seller"]["gstin"] == GST_A
        # v1 never verifies GSTIN ownership — the UI must badge this.
        assert theirs["items"][0]["seller"]["verified"] is False


# ---------------------------------------------------------------------------
# Orders
# ---------------------------------------------------------------------------

class TestOrderRoutes:
    def _market(self, client, db_session):
        seller = make_company(db_session, name="SellerCo", gst=GST_A)
        buyer = make_company(db_session, name="BuyerCo", gst=GST_B)
        for company in (seller, buyer):
            client.post(
                "/api/marketplace/connection",
                json={"base_url": "http://marketplace.test"},
                headers=headers_for(company),
            )
        product = make_product(db_session, seller.id)
        listing = client.post(
            "/api/marketplace/listings",
            json={"product_id": product.id, "asking_price": 125.0},
            headers=headers_for(seller),
        ).json()
        return seller, buyer, product, listing

    def test_buy_now_mirrors_the_order_locally(self, client, db_session, fake):
        _seller, buyer, _product, listing = self._market(client, db_session)

        response = client.post(
            "/api/marketplace/orders",
            json={"listing_id": listing["remote_listing_id"], "quantity": 10},
            headers=headers_for(buyer),
        )

        assert response.status_code == 201
        body = response.json()
        assert body["side"] == "buy"
        assert body["state"] == "pending"
        assert body["counterparty_gstin"] == GST_A
        assert body["remote_total_amount"] == "1250.00"
        assert len(body["items"]) == 1
        assert body["items"][0]["gst_rate"] == "18.00"
        # Nothing is posted off a pending order.
        assert body["posting_state"] == "not_required"

    def test_cancel_is_buyer_only_and_accept_is_seller_only(self, client, db_session, fake):
        seller, buyer, _product, listing = self._market(client, db_session)
        order = client.post(
            "/api/marketplace/orders",
            json={"listing_id": listing["remote_listing_id"], "quantity": 10},
            headers=headers_for(buyer),
        ).json()

        # A buy-side order cannot be accepted.
        assert (
            client.post(
                f"/api/marketplace/orders/{order['id']}/accept", headers=headers_for(buyer)
            ).status_code
            == 409
        )
        cancelled = client.post(
            f"/api/marketplace/orders/{order['id']}/cancel", headers=headers_for(buyer)
        )
        assert cancelled.status_code == 200
        assert cancelled.json()["state"] == "cancelled"

    def test_accept_refuses_when_local_stock_cannot_cover_it(self, client, db_session, fake):
        seller, buyer, product, listing = self._market(client, db_session)
        client.post(
            "/api/marketplace/orders",
            json={"listing_id": listing["remote_listing_id"], "quantity": 10},
            headers=headers_for(buyer),
        )
        # A walk-in sale eats the stock between placement and accept.
        db_session.query(Inventory).filter(Inventory.product_id == product.id).update(
            {"quantity": 1}
        )
        db_session.commit()

        seller_order = _seed_seller_order(db_session, seller.id, listing)
        response = client.post(
            f"/api/marketplace/orders/{seller_order.id}/accept", headers=headers_for(seller)
        )

        assert response.status_code == 400
        assert "Insufficient stock" in response.json()["detail"]

    def test_link_product_remaps_future_orders_only(self, client, db_session, fake):
        seller, buyer, _product, listing = self._market(client, db_session)
        order = client.post(
            "/api/marketplace/orders",
            json={"listing_id": listing["remote_listing_id"], "quantity": 10},
            headers=headers_for(buyer),
        ).json()
        local = make_product(db_session, buyer.id, sku="LOCAL")

        response = client.post(
            f"/api/marketplace/orders/{order['id']}/link-product",
            json={
                "remote_listing_id": listing["remote_listing_id"],
                "product_id": local.id,
            },
            headers=headers_for(buyer),
        )

        assert response.status_code == 200
        assert response.json()["items"][0]["product_id"] == local.id

    def test_retry_posting_refuses_an_already_posted_order(self, client, db_session, fake):
        seller, buyer, _product, listing = self._market(client, db_session)
        order = client.post(
            "/api/marketplace/orders",
            json={"listing_id": listing["remote_listing_id"], "quantity": 10},
            headers=headers_for(buyer),
        ).json()
        db_session.query(MarketplaceOrder).filter(MarketplaceOrder.id == order["id"]).update(
            {"posting_state": "posted", "posted_invoice_id": 12345}
        )
        db_session.commit()

        response = client.post(
            f"/api/marketplace/orders/{order['id']}/retry-posting", headers=headers_for(buyer)
        )
        assert response.status_code == 409


def _seed_seller_order(db, company_id, listing) -> MarketplaceOrder:
    """The seller-side mirror an order.created event would have produced."""
    order = MarketplaceOrder(
        company_id=company_id,
        side="sell",
        remote_order_id="ord_seeded",
        state="pending",
        remote_listing_id=listing["remote_listing_id"],
        counterparty_remote_id="sel_buyer",
        counterparty_gstin=GST_B,
        order_placed_at=datetime(2026, 8, 22),
        posting_state="not_required",
    )
    db.add(order)
    db.flush()
    db.add(
        MarketplaceOrderItem(
            order_id=order.id,
            line_no=1,
            remote_listing_id=listing["remote_listing_id"],
            title="Bearing",
            quantity=Decimal("10"),
            unit="Pieces",
            unit_price=Decimal("125.00"),
            gst_rate=Decimal("18.00"),
            hsn_sac="8482",
        )
    )
    db.commit()
    return order


# ---------------------------------------------------------------------------
# Company scoping
# ---------------------------------------------------------------------------

class TestCompanyScoping:
    def test_two_companies_never_see_each_others_marketplace_rows(
        self, client, db_session, fake
    ):
        first = make_company(db_session, name="First", gst=GST_A)
        second = make_company(db_session, name="Second", gst=GST_B)
        make_connection(db_session, first.id, remote_seller_id="sel_first")
        make_connection(db_session, second.id, remote_seller_id="sel_second")

        product_a = make_product(db_session, first.id, sku="A1")
        product_b = make_product(db_session, second.id, sku="B1")
        for company, product in ((first, product_a), (second, product_b)):
            db_session.add(
                MarketplaceListing(
                    company_id=company.id,
                    product_id=product.id,
                    remote_listing_id=f"lst_{company.id}",
                    title=f"Listing {company.id}",
                    asking_price=Decimal("100.00"),
                    status="active",
                )
            )
            db_session.add(
                MarketplaceOrder(
                    company_id=company.id,
                    side="sell",
                    remote_order_id=f"ord_{company.id}",
                    state="pending",
                    posting_state="not_required",
                )
            )
        db_session.commit()

        first_listings = client.get(
            "/api/marketplace/listings", headers=headers_for(first)
        ).json()
        second_listings = client.get(
            "/api/marketplace/listings", headers=headers_for(second)
        ).json()
        first_orders = client.get("/api/marketplace/orders", headers=headers_for(first)).json()
        second_orders = client.get(
            "/api/marketplace/orders", headers=headers_for(second)
        ).json()

        assert [l["remote_listing_id"] for l in first_listings] == [f"lst_{first.id}"]
        assert [l["remote_listing_id"] for l in second_listings] == [f"lst_{second.id}"]
        assert [o["remote_order_id"] for o in first_orders["items"]] == [f"ord_{first.id}"]
        assert [o["remote_order_id"] for o in second_orders["items"]] == [f"ord_{second.id}"]

    def test_each_company_reads_only_its_own_connection(self, client, db_session, fake):
        first = make_company(db_session, name="First", gst=GST_A)
        second = make_company(db_session, name="Second", gst=GST_B)
        make_connection(db_session, first.id, remote_seller_id="sel_first")

        assert (
            client.get("/api/marketplace/connection", headers=headers_for(first)).json()[
                "remote_seller_id"
            ]
            == "sel_first"
        )
        assert client.get("/api/marketplace/connection", headers=headers_for(second)).json() is None

    def test_fetching_another_companys_order_by_id_is_a_404(self, client, db_session, fake):
        first = make_company(db_session, name="First", gst=GST_A)
        second = make_company(db_session, name="Second", gst=GST_B)
        make_connection(db_session, first.id)
        order = MarketplaceOrder(
            company_id=first.id,
            side="sell",
            remote_order_id="ord_private",
            state="pending",
            posting_state="not_required",
        )
        db_session.add(order)
        db_session.commit()

        assert (
            client.get(
                f"/api/marketplace/orders/{order.id}", headers=headers_for(first)
            ).status_code
            == 200
        )
        assert (
            client.get(
                f"/api/marketplace/orders/{order.id}", headers=headers_for(second)
            ).status_code
            == 404
        )


# ---------------------------------------------------------------------------
# RBAC
# ---------------------------------------------------------------------------

class TestRbac:
    @pytest.fixture
    def company(self, client, db_session, fake):
        company = make_company(db_session, name="Acme", gst=GST_A)
        # Registered for real, so a manager's publish actually reaches the fake
        # instead of failing auth before RBAC has been proven.
        client.post(
            "/api/marketplace/connection",
            json={"base_url": "http://marketplace.test"},
            headers=headers_for(company),
        )
        make_product(db_session, company.id)
        return company

    @pytest.mark.parametrize("role", [UserRole.admin, UserRole.manager, UserRole.staff])
    def test_every_role_can_read(self, client, company, role):
        with as_role(role):
            for path in ("/api/marketplace/connection", "/api/marketplace/listings", "/api/marketplace/orders"):
                assert client.get(path, headers=headers_for(company)).status_code == 200

    def test_staff_cannot_mutate_listings_or_orders(self, client, company, db_session):
        with as_role(UserRole.staff):
            assert (
                client.post(
                    "/api/marketplace/listings",
                    json={"product_id": 1, "asking_price": 1.0},
                    headers=headers_for(company),
                ).status_code
                == 403
            )
            assert (
                client.post(
                    "/api/marketplace/orders",
                    json={"listing_id": "lst_1", "quantity": 1},
                    headers=headers_for(company),
                ).status_code
                == 403
            )

    def test_manager_can_mutate_listings_but_not_the_connection(
        self, client, company, db_session
    ):
        product = (
            db_session.query(Product).filter(Product.company_id == company.id).first()
        )
        with as_role(UserRole.manager):
            assert (
                client.post(
                    "/api/marketplace/listings",
                    json={"product_id": product.id, "asking_price": 125.0},
                    headers=headers_for(company),
                ).status_code
                == 201
            )
            # Connection management is admin-only.
            assert (
                client.patch(
                    "/api/marketplace/connection",
                    json={"auto_post": True},
                    headers=headers_for(company),
                ).status_code
                == 403
            )
            assert (
                client.delete(
                    "/api/marketplace/connection", headers=headers_for(company)
                ).status_code
                == 403
            )

    def test_only_admins_can_register_or_rotate(self, client, db_session, fake):
        company = make_company(db_session, name="Fresh", gst=GST_B)
        for role in (UserRole.manager, UserRole.staff):
            with as_role(role):
                assert (
                    client.post(
                        "/api/marketplace/connection",
                        json={"base_url": "http://marketplace.test"},
                        headers=headers_for(company),
                    ).status_code
                    == 403
                )
                assert (
                    client.post(
                        "/api/marketplace/connection/rotate-key", headers=headers_for(company)
                    ).status_code
                    == 403
                )


# ---------------------------------------------------------------------------
# Sync endpoints
# ---------------------------------------------------------------------------

class TestSyncRoutes:
    def test_sync_returns_a_result_envelope(self, client, db_session, fake):
        company = make_company(db_session, name="Acme", gst=GST_A)
        client.post(
            "/api/marketplace/connection",
            json={"base_url": "http://marketplace.test"},
            headers=headers_for(company),
        )

        response = client.post("/api/marketplace/sync", headers=headers_for(company))

        assert response.status_code == 200
        body = response.json()
        assert body["ran"] is True
        assert body["locked"] is False
        assert body["error"] is None
        # The approval event arrived on the first drain.
        assert body["events_applied"] >= 1

    def test_sync_all_covers_every_connection(self, client, db_session, fake):
        first = make_company(db_session, name="First", gst=GST_A)
        second = make_company(db_session, name="Second", gst=GST_B)
        for company in (first, second):
            client.post(
                "/api/marketplace/connection",
                json={"base_url": "http://marketplace.test"},
                headers=headers_for(company),
            )

        response = client.post("/api/marketplace/sync-all")

        assert response.status_code == 200
        results = response.json()["results"]
        assert {r["company_id"] for r in results} == {first.id, second.id}

    def test_sync_is_available_to_every_role(self, client, db_session, fake):
        """The frontend poll fires for whoever has the tab open."""
        company = make_company(db_session, name="Acme", gst=GST_A)
        make_connection(db_session, company.id)
        with as_role(UserRole.staff):
            assert (
                client.post("/api/marketplace/sync", headers=headers_for(company)).status_code
                == 200
            )


# ---------------------------------------------------------------------------
# GST resync: a product tax edit must reach its open listings (#888)
# ---------------------------------------------------------------------------


class TestMarketplaceGstResync:
    def _listed_product(self, client, db_session, fake):
        """A connected company with a product published at 18% GST."""
        company = make_company(db_session, name="Acme", gst=GST_A)
        client.post(
            "/api/marketplace/connection",
            json={"base_url": "http://marketplace.test"},
            headers=headers_for(company),
        )
        product = make_product(db_session, company.id)
        created = client.post(
            "/api/marketplace/listings",
            json={"product_id": product.id, "asking_price": 125.0},
            headers=headers_for(company),
        )
        assert created.status_code == 201
        assert created.json()["gst_rate"] == "18.00"
        return company, product, created.json()

    def _read_listing(self, client, company, listing_id):
        listed = client.get(
            "/api/marketplace/listings", headers=headers_for(company)
        ).json()
        return next(item for item in listed if item["id"] == listing_id)

    def test_product_gst_edit_resyncs_the_open_listing(self, client, db_session, fake):
        company, product, listing = self._listed_product(client, db_session, fake)

        updated = client.put(
            f"/api/products/{product.id}",
            json={
                "sku": "P1",
                "name": "Product P1",
                "price": 125.0,
                "gst_rate": 12,
                "hsn_sac": "8483",
                "unit": "Numbers",
            },
            headers=headers_for(company),
        )
        assert updated.status_code == 200

        synced = self._read_listing(client, company, listing["id"])
        assert synced["gst_rate"] == "12.00"
        assert synced["hsn_sac"] == "8483"
        assert synced["unit"] == "Numbers"
        # The remote marketplace must quote the new rate too, not just our row.
        assert Decimal(
            fake.listings[listing["remote_listing_id"]]["gst_rate"]
        ) == Decimal("12")

    def test_with_inventory_gst_edit_resyncs_the_open_listing(
        self, client, db_session, fake
    ):
        company, product, listing = self._listed_product(client, db_session, fake)

        updated = client.put(
            f"/api/products/{product.id}/with-inventory",
            json={"gst_rate": 12, "hsn_sac": "8483", "unit": "Numbers"},
            headers=headers_for(company),
        )
        assert updated.status_code == 200

        synced = self._read_listing(client, company, listing["id"])
        assert synced["gst_rate"] == "12.00"
        assert synced["hsn_sac"] == "8483"
        assert synced["unit"] == "Numbers"

    def test_withdrawn_listing_is_left_alone(self, client, db_session, fake):
        company, product, listing = self._listed_product(client, db_session, fake)
        assert (
            client.delete(
                f"/api/marketplace/listings/{listing['id']}",
                headers=headers_for(company),
            ).status_code
            == 200
        )

        updated = client.put(
            f"/api/products/{product.id}",
            json={
                "sku": "P1",
                "name": "Product P1",
                "price": 125.0,
                "gst_rate": 12,
                "hsn_sac": "8483",
                "unit": "Numbers",
            },
            headers=headers_for(company),
        )
        assert updated.status_code == 200

        left = self._read_listing(client, company, listing["id"])
        assert left["status"] == "withdrawn"
        assert left["gst_rate"] == "18.00"
        assert left["hsn_sac"] == "8482"

    def test_remote_failure_does_not_break_the_product_edit(
        self, client, db_session, fake
    ):
        company, product, listing = self._listed_product(client, db_session, fake)
        # The remote listing is gone, so the push PATCH 404s.
        del fake.listings[listing["remote_listing_id"]]

        updated = client.put(
            f"/api/products/{product.id}",
            json={
                "sku": "P1",
                "name": "Product P1",
                "price": 125.0,
                "gst_rate": 12,
                "hsn_sac": "8483",
                "unit": "Numbers",
            },
            headers=headers_for(company),
        )
        assert updated.status_code == 200

        db_session.expire_all()
        stored_product = (
            db_session.query(Product).filter(Product.id == product.id).first()
        )
        assert Decimal(str(stored_product.gst_rate)) == Decimal("12")
        stored_listing = (
            db_session.query(MarketplaceListing)
            .filter(MarketplaceListing.id == listing["id"])
            .first()
        )
        # The local row still moves to the new rate even though the push failed.
        assert Decimal(str(stored_listing.gst_rate)) == Decimal("12")
        assert stored_listing.last_error

    def test_clearing_the_hsn_reaches_the_remote_listing(
        self, client, db_session, fake
    ):
        company, product, listing = self._listed_product(client, db_session, fake)

        # The listing is published at creation, so last_published_at already
        # has a value: only a later value proves the clear was pushed.
        db_session.expire_all()
        before = (
            db_session.query(MarketplaceListing)
            .filter(MarketplaceListing.id == listing["id"])
            .first()
        )
        published_at = before.last_published_at
        assert published_at is not None

        updated = client.put(
            f"/api/products/{product.id}",
            json={
                "sku": "P1",
                "name": "Product P1",
                "price": 125.0,
                "gst_rate": 18,
                "hsn_sac": None,
                "unit": "Pieces",
            },
            headers=headers_for(company),
        )
        assert updated.status_code == 200
        assert updated.json()["hsn_sac"] is None

        db_session.expire_all()
        stored = (
            db_session.query(MarketplaceListing)
            .filter(MarketplaceListing.id == listing["id"])
            .first()
        )
        assert stored.hsn_sac is None
        # last_published_at only moves after a successful remote push, so a
        # later value proves the clear was pushed, not just written locally.
        # (The fake drops nulls from PATCH bodies, so its own copy keeps
        # the old HSN.)
        assert stored.last_published_at > published_at

    def test_csv_import_gst_edit_resyncs_the_open_listing(
        self, client, db_session, fake
    ):
        company, product, listing = self._listed_product(client, db_session, fake)

        csv_content = (
            "Item Name,Item Code,Selling Price,Current Stock,Tax,HSN Code,Unit\n"
            "Product P1,P1,125,100,12,8483,Numbers\n"
        )
        imported = client.post(
            "/api/products/import-csv",
            files={"file": ("p.csv", csv_content.encode(), "text/csv")},
            headers=headers_for(company),
        )
        assert imported.status_code == 200
        assert imported.json()["updated"] == 1

        synced = self._read_listing(client, company, listing["id"])
        assert synced["gst_rate"] == "12.00"
        assert synced["hsn_sac"] == "8483"
        assert synced["unit"] == "Numbers"
        # The remote marketplace must quote the new rate too, not just our row.
        assert Decimal(
            fake.listings[listing["remote_listing_id"]]["gst_rate"]
        ) == Decimal("12")
