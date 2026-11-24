"""Record on each invoice line whether saving it moved stock (#905).

Cancelling, restoring, editing or returning against an invoice used to read the
product's "Maintain inventory" setting as it is now, so switching it after the
invoice was saved put back stock that never left, or kept stock that did.

Nothing recorded the setting at the time, so existing lines are filled from each
product's setting today. That is exactly what the app assumed before this change,
so no stock moves and no existing behaviour changes; the record only protects
switches made from now on. The column stays nullable: a line nothing has filled in
falls back to the product's current setting, as before.
"""

from sqlalchemy import text


def up(conn) -> None:
    conn.execute(text("ALTER TABLE invoice_items ADD COLUMN IF NOT EXISTS stock_applied BOOLEAN"))
    conn.execute(text(
        "UPDATE invoice_items AS ii SET stock_applied = p.maintain_inventory "
        "FROM products AS p WHERE p.id = ii.product_id AND ii.stock_applied IS NULL"
    ))


def down(conn) -> None:
    conn.execute(text("ALTER TABLE invoice_items DROP COLUMN IF EXISTS stock_applied"))
