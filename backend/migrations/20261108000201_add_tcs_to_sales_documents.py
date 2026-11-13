"""Optional TCS on sales invoices (s.394(1) Income-tax Act 2025, s.206C of the 1961 Act).

Everything is off or zero by default, so a company that never turns TCS on sees no
change:

* ``company_profiles.enable_tcs`` turns the feature on for a company.
* ``buyers.tcs_declaration_received`` records a buyer's s.394(2) declaration
  (goods of Sl. No. 1 to 5 bought for manufacturing), after which no TCS is suggested.
* Invoices and quotations keep their own copy of the section, rate, base and amount,
  so a later change to ``tax_withholding_sections`` never changes a saved document.
  TCS sits outside the GST columns: ``total_amount`` is taxable + GST - discount +
  TCS + round-off.
* Credit notes and their lines carry the TCS they reverse, so a full credit note
  settles the whole of a TCS invoice.
"""

from sqlalchemy import text


_DOCUMENT_TABLES = ("invoices", "quotations")


def up(conn) -> None:
    conn.execute(text(
        "ALTER TABLE company_profiles ADD COLUMN IF NOT EXISTS enable_tcs BOOLEAN NOT NULL DEFAULT FALSE"
    ))
    conn.execute(text(
        "ALTER TABLE buyers ADD COLUMN IF NOT EXISTS tcs_declaration_received BOOLEAN NOT NULL DEFAULT FALSE"
    ))
    for table in _DOCUMENT_TABLES:
        conn.execute(text(
            f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS tcs_section_id INTEGER "
            "REFERENCES tax_withholding_sections(id)"
        ))
        conn.execute(text(f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS tcs_section_ref VARCHAR(64)"))
        conn.execute(text(f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS tcs_rate NUMERIC(7,3)"))
        conn.execute(text(
            f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS tcs_base_amount NUMERIC(10,2) NOT NULL DEFAULT 0"
        ))
        conn.execute(text(
            f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS tcs_amount NUMERIC(10,2) NOT NULL DEFAULT 0"
        ))
    # The TCS collected report reads sales invoices that carry TCS, by date.
    conn.execute(text(
        "CREATE INDEX IF NOT EXISTS ix_invoices_company_tcs_date ON invoices (company_id, invoice_date) "
        "WHERE tcs_amount <> 0"
    ))
    conn.execute(text(
        "ALTER TABLE credit_notes ADD COLUMN IF NOT EXISTS tcs_amount NUMERIC(10,2) NOT NULL DEFAULT 0"
    ))
    conn.execute(text(
        "ALTER TABLE credit_note_items ADD COLUMN IF NOT EXISTS tcs_amount NUMERIC(10,2) NOT NULL DEFAULT 0"
    ))


def down(conn) -> None:
    conn.execute(text("ALTER TABLE credit_note_items DROP COLUMN IF EXISTS tcs_amount"))
    conn.execute(text("ALTER TABLE credit_notes DROP COLUMN IF EXISTS tcs_amount"))
    conn.execute(text("DROP INDEX IF EXISTS ix_invoices_company_tcs_date"))
    for table in _DOCUMENT_TABLES:
        for column in ("tcs_amount", "tcs_base_amount", "tcs_rate", "tcs_section_ref", "tcs_section_id"):
            conn.execute(text(f"ALTER TABLE {table} DROP COLUMN IF EXISTS {column}"))
    conn.execute(text("ALTER TABLE buyers DROP COLUMN IF EXISTS tcs_declaration_received"))
    conn.execute(text("ALTER TABLE company_profiles DROP COLUMN IF EXISTS enable_tcs"))
