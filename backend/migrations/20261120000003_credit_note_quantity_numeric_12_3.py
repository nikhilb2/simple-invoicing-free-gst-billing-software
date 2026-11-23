"""Match credit_note_items.quantity to the other quantity columns, NUMERIC(12, 3)."""

from sqlalchemy import text


def up(conn) -> None:
    # A return is capped at its invoice line's quantity, which is NUMERIC(12, 3),
    # so every existing row fits. Re-running on a NUMERIC(12, 3) column is a no-op.
    conn.execute(text(
        "ALTER TABLE credit_note_items ALTER COLUMN quantity TYPE NUMERIC(12, 3)"
    ))


def down(conn) -> None:
    conn.execute(text(
        "ALTER TABLE credit_note_items ALTER COLUMN quantity TYPE NUMERIC(13, 3)"
    ))
