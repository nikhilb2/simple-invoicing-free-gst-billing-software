"""Record invoice cancellation time without inventing dates for old records."""

from sqlalchemy import text


def up(conn) -> None:
    conn.execute(text("ALTER TABLE invoices ADD COLUMN IF NOT EXISTS cancelled_at TIMESTAMP"))


def down(conn) -> None:
    conn.execute(text("ALTER TABLE invoices DROP COLUMN IF EXISTS cancelled_at"))
