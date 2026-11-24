"""Let a ledger be soft-deleted (#1050).

Deleting a ledger that has entries cancels them and hides the ledger instead of
removing the row: its cancelled invoices, notes and payments still point at it, and
reports still read its name. ``deleted_at`` marks it hidden and ``deleted_by`` says
who did it. Both are new and nullable, so every existing ledger stays live.

A party can come back as a new ledger with the same GSTIN, so the per-company GSTIN
uniqueness (20260425000001) now covers live ledgers only. That index is only made
less strict, so no existing row can break it.
"""

from sqlalchemy import text


def up(conn) -> None:
    conn.execute(text("ALTER TABLE buyers ADD COLUMN IF NOT EXISTS deleted_at TIMESTAMP"))
    conn.execute(text(
        "ALTER TABLE buyers ADD COLUMN IF NOT EXISTS deleted_by INTEGER "
        "REFERENCES users(id) ON DELETE SET NULL"
    ))
    conn.execute(text("DROP INDEX IF EXISTS ux_buyers_company_id_gst"))
    conn.execute(text(
        "CREATE UNIQUE INDEX IF NOT EXISTS ux_buyers_company_id_gst "
        "ON buyers(company_id, gst) WHERE gst IS NOT NULL AND deleted_at IS NULL"
    ))


def down(conn) -> None:
    # The stricter index cannot come back while a deleted ledger shares its GSTIN
    # with a live one. The CREATE then fails and the migration's transaction puts
    # everything back as it was.
    conn.execute(text("DROP INDEX IF EXISTS ux_buyers_company_id_gst"))
    conn.execute(text(
        "CREATE UNIQUE INDEX IF NOT EXISTS ux_buyers_company_id_gst "
        "ON buyers(company_id, gst) WHERE gst IS NOT NULL"
    ))
    conn.execute(text("ALTER TABLE buyers DROP COLUMN IF EXISTS deleted_by"))
    conn.execute(text("ALTER TABLE buyers DROP COLUMN IF EXISTS deleted_at"))
