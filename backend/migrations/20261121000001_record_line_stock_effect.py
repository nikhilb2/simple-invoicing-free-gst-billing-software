"""Record whether an invoice or credit-note line affected inventory."""

from sqlalchemy import text


def up(conn) -> None:
    # Old rows have no reliable record of their stock effect. Keep it unknown.
    conn.execute(text("ALTER TABLE invoice_items ADD COLUMN IF NOT EXISTS stock_applied BOOLEAN"))
    conn.execute(text("ALTER TABLE credit_note_items ADD COLUMN IF NOT EXISTS stock_applied BOOLEAN"))
