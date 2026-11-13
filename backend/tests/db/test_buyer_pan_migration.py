"""The invoice buyer-PAN snapshot migration backfills TCS invoices from their ledger."""

import importlib.util
import uuid
from pathlib import Path

import pytest
from sqlalchemy import create_engine, text

import src.models  # noqa: F401
from src.core.config import settings
from src.db.base import Base

MIGRATION = Path(__file__).resolve().parents[2] / "migrations" / "20261109000001_add_buyer_pan_to_invoices.py"

pytestmark = pytest.mark.skipif(
    not settings.DATABASE_URL.startswith("postgres"),
    reason="migrations are Postgres DDL",
)


@pytest.fixture
def conn():
    schema = f"buyer_pan_{uuid.uuid4().hex[:10]}"
    engine = create_engine(settings.DATABASE_URL, connect_args={"options": f"-csearch_path={schema}"})
    with engine.connect() as connection:
        transaction = connection.begin()
        connection.execute(text(f'CREATE SCHEMA "{schema}"'))
        yield connection
        transaction.rollback()
    engine.dispose()


def _buyer(conn, name, gst, pan):
    return conn.execute(text(
        "INSERT INTO buyers (name, address, gst, pan, phone_number) VALUES (:n, '', :g, :p, '') RETURNING id"
    ), {"n": name, "g": gst, "p": pan}).scalar()


def _invoice(conn, buyer_id, tcs_section_id, buyer_gst):
    return conn.execute(text(
        "INSERT INTO invoices (buyer_id, buyer_gst, voucher_type, status, credit_status, tcs_section_id) "
        "VALUES (:b, :g, 'sales', 'active', 'none', :s) RETURNING id"
    ), {"b": buyer_id, "g": buyer_gst, "s": tcs_section_id}).scalar()


def test_backfill_uses_the_ledger_pan_then_the_gstin(conn):
    Base.metadata.create_all(bind=conn)
    conn.execute(text("ALTER TABLE invoices DROP COLUMN buyer_pan"))
    # Only the columns the migration reads matter; relax the rest so rows stay small.
    for (column,) in conn.execute(text(
        "SELECT column_name FROM information_schema.columns WHERE table_schema = current_schema() "
        "AND table_name = 'invoices' AND is_nullable = 'NO' AND column_default IS NULL AND column_name <> 'id'"
    )).fetchall():
        conn.execute(text(f'ALTER TABLE invoices ALTER COLUMN "{column}" DROP NOT NULL'))
    section = conn.execute(text(
        "INSERT INTO tax_withholding_sections (kind, act, section_ref, legacy_code, nature, rate_individual_huf, "
        "rate_other, rate_no_pan, base, effective_from) "
        "VALUES ('tcs', 2025, 'x', '206C(1)', 'Sale of scrap', 2, 2, 5, 'gross', '2026-04-01') RETURNING id"
    )).scalar()
    with_pan = _buyer(conn, "A", "", "pqrst6789u")
    with_gstin = _buyer(conn, "B", "29ABCDE1234F1ZW", None)
    plain = _buyer(conn, "C", "29ABCDE1234F1ZW", None)
    ids = [
        _invoice(conn, with_pan, section, None),
        _invoice(conn, with_gstin, section, "29ABCDE1234F1ZW"),
        _invoice(conn, plain, None, "29ABCDE1234F1ZW"),
    ]

    spec = importlib.util.spec_from_file_location("buyer_pan_migration", MIGRATION)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.up(conn)
    module.up(conn)  # safe to run twice

    got = [conn.execute(text("SELECT buyer_pan FROM invoices WHERE id = :i"), {"i": i}).scalar() for i in ids]
    assert got == ["PQRST6789U", "ABCDE1234F", None]
