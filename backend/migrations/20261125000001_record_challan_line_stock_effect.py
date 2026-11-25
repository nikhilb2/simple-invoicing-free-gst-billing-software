"""Record on each delivery challan line whether it took its goods out of stock (#1067).

Cancelling, editing or invoicing a challan used to read the product's "Maintain
inventory" setting as it is now, so switching it while the challan was open put
back stock that never left, or kept stock that did. #905 fixed the same for
invoice lines.

Nothing recorded the setting at the time, so existing lines are filled from each
product's setting today. That is exactly what the app assumed before this change,
so no stock moves and no existing behaviour changes; the record only protects
switches made from now on. The column stays nullable: a line nothing has filled in
falls back to the product's current setting, as before.
"""

from sqlalchemy import text


def up(conn) -> None:
    conn.execute(text("ALTER TABLE delivery_challan_items ADD COLUMN IF NOT EXISTS stock_applied BOOLEAN"))
    conn.execute(text(
        "UPDATE delivery_challan_items AS dci SET stock_applied = p.maintain_inventory "
        "FROM products AS p WHERE p.id = dci.product_id AND dci.stock_applied IS NULL"
    ))


def down(conn) -> None:
    conn.execute(text("ALTER TABLE delivery_challan_items DROP COLUMN IF EXISTS stock_applied"))
