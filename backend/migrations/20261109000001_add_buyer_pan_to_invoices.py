"""Keep the buyer's PAN on the invoice when TCS is applied.

The TCS collected report names the buyer's PAN and the rate depends on whether the
buyer had one. Reading it live from the ledger meant editing a ledger later changed
the PAN on past quarters' reports. Like ``buyer_gst`` and ``buyer_name``, the invoice
now keeps its own copy. Existing TCS invoices are filled from their ledger (its PAN,
else the one inside its GSTIN).
"""

from sqlalchemy import text


def up(conn) -> None:
    conn.execute(text("ALTER TABLE invoices ADD COLUMN IF NOT EXISTS buyer_pan VARCHAR(10)"))
    conn.execute(text(
        "UPDATE invoices SET buyer_pan = COALESCE("
        "NULLIF(UPPER(TRIM(b.pan)), ''), "
        "CASE WHEN UPPER(TRIM(COALESCE(invoices.buyer_gst, b.gst))) ~ '^[0-9]{2}[A-Z]{5}[0-9]{4}[A-Z]' "
        "THEN SUBSTRING(UPPER(TRIM(COALESCE(invoices.buyer_gst, b.gst))) FROM 3 FOR 10) END) "
        "FROM buyers b WHERE b.id = invoices.buyer_id AND invoices.tcs_section_id IS NOT NULL "
        "AND invoices.buyer_pan IS NULL"
    ))


def down(conn) -> None:
    conn.execute(text("ALTER TABLE invoices DROP COLUMN IF EXISTS buyer_pan"))
