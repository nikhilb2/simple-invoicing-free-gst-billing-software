"""Use INR for the untouched company created during a fresh installation."""

from sqlalchemy import text


def up(conn) -> None:
    # A fresh migration chain creates the legacy USD profile before seed_admin
    # creates the first account. Never reinterpret a configured installation's
    # currency, even if it has not issued an invoice yet.
    conn.execute(text("""
        UPDATE company_profiles SET currency_code = 'INR'
        WHERE name = 'Default Company' AND currency_code = 'USD'
          AND COALESCE(address, '') = '' AND COALESCE(gst, '') = ''
          AND NOT EXISTS (SELECT 1 FROM users)
          AND NOT EXISTS (SELECT 1 FROM invoices)
          AND NOT EXISTS (SELECT 1 FROM buyers)
          AND NOT EXISTS (SELECT 1 FROM products)
          AND NOT EXISTS (SELECT 1 FROM payments)
          AND NOT EXISTS (SELECT 1 FROM company_accounts)
    """))


def down(conn) -> None:
    # The user may have started billing in INR since up(); reverting the value
    # would relabel their amounts, so this data default has no automatic undo.
    pass
