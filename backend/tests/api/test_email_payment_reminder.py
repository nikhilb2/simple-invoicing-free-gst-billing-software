"""The reminder's "last payment" line must only count money received.

A ledger can be both customer and supplier. Before this, the single reminder picked
the newest active payment of *any* voucher type, so a payment made *to* the party
was reported as their last payment, while the bulk reminder (which filters on
receipts) reported the right one. Both now share one query.
"""

from datetime import datetime
from unittest.mock import AsyncMock, patch

RECEIPT_DATE = datetime(2026, 3, 1, 10, 0, 0)
PAYMENT_DATE = datetime(2026, 3, 20, 10, 0, 0)


def _create_ledger(client):
    response = client.post(
        "/api/ledgers/",
        json={
            "name": "Dual Role Ledger",
            "address": "Mumbai",
            "gst": "27ABCDE1234F1Z0",
            "phone_number": "9999999999",
            "email": "ledger@example.com",
            "website": "",
            "bank_name": "",
            "branch_name": "",
            "account_name": "",
            "account_number": "",
            "ifsc_code": "",
        },
    )
    assert response.status_code == 200, response.text
    return response.json()["id"]


def _create_product(client):
    response = client.post(
        "/api/products/",
        json={
            "sku": "REM-001",
            "name": "Reminder Product",
            "description": "",
            "hsn_sac": "9988",
            "price": 100,
            "gst_rate": 0,
        },
    )
    assert response.status_code == 200, response.text
    return response.json()["id"]


def _add_inventory(client, product_id, quantity=50):
    response = client.post(
        "/api/inventory/adjust",
        json={"product_id": product_id, "quantity": quantity},
    )
    assert response.status_code == 200, response.text


def _create_invoice(client, ledger_id, product_id, unit_price):
    response = client.post(
        "/api/invoices/",
        json={
            "ledger_id": ledger_id,
            "voucher_type": "sales",
            "tax_inclusive": False,
            "apply_round_off": False,
            "invoice_date": "2026-02-01",
            "due_date": "2026-02-15",
            "items": [{"product_id": product_id, "quantity": 1, "unit_price": unit_price}],
        },
    )
    assert response.status_code == 200, response.text
    return response.json()


def _create_voucher(client, ledger_id, voucher_type, amount, dt, allocations=None):
    response = client.post(
        "/api/payments/",
        json={
            "ledger_id": ledger_id,
            "voucher_type": voucher_type,
            "amount": amount,
            "date": dt.isoformat(),
            "mode": "bank",
            "invoice_allocations": allocations or [],
        },
    )
    assert response.status_code == 200, response.text
    return response.json()


def _send_single_reminder(client, ledger_id):
    with patch("src.api.routes.email.send_email", new=AsyncMock()) as send_email_mock:
        response = client.post(f"/api/email/payment-reminder/{ledger_id}", json={})
    assert response.status_code == 200, response.text
    send_email_mock.assert_awaited_once()
    return send_email_mock.await_args.kwargs["html_body"]


def _seed(client):
    invoice_numbers = iter(["INV-000101", "INV-000102"])
    with patch(
        "src.services.invoice_processor.generate_next_number",
        side_effect=lambda *args, **kwargs: next(invoice_numbers),
    ), patch(
        "src.api.routes.payments.generate_next_number",
        return_value="PAY-000101",
    ):
        ledger_id = _create_ledger(client)
        product_id = _create_product(client)
        _add_inventory(client, product_id)
        invoice = _create_invoice(client, ledger_id, product_id, 1000)
    return ledger_id, invoice


def test_single_reminder_reports_the_last_receipt_not_the_last_payment_out(client):
    ledger_id, invoice = _seed(client)

    _create_voucher(
        client,
        ledger_id,
        "receipt",
        100,
        RECEIPT_DATE,
        [{"invoice_id": invoice["id"], "allocated_amount": 100}],
    )
    # Money paid *out* to the same party, later than the receipt.
    _create_voucher(client, ledger_id, "payment", 200, PAYMENT_DATE)

    html_body = _send_single_reminder(client, ledger_id)

    assert "Last payment received on 01 Mar 2026" in html_body
    assert "20 Mar 2026" not in html_body


def test_single_reminder_omits_the_line_when_nothing_was_ever_received(client):
    ledger_id, _invoice = _seed(client)

    # Only an outgoing payment, so there is no "last payment received" to show.
    _create_voucher(client, ledger_id, "payment", 200, PAYMENT_DATE)

    html_body = _send_single_reminder(client, ledger_id)

    assert "Last payment received on" not in html_body
    assert "20 Mar 2026" not in html_body


def _create_ledger_with_opening(client, opening_balance, name="Opening Balance Ledger"):
    response = client.post(
        "/api/ledgers/",
        json={
            "name": name,
            "address": "Mumbai",
            "gst": "27ABCDE1234F1Z0",
            "phone_number": "9999999999",
            "email": "opening@example.com",
            "website": "",
            "bank_name": "",
            "branch_name": "",
            "account_name": "",
            "account_number": "",
            "ifsc_code": "",
            "opening_balance": opening_balance,
        },
    )
    assert response.status_code == 200, response.text
    return response.json()["id"]


def _ledger_list_balance(client, ledger_id):
    response = client.get("/api/ledgers/", params={"page_size": 100})
    assert response.status_code == 200, response.text
    row = next(item for item in response.json()["items"] if item["id"] == ledger_id)
    return row["balance"]


