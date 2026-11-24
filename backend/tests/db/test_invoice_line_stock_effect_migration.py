"""The #905 migration fills invoice_items.stock_applied from each product's setting."""

import importlib.util
import uuid
from pathlib import Path

import pytest
from sqlalchemy import create_engine, text

from src.core.config import settings

MIGRATION = Path(__file__).resolve().parents[2] / "migrations" / "20261124000001_record_invoice_line_stock_effect.py"

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
    schema = f"line_stock_{uuid.uuid4().hex[:10]}"
    engine = create_engine(settings.DATABASE_URL, connect_args={"options": f"-csearch_path={schema}"})
    with engine.connect() as connection:
        transaction = connection.begin()
        connection.execute(text(f'CREATE SCHEMA "{schema}"'))
        # Only the columns the migration reads.
        connection.execute(text("CREATE TABLE products (id INTEGER PRIMARY KEY, maintain_inventory BOOLEAN NOT NULL)"))
        connection.execute(text(
            "CREATE TABLE invoice_items (id INTEGER PRIMARY KEY, product_id INTEGER NOT NULL REFERENCES products(id))"
        ))
        connection.execute(text("INSERT INTO products VALUES (1, TRUE), (2, FALSE)"))
        connection.execute(text("INSERT INTO invoice_items VALUES (10, 1), (11, 2), (12, 1)"))
        yield connection
        transaction.rollback()
    engine.dispose()


def _recorded(conn) -> dict:
    return dict(conn.execute(text("SELECT id, stock_applied FROM invoice_items ORDER BY id")).fetchall())


def test_up_backfills_from_the_product_setting_and_is_idempotent(conn):
    migration = _load()
    migration.up(conn)
    assert _recorded(conn) == {10: True, 11: False, 12: True}

    # A value already recorded is never overwritten, even if the product changed.
    conn.execute(text("UPDATE products SET maintain_inventory = FALSE WHERE id = 1"))
    migration.up(conn)
    assert _recorded(conn) == {10: True, 11: False, 12: True}

    # New rows may leave it empty; the app then reads the product's setting.
    conn.execute(text("INSERT INTO invoice_items (id, product_id) VALUES (13, 2)"))
    assert _recorded(conn)[13] is None


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
    assert columns == {"id", "product_id"}
    migration.down(conn)
