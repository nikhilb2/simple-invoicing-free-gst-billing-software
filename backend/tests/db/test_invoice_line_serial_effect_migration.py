"""The #1068 migration fills invoice_items.serials_applied only where the serial rows are certain."""

import importlib.util
import uuid
from pathlib import Path

import pytest
from sqlalchemy import create_engine, text

from src.core.config import settings

MIGRATION = Path(__file__).resolve().parents[2] / "migrations" / "20261126000001_record_invoice_line_serial_effect.py"

pytestmark = pytest.mark.skipif(
    not settings.DATABASE_URL.startswith("postgres"),
    reason="migrations are Postgres DDL",
)


def _load():
    spec = importlib.util.spec_from_file_location(MIGRATION.stem, MIGRATION)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def conn():
    schema = f"line_serial_{uuid.uuid4().hex[:10]}"
    engine = create_engine(settings.DATABASE_URL, connect_args={"options": f"-csearch_path={schema}"})
    with engine.connect() as connection:
        transaction = connection.begin()
        connection.execute(text(f'CREATE SCHEMA "{schema}"'))
        # Only the columns the migration reads, typed as the app creates them.
        connection.execute(text("SET LOCAL TIME ZONE 'Asia/Kolkata'"))
        connection.execute(text("CREATE TABLE products (id INTEGER PRIMARY KEY)"))
        connection.execute(text(
            "CREATE TABLE invoices (id INTEGER PRIMARY KEY, voucher_type VARCHAR NOT NULL, created_at TIMESTAMP)"
        ))
        connection.execute(text(
            "CREATE TABLE invoice_items (id INTEGER PRIMARY KEY, invoice_id INTEGER NOT NULL REFERENCES invoices(id), "
            "product_id INTEGER NOT NULL REFERENCES products(id))"
        ))
        connection.execute(text(
            "CREATE TABLE product_serials (id INTEGER PRIMARY KEY, product_id INTEGER NOT NULL, status VARCHAR NOT NULL, "
            "purchase_invoice_id INTEGER, sales_invoice_id INTEGER, created_at TIMESTAMPTZ NOT NULL)"
        ))
        # 1 was tracked from the start, 2 had tracking turned on in March, 3 never.
        connection.execute(text("INSERT INTO products VALUES (1), (2), (3)"))
        connection.execute(text(
            "INSERT INTO invoices VALUES "
            "(1, 'purchase', '2026-01-01 10:00'), "
            "(2, 'sales', '2026-01-05 10:00'), "
            "(3, 'sales', '2026-01-06 10:00'), "
            "(4, 'sales', '2026-02-01 10:00'), "
            "(5, 'sales', '2026-02-28 12:00'), "
            "(6, 'purchase', '2026-02-02 10:00'), "
            "(7, 'sales', NULL)"
        ))
        connection.execute(text(
            "INSERT INTO product_serials VALUES "
            "(100, 1, 'sold', 1, 2, '2026-01-01 10:00+00'), "
            "(101, 1, 'sold', 1, 99, '2026-01-01 10:00+00'), "
            "(102, 2, 'in_stock', NULL, NULL, '2026-03-01 00:00+00')"
        ))
        connection.execute(text(
            "INSERT INTO invoice_items VALUES "
            "(10, 1, 1), "  # received units 100 and 101
            "(11, 2, 1), "  # sold unit 100
            "(12, 3, 1), "  # no unit linked, but the product had units: sold elsewhere, or untracked?
            "(13, 4, 2), "  # sold a month before the product had any serial
            "(14, 5, 2), "  # sold within a day of the first serial: too close to tell
            "(15, 6, 2), "  # a purchase with no units received none
            "(16, 4, 3), "
            "(17, 6, 3), "
            "(18, 7, 3)"    # no creation time to compare
        ))
        yield connection
        transaction.rollback()
    engine.dispose()


def _recorded(conn) -> dict:
    return dict(conn.execute(text("SELECT id, serials_applied FROM invoice_items ORDER BY id")).fetchall())


EXPECTED = {
    10: True,
    11: True,
    12: None,
    13: False,
    14: None,
    15: False,
    16: False,
    17: False,
    18: None,
}


def test_up_records_only_what_the_serial_rows_make_certain_and_is_idempotent(conn):
    migration = _load()
    migration.up(conn)
    assert _recorded(conn) == EXPECTED

    # A value already recorded is never overwritten, even if the rows change.
    conn.execute(text("UPDATE product_serials SET sales_invoice_id = 4 WHERE id = 102"))
    conn.execute(text("UPDATE product_serials SET sales_invoice_id = NULL WHERE id = 100"))
    migration.up(conn)
    assert _recorded(conn) == EXPECTED


def test_down_drops_the_column(conn):
    migration = _load()
    migration.up(conn)
    migration.down(conn)
    columns = {
        name
        for (name,) in conn.execute(text(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_schema = current_schema() AND table_name = 'invoice_items'"
        ))
    }
    assert columns == {"id", "invoice_id", "product_id"}
    migration.down(conn)