def test_single_reminder_outstanding_includes_opening_balance(client):
    """#920: opening balance 50,000 + invoice 1,000 → reminder shows ₹51,000.00,
    the same figure as the ledger list and the statement link."""
    invoice_numbers = iter(["INV-000201"])
    with patch(
        "src.services.invoice_processor.generate_next_number",
        side_effect=lambda *args, **kwargs: next(invoice_numbers),
    ):
        ledger_id = _create_ledger_with_opening(client, 50000)
        product_id = _create_product(client)
        _add_inventory(client, product_id)
        _create_invoice(client, ledger_id, product_id, 1000)

    html_body = _send_single_reminder(client, ledger_id)

    assert "₹51,000.00" in html_body
    assert _ledger_list_balance(client, ledger_id) == 51000.0


def test_single_reminder_with_only_opening_balance_is_not_zero_and_offers_pay(client):
    """#920: an opening balance alone is the whole debt — the reminder must not
    say ₹0.00 and must render the 'View & pay online' button (balance > 0)."""
    ledger_id = _create_ledger_with_opening(client, 25000, name="Opening Only Ledger")

    html_body = _send_single_reminder(client, ledger_id)

    assert "₹25,000.00" in html_body
    assert "Outstanding balance" in html_body
    assert "₹0.00" not in html_body
    assert _ledger_list_balance(client, ledger_id) == 25000.0


def test_single_reminder_outstanding_still_nets_receipts(client):
    """#920 regression guard: money received still reduces the outstanding
    balance, and the reminder matches the ledger list exactly."""
    invoice_numbers = iter(["INV-000202"])
    with patch(
        "src.services.invoice_processor.generate_next_number",
        side_effect=lambda *args, **kwargs: next(invoice_numbers),
    ), patch(
        "src.api.routes.payments.generate_next_number",
        return_value="PAY-000202",
    ):
        ledger_id = _create_ledger_with_opening(client, 50000, name="Netted Ledger")
        product_id = _create_product(client)
        _add_inventory(client, product_id)
        invoice = _create_invoice(client, ledger_id, product_id, 1000)
        _create_voucher(
            client,
            ledger_id,
            "receipt",
            1000,
            RECEIPT_DATE,
            [{"invoice_id": invoice["id"], "allocated_amount": 1000}],
        )

    html_body = _send_single_reminder(client, ledger_id)

    # 50,000 opening + 1,000 invoice − 1,000 receipt = 50,000.
    assert "₹50,000.00" in html_body
    assert _ledger_list_balance(client, ledger_id) == 50000.0


def test_single_reminder_outstanding_matches_ledger_balance_with_payment_voucher(client):
    """#920: payment vouchers (e.g. refunds paid to the party) are part of the
    ledger balance too — the reminder must show the same figure as the list."""
    invoice_numbers = iter(["INV-000203"])
    with patch(
        "src.services.invoice_processor.generate_next_number",
        side_effect=lambda *args, **kwargs: next(invoice_numbers),
    ), patch(
        "src.api.routes.payments.generate_next_number",
        return_value="PAY-000203",
    ):
        ledger_id = _create_ledger_with_opening(client, 50000, name="Voucher Ledger")
        product_id = _create_product(client)
        _add_inventory(client, product_id)
        _create_invoice(client, ledger_id, product_id, 1000)
        _create_voucher(client, ledger_id, "payment", 5000, PAYMENT_DATE)

    html_body = _send_single_reminder(client, ledger_id)

    balance = _ledger_list_balance(client, ledger_id)
    assert balance == 56000.0  # opening 50,000 + invoice 1,000 + payment voucher 5,000
    assert f"₹{balance:,.2f}" in html_body


def test_single_reminder_settled_ledger_shows_clean_zero_and_no_pay_button(client):
    """Review follow-up: _ledger_balances sums plain floats, so a settled
    account (opening 200.20 + invoice 100.10 − receipt 300.30) can leave a
    residue like -2.84e-14. The reminder must round like the statement does
    (round(x, 2) + 0.0): show ₹0.00, never ₹-0.00, and not render the
    'View & pay online' button (which requires outstanding_balance > 0)."""
    invoice_numbers = iter(["INV-000204"])
    with patch(
        "src.services.invoice_processor.generate_next_number",
        side_effect=lambda *args, **kwargs: next(invoice_numbers),
    ), patch(
        "src.api.routes.payments.generate_next_number",
        return_value="PAY-000204",
    ):
        ledger_id = _create_ledger_with_opening(client, 200.20, name="Settled Ledger")
        product_id = _create_product(client)
        _add_inventory(client, product_id)
        invoice = _create_invoice(client, ledger_id, product_id, 100.10)
        # Allocate only up to the invoice's remaining amount; the rest of the
        # receipt stays unallocated but still nets against the ledger balance.
        _create_voucher(
            client,
            ledger_id,
            "receipt",
            300.30,
            RECEIPT_DATE,
            [{"invoice_id": invoice["id"], "allocated_amount": 100.10}],
        )

    html_body = _send_single_reminder(client, ledger_id)

    assert "₹0.00" in html_body
    assert "₹-0.00" not in html_body
    assert "View & pay online" not in html_body
    # The ledger-list API intentionally returns the raw float; the reminder
    # rounds it. Both represent the same settled account.
    assert abs(_ledger_list_balance(client, ledger_id)) < 1e-9
