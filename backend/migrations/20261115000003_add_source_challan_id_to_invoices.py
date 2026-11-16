"""
Link an invoice to the delivery challan it was made from (#840).

The partial unique index is the rule itself: at most one live invoice per challan.
A cancelled invoice stays behind as history and falls out of the index, so the
challan can be invoiced again, and restoring the old one while a newer invoice is
live fails here too.

create_all does not alter an existing table, so on an upgraded database this is what
actually adds the column and the index.
"""

from sqlalchemy import text


def up(conn) -> None:
    conn.execute(text(
        "ALTER TABLE invoices ADD COLUMN IF NOT EXISTS "
        "source_challan_id INTEGER REFERENCES delivery_challans(id)"
    ))
    conn.execute(text("""
        CREATE UNIQUE INDEX IF NOT EXISTS ux_invoices_active_source_challan
        ON invoices (source_challan_id)
        WHERE source_challan_id IS NOT NULL AND status = 'active'
    """))


def down(conn) -> None:
    conn.execute(text("DROP INDEX IF EXISTS ux_invoices_active_source_challan"))
    conn.execute(text("ALTER TABLE invoices DROP COLUMN IF EXISTS source_challan_id"))
