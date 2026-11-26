"""Record on each invoice line whether it carried serial numbers (#1068).

Restoring, editing or returning against an invoice decided from the product's
"Track serials" setting as it is now, so a line saved while the product was
untracked was asked for serial numbers it never had once tracking was switched on:
restore refused, saying the units had gone out on another invoice.

Existing lines are filled only where the serial rows say for certain what the line
did, and stay NULL (the old rule) everywhere else. Nothing moves on deploy:

- TRUE where serial rows are linked to the line's invoice and product. A purchase
  links the units it received (kept when cancelled, as void), a sale the units it
  sold (kept when cancelled).
- FALSE for a purchase line with no such rows: nothing ever unlinks a purchase's
  units, so it received none.
- FALSE for a sale line with no such rows when the product had no serial row at
  all until more than a day after the invoice. A sale with serials needs its
  units registered first, so it sold none. The day of margin absorbs clock and
  time zone differences (invoices.created_at is naive UTC, the serial rows'
  timestamp has a zone).

A sale line left NULL, such as a cancelled sale whose units were sold again since,
keeps following the product's setting as before.
"""

from sqlalchemy import text

_LINKED = (
    "EXISTS (SELECT 1 FROM product_serials AS ps WHERE ps.product_id = ii.product_id "
    "AND (CASE WHEN i.voucher_type = 'purchase' THEN ps.purchase_invoice_id "
    "ELSE ps.sales_invoice_id END) = i.id)"
)


def up(conn) -> None:
    conn.execute(text("ALTER TABLE invoice_items ADD COLUMN IF NOT EXISTS serials_applied BOOLEAN"))
    conn.execute(text(
        "UPDATE invoice_items AS ii SET serials_applied = TRUE FROM invoices AS i "
        f"WHERE i.id = ii.invoice_id AND ii.serials_applied IS NULL AND {_LINKED}"
    ))
    conn.execute(text(
        "UPDATE invoice_items AS ii SET serials_applied = FALSE FROM invoices AS i "
        "WHERE i.id = ii.invoice_id AND ii.serials_applied IS NULL "
        f"AND i.voucher_type = 'purchase' AND NOT {_LINKED}"
    ))
    conn.execute(text(
        "UPDATE invoice_items AS ii SET serials_applied = FALSE FROM invoices AS i "
        "WHERE i.id = ii.invoice_id AND ii.serials_applied IS NULL "
        f"AND i.voucher_type <> 'purchase' AND i.created_at IS NOT NULL AND NOT {_LINKED} "
        "AND NOT EXISTS (SELECT 1 FROM product_serials AS ps WHERE ps.product_id = ii.product_id "
        "AND ps.created_at < (i.created_at AT TIME ZONE 'UTC') + INTERVAL '1 day')"
    ))


def down(conn) -> None:
    conn.execute(text("ALTER TABLE invoice_items DROP COLUMN IF EXISTS serials_applied"))
