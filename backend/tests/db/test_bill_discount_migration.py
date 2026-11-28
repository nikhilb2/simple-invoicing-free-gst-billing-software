"""The #1154 migration: every existing document stays 'after_tax', nothing is recalculated."""

import importlib.util
import uuid
from pathlib import Path

import pytest
from sqlalchemy import create_engine, text

import src.models  # noqa: F401
from src.core.config import settings
from src.db.base import Base

MIGRATION = Path(__file__).resolve().parents[2] / "migrations" / "20261128000001_bill_discount_before_gst.py"

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
    schema = f"bill_disc_{uuid.uuid4().hex[:10]}"
    engine = create_engine(settings.DATABASE_URL, connect_args={"options": f"-csearch_path={schema}"})
    with engine.connect() as connection:
        transaction = connection.begin()
        connection.execute(text(f'CREATE SCHEMA "{schema}"'))
        yield connection
        transaction.rollback()
    engine.dispose()


def _old_tables(conn) -> None:
    """Only the columns that matter here, as they stood before #1154."""
    for document, line in (("invoices", "invoice_items"), ("quotations", "quotation_items")):
        conn.execute(text(
            f"CREATE TABLE {document} (id INTEGER PRIMARY KEY, discount_type VARCHAR(20), "
            "discount_value NUMERIC(10, 2), taxable_amount NUMERIC(10, 2), total_amount NUMERIC(10, 2))"
        ))
        conn.execute(text(
            f"CREATE TABLE {line} (id INTEGER PRIMARY KEY, parent_id INTEGER, "
            "taxable_amount NUMERIC(10, 2), line_total NUMERIC(10, 2))"
        ))
        # The worked example as it was saved: 300 at 18%, 50 off after GST.
        conn.execute(text(f"INSERT INTO {document} VALUES (1, 'net', 50, 300, 304), (2, NULL, NULL, 100, 118)"))
        conn.execute(text(f"INSERT INTO {line} VALUES (10, 1, 300, 354), (11, 2, 100, 118)"))


def test_existing_rows_stay_after_gst_and_keep_their_figures(conn):
    _old_tables(conn)
    _load().up(conn)

    for document, line in (("invoices", "invoice_items"), ("quotations", "quotation_items")):
        assert conn.execute(text(
            f"SELECT id, discount_mode, taxable_amount, total_amount FROM {document} ORDER BY id"
        )).fetchall() == [(1, "after_tax", 300, 304), (2, "after_tax", 100, 118)]
        assert conn.execute(text(
            f"SELECT id, bill_discount_amount, taxable_amount, line_total FROM {line} ORDER BY id"
        )).fetchall() == [(10, 0, 300, 354), (11, 0, 100, 118)]

        # A row written after the migration takes the discount before GST.
        conn.execute(text(f"INSERT INTO {document} (id) VALUES (3)"))
        assert conn.execute(text(f"SELECT discount_mode FROM {document} WHERE id = 3")).scalar() == "before_tax"
        conn.execute(text(f"INSERT INTO {line} (id, parent_id) VALUES (12, 3)"))
        assert conn.execute(text(f"SELECT bill_discount_amount FROM {line} WHERE id = 12")).scalar() == 0


def test_running_twice_changes_nothing(conn):
    _old_tables(conn)
    migration = _load()
    migration.up(conn)
    migration.up(conn)
    assert conn.execute(text("SELECT discount_mode FROM invoices WHERE id = 1")).scalar() == "after_tax"


def test_columns_are_not_null(conn):
    _old_tables(conn)
    _load().up(conn)
    rows = conn.execute(text(
        "SELECT table_name, column_name, is_nullable FROM information_schema.columns "
        "WHERE table_schema = current_schema() AND column_name IN ('discount_mode', 'bill_discount_amount') "
        "ORDER BY table_name"
    )).fetchall()
    assert rows == [
        ("invoice_items", "bill_discount_amount", "NO"),
        ("invoices", "discount_mode", "NO"),
        ("quotation_items", "bill_discount_amount", "NO"),
        ("quotations", "discount_mode", "NO"),
    ]


def test_a_fresh_database_gets_the_models_defaults(conn):
    """Boot runs create_all first; the migration then finds the columns and keeps 'before_tax'."""
    Base.metadata.create_all(bind=conn)
    _load().up(conn)
    default = conn.execute(text(
        "SELECT column_default FROM information_schema.columns WHERE table_schema = current_schema() "
        "AND table_name = 'invoices' AND column_name = 'discount_mode'"
    )).scalar()
    assert "before_tax" in default


def test_down_removes_the_columns(conn):
    _old_tables(conn)
    migration = _load()
    migration.up(conn)
    migration.down(conn)
    left = conn.execute(text(
        "SELECT count(*) FROM information_schema.columns WHERE table_schema = current_schema() "
        "AND column_name IN ('discount_mode', 'bill_discount_amount')"
    )).scalar()
    assert left == 0
