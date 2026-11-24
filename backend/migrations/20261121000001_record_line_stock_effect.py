"""Record whether an invoice or credit-note line affected inventory."""

from sqlalchemy import text


def up(conn) -> None:
    conn.execute(text("ALTER TABLE invoice_items ADD COLUMN IF NOT EXISTS stock_applied BOOLEAN"))
    conn.execute(text("ALTER TABLE credit_note_items ADD COLUMN IF NOT EXISTS stock_applied BOOLEAN"))
    # Preserve the behaviour that applied when each existing line was written.
    conn.execute(text("""
        UPDATE invoice_items ii SET stock_applied = p.maintain_inventory
        FROM products p
        WHERE p.id = ii.product_id AND ii.stock_applied IS NULL
    """))
    conn.execute(text("""
        UPDATE credit_note_items cni SET stock_applied = ii.stock_applied
        FROM invoice_items ii
        WHERE ii.id = cni.invoice_item_id AND cni.stock_applied IS NULL
    """))
    conn.execute(text("""
        UPDATE credit_note_items cni SET stock_applied = p.maintain_inventory
        FROM products p
        WHERE p.id = cni.product_id AND cni.stock_applied IS NULL
    """))


def down(conn) -> None:
    conn.execute(text("ALTER TABLE credit_note_items DROP COLUMN IF EXISTS stock_applied"))
    conn.execute(text("ALTER TABLE invoice_items DROP COLUMN IF EXISTS stock_applied"))
