"""Store fractional credit note quantities without changing existing whole units."""

from sqlalchemy import text


def up(conn) -> None:
    # Keep enough integral digits for any quantity from the previous INTEGER column.
    conn.execute(text(
        "ALTER TABLE credit_note_items ALTER COLUMN quantity TYPE NUMERIC(13, 3)"
    ))


def down(conn) -> None:
    # Refuse rather than round: a rollback must never quietly change a credit note.
    fractional = conn.execute(text(
        "SELECT COUNT(*) FROM credit_note_items WHERE quantity <> TRUNC(quantity)"
    )).scalar()
    if fractional:
        raise RuntimeError(
            f"Cannot roll back: {fractional} credit note item(s) have a fractional quantity"
        )
    conn.execute(text(
        "ALTER TABLE credit_note_items ALTER COLUMN quantity TYPE INTEGER USING ROUND(quantity)::integer"
    ))
