"""
Create product_bulk_updates, the record of confirmed catalogue bulk updates.

Each row's id is the signed preview's id, so confirming the same preview twice
applies it once. The table is company-scoped, so it is listed in src/db/rls.py.
Applying the policy here rather than leaving it to the next boot means the table
never exists on a shared-hosting database without one. Every statement is
idempotent, so a database that already ran the earlier ORM-based version of this
migration is unaffected.
"""

from sqlalchemy import text

from src.core.config import settings
from src.db.rls import ensure_row_level_security


def up(conn) -> None:
    conn.execute(text("""
        CREATE TABLE IF NOT EXISTS product_bulk_updates (
            id VARCHAR(32) PRIMARY KEY,
            company_id INTEGER NOT NULL REFERENCES company_profiles(id),
            user_id INTEGER REFERENCES users(id) ON DELETE SET NULL,
            changes JSON NOT NULL,
            created_at TIMESTAMP NOT NULL DEFAULT now()
        )
    """))

    conn.execute(text("""
        CREATE INDEX IF NOT EXISTS ix_product_bulk_updates_company_id
        ON product_bulk_updates(company_id)
    """))

    if settings.is_shared_hosting:
        ensure_row_level_security(conn)


def down(conn) -> None:
    conn.execute(text("DROP TABLE IF EXISTS product_bulk_updates"))
