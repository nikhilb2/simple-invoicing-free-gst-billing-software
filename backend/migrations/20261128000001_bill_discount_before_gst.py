"""Take the bill discount before GST on new documents (#1154).

Adds ``discount_mode`` to invoices and quotations, and ``bill_discount_amount`` (each
line's share of a before-GST bill discount) to their lines.

Safe on existing data, and nothing is recalculated:

- ``discount_mode`` is added with the default 'after_tax', so every document saved
  before this release keeps taking its discount after GST and keeps its stored
  figures, PDFs and returns exactly as they were. Only then does the default become
  'before_tax', for rows written from now on.
- ``bill_discount_amount`` is added as 0 on every existing line, which is what an
  'after_tax' line carries.

On a fresh database the tables already have both columns from the models, so the
ADD COLUMNs do nothing and the defaults are set as the models have them.
"""

from sqlalchemy import text

_DOCUMENTS = ("invoices", "quotations")
_LINES = ("invoice_items", "quotation_items")


def up(conn) -> None:
    for table in _DOCUMENTS:
        conn.execute(text(
            f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS discount_mode VARCHAR(20) NOT NULL DEFAULT 'after_tax'"
        ))
        conn.execute(text(f"ALTER TABLE {table} ALTER COLUMN discount_mode SET DEFAULT 'before_tax'"))
    for table in _LINES:
        conn.execute(text(
            f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS bill_discount_amount NUMERIC(10, 2) NOT NULL DEFAULT 0"
        ))


def down(conn) -> None:
    for table in _LINES:
        conn.execute(text(f"ALTER TABLE {table} DROP COLUMN IF EXISTS bill_discount_amount"))
    for table in _DOCUMENTS:
        conn.execute(text(f"ALTER TABLE {table} DROP COLUMN IF EXISTS discount_mode"))
