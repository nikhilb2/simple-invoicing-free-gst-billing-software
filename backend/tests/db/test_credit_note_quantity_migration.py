"""The credit note quantity migrations widen an INTEGER column to NUMERIC(12, 3)."""

import importlib.util
import uuid
from decimal import Decimal
from pathlib import Path

import pytest
from sqlalchemy import create_engine, text

import src.models  # noqa: F401
from src.core.config import settings
from src.db.base import Base

MIGRATIONS = Path(__file__).resolve().parents[2] / "migrations"
FILES = [
    "20261120000002_fractional_credit_note_quantities.py",
    "20261120000003_credit_note_quantity_numeric_12_3.py",
]

pytestmark = pytest.mark.skipif(
    not settings.DATABASE_URL.startswith("postgres"),
    reason="migrations are Postgres DDL",
)


def _load(name):
    spec = importlib.util.spec_from_file_location(name.removesuffix(".py"), MIGRATIONS / name)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def conn():
    schema = f"cn_qty_{uuid.uuid4().hex[:10]}"
    engine = create_engine(settings.DATABASE_URL, connect_args={"options": f"-csearch_path={schema}"})
    with engine.connect() as connection:
        transaction = connection.begin()
        connection.execute(text(f'CREATE SCHEMA "{schema}"'))
        yield connection
        transaction.rollback()
    engine.dispose()


def _column(conn):
    return conn.execute(text(
        "SELECT data_type, numeric_precision, numeric_scale FROM information_schema.columns "
        "WHERE table_schema = current_schema() AND table_name = 'credit_note_items' AND column_name = 'quantity'"
    )).one()


def _legacy_table(conn):
    Base.metadata.create_all(bind=conn)
    # Only the columns under test matter; relax the rest so rows stay small.
    for (column,) in conn.execute(text(
        "SELECT column_name FROM information_schema.columns WHERE table_schema = current_schema() "
        "AND table_name = 'credit_note_items' AND is_nullable = 'NO' AND column_default IS NULL "
        "AND column_name NOT IN ('id', 'quantity')"
    )).fetchall():
        conn.execute(text(f'ALTER TABLE credit_note_items ALTER COLUMN "{column}" DROP NOT NULL'))
    conn.execute(text("ALTER TABLE credit_note_items DROP CONSTRAINT IF EXISTS credit_note_items_credit_note_id_fkey"))
    conn.execute(text("ALTER TABLE credit_note_items ALTER COLUMN quantity TYPE INTEGER USING ROUND(quantity)::integer"))
    return conn.execute(text("INSERT INTO credit_note_items (quantity) VALUES (7) RETURNING id")).scalar()


def test_up_migrates_a_legacy_integer_column_and_is_idempotent(conn):
    legacy_id = _legacy_table(conn)
    assert _column(conn)[0] == "integer"

    for _ in range(2):
        for name in FILES:
            _load(name).up(conn)

    assert tuple(_column(conn)) == ("numeric", 12, 3)
    assert conn.execute(text("SELECT quantity FROM credit_note_items WHERE id = :i"), {"i": legacy_id}).scalar() == Decimal("7")
    new_id = conn.execute(text("INSERT INTO credit_note_items (quantity) VALUES (1.125) RETURNING id")).scalar()
    assert conn.execute(text("SELECT quantity FROM credit_note_items WHERE id = :i"), {"i": new_id}).scalar() == Decimal("1.125")


def test_down_refuses_to_round_a_fractional_quantity(conn):
    _legacy_table(conn)
    first, second = (_load(name) for name in FILES)
    first.up(conn)
    second.up(conn)
    conn.execute(text("INSERT INTO credit_note_items (quantity) VALUES (1.125)"))

    second.down(conn)
    assert tuple(_column(conn)) == ("numeric", 13, 3)
    with pytest.raises(RuntimeError, match="fractional"):
        first.down(conn)
