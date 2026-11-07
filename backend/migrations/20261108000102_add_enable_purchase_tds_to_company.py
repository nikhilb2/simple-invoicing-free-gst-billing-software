"""Company setting: deduct TDS on payments to suppliers (#770). Off by default."""

from sqlalchemy import text


def up(conn) -> None:
    conn.execute(text(
        "ALTER TABLE company_profiles "
        "ADD COLUMN IF NOT EXISTS enable_purchase_tds BOOLEAN NOT NULL DEFAULT false"
    ))


def down(conn) -> None:
    conn.execute(text("ALTER TABLE company_profiles DROP COLUMN IF EXISTS enable_purchase_tds"))
