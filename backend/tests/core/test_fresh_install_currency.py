"""The fresh-install default must not change an existing company's money unit."""

import importlib.util
from pathlib import Path

import pytest
from sqlalchemy import create_engine, text


path = Path(__file__).resolve().parents[2] / "migrations" / "20261123000001_default_fresh_install_currency_to_inr.py"
spec = importlib.util.spec_from_file_location("fresh_install_currency", path)
migration = importlib.util.module_from_spec(spec)
spec.loader.exec_module(migration)


@pytest.fixture
def conn():
    engine = create_engine("sqlite://")
    with engine.begin() as connection:
        connection.execute(text("CREATE TABLE company_profiles (name TEXT, currency_code TEXT, address TEXT, gst TEXT)"))
        for table in ("users", "invoices", "buyers", "products", "payments", "company_accounts"):
            connection.execute(text(f"CREATE TABLE {table} (id INTEGER)"))
        connection.execute(text("INSERT INTO company_profiles VALUES ('Default Company', 'USD', '', '')"))
        yield connection
    engine.dispose()


def currency(conn):
    return conn.execute(text("SELECT currency_code FROM company_profiles")).scalar_one()


def test_fresh_install_defaults_to_inr_and_is_idempotent(conn):
    migration.up(conn)
    migration.up(conn)
    assert currency(conn) == "INR"
    migration.down(conn)
    assert currency(conn) == "INR"


@pytest.mark.parametrize("table", ["users", "invoices", "buyers", "products", "payments", "company_accounts"])
def test_existing_install_keeps_usd(conn, table):
    conn.execute(text(f"INSERT INTO {table} VALUES (1)"))
    migration.up(conn)
    assert currency(conn) == "USD"


@pytest.mark.parametrize("column,value", [("name", "My shop"), ("address", "1 Main Road"), ("gst", "29ABCDE1234F1Z5"), ("currency_code", "EUR")])
def test_configured_profile_is_not_reset(conn, column, value):
    conn.execute(text(f"UPDATE company_profiles SET {column} = :value"), {"value": value})
    migration.up(conn)
    assert currency(conn) == ("EUR" if column == "currency_code" else "USD")
