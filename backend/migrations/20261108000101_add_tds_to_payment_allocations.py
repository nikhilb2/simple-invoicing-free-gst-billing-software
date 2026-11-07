"""Record TDS deducted per invoice on a receipt or a payment (#768, #770).

Payment.amount stays the cash amount. The TDS the customer kept back (or that
we kept back from a supplier) is stored per invoice allocation, with its own
copy of the section reference, rate and base so that a later change to the
section table never changes a saved receipt.
"""

from sqlalchemy import text


def up(conn) -> None:
    conn.execute(text(
        "ALTER TABLE payment_invoice_allocations "
        "ADD COLUMN IF NOT EXISTS tds_amount NUMERIC(10,2) NOT NULL DEFAULT 0"
    ))
    conn.execute(text(
        "ALTER TABLE payment_invoice_allocations "
        "ADD COLUMN IF NOT EXISTS tds_section_id INTEGER REFERENCES tax_withholding_sections(id)"
    ))
    conn.execute(text(
        "ALTER TABLE payment_invoice_allocations ADD COLUMN IF NOT EXISTS tds_section_ref VARCHAR(64)"
    ))
    conn.execute(text(
        "ALTER TABLE payment_invoice_allocations ADD COLUMN IF NOT EXISTS tds_rate NUMERIC(7,3)"
    ))
    conn.execute(text(
        "ALTER TABLE payment_invoice_allocations ADD COLUMN IF NOT EXISTS tds_base_amount NUMERIC(10,2)"
    ))
    conn.execute(text(
        "ALTER TABLE payment_invoice_allocations "
        "ADD COLUMN IF NOT EXISTS tds_certificate_received BOOLEAN NOT NULL DEFAULT false"
    ))
    conn.execute(text(
        "CREATE INDEX IF NOT EXISTS ix_payment_invoice_allocations_tds "
        "ON payment_invoice_allocations (invoice_id) WHERE tds_amount > 0"
    ))


def down(conn) -> None:
    conn.execute(text("DROP INDEX IF EXISTS ix_payment_invoice_allocations_tds"))
    for column in (
        "tds_certificate_received",
        "tds_base_amount",
        "tds_rate",
        "tds_section_ref",
        "tds_section_id",
        "tds_amount",
    ):
        conn.execute(text(f"ALTER TABLE payment_invoice_allocations DROP COLUMN IF EXISTS {column}"))
