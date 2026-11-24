"""The #1050 migration adds deleted_at/deleted_by to buyers and frees a deleted ledger's GSTIN."""

import importlib.util
import uuid
from pathlib import Path

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.exc import IntegrityError

from src.core.config import settings

MIGRATION = Path(__file__).resolve().parents[2] / "migrations" / "20261124000002_soft_delete_ledgers.py"

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
    schema = f"soft_delete_{uuid.uuid4().hex[:10]}"
    engine = create_engine(settings.DATABASE_URL, connect_args={"options": f"-csearch_path={schema}"})
    with engine.connect() as connection:
        transaction = connection.begin()
        connection.execute(text(f'CREATE SCHEMA "{schema}"'))
        # Only what the migration touches, with the index 20260425000001 left behind.
        connection.execute(text("CREATE TABLE users (id INTEGER PRIMARY KEY)"))
        connection.execute(text("CREATE TABLE buyers (id INTEGER PRIMARY KEY, company_id INTEGER, gst VARCHAR)"))
        connection.execute(text(
            "CREATE UNIQUE INDEX ux_buyers_company_id_gst ON buyers(company_id, gst) WHERE gst IS NOT NULL"
        ))
        connection.execute(text("INSERT INTO users VALUES (7)"))
        connection.execute(text("INSERT INTO buyers VALUES (1, 1, '29AADCB2230M1ZP'), (2, 1, NULL)"))
        yield connection
        transaction.rollback()
    engine.dispose()


def _columns(conn) -> set[str]:
    return {
        name
        for (name,) in conn.execute(text(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_schema = current_schema() AND table_name = 'buyers'"
        ))
    }


def _insert(conn, buyer_id: int, gst: str):
    with conn.begin_nested():
        conn.execute(text("INSERT INTO buyers (id, company_id, gst) VALUES (:i, 1, :g)"), {"i": buyer_id, "g": gst})


def test_up_leaves_every_ledger_live_and_is_idempotent(conn):
    migration = _load()
    migration.up(conn)
    migration.up(conn)

    assert {"deleted_at", "deleted_by"} <= _columns(conn)
    rows = conn.execute(text("SELECT id, deleted_at, deleted_by FROM buyers ORDER BY id")).fetchall()
    assert [tuple(row) for row in rows] == [(1, None, None), (2, None, None)]


def test_a_deleted_ledgers_gstin_can_be_used_again_but_not_twice_live(conn):
    migration = _load()
    migration.up(conn)

    with pytest.raises(IntegrityError):
        _insert(conn, 3, "29AADCB2230M1ZP")

    conn.execute(text("UPDATE buyers SET deleted_at = NOW(), deleted_by = 7 WHERE id = 1"))
    _insert(conn, 3, "29AADCB2230M1ZP")
    with pytest.raises(IntegrityError):
        _insert(conn, 4, "29AADCB2230M1ZP")


def test_deleted_by_lets_go_of_a_removed_user(conn):
    migration = _load()
    migration.up(conn)
    conn.execute(text("UPDATE buyers SET deleted_at = NOW(), deleted_by = 7 WHERE id = 1"))

    conn.execute(text("DELETE FROM users WHERE id = 7"))

    assert conn.execute(text("SELECT deleted_by FROM buyers WHERE id = 1")).scalar() is None


def test_down_restores_the_columns_and_the_stricter_index(conn):
    migration = _load()
    migration.up(conn)
    migration.down(conn)

    assert _columns(conn) == {"id", "company_id", "gst"}
    with pytest.raises(IntegrityError):
        _insert(conn, 3, "29AADCB2230M1ZP")
    migration.down(conn)
