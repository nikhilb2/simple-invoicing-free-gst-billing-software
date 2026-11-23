"""Exercise actual pg_dump/pg_restore/psql against a disposable database."""

import io
import shutil
import uuid
from pathlib import Path

import pytest
from fastapi import HTTPException, UploadFile
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url

from src.core.config import settings
from src.db.base import Base
from src.services import backup


pytestmark = pytest.mark.skipif(
    not settings.DATABASE_URL.startswith("postgres")
    or any(shutil.which(tool) is None for tool in ("pg_dump", "pg_restore", "psql")),
    reason="backup integration tests need PostgreSQL and its client tools",
)
NEW_MIGRATION = "20261120000001_create_product_bulk_updates"


@pytest.fixture
def backup_db(monkeypatch, tmp_path):
    # restore_backup terminates connections to its database: never point it at
    # the suite's database, which may also contain another test's schemas.
    url = make_url(settings.DATABASE_URL)
    name = "backup_restore_test_" + uuid.uuid4().hex
    admin = create_engine(url, isolation_level="AUTOCOMMIT")
    db = create_engine(url.set(database=name))
    with admin.connect() as conn:
        conn.execute(text(f'CREATE DATABASE "{name}"'))
    monkeypatch.setattr(backup, "engine", db)
    monkeypatch.setattr(backup, "app_engine", db)
    monkeypatch.setattr(backup, "BACKUP_DIR", tmp_path)
    monkeypatch.setattr(settings, "DEPLOYMENT_MODE", "single_tenant")
    try:
        Base.metadata.create_all(db)
        backup._apply_pending_migrations()
        yield db
    finally:
        db.dispose()
        with admin.connect() as conn:
            conn.execute(text(f'DROP DATABASE "{name}" WITH (FORCE)'))
        admin.dispose()


def upload(path):
    return UploadFile(filename=path.name, file=io.BytesIO(path.read_bytes()))


def archive():
    item = backup.create_backup_archive()
    return Path(backup.BACKUP_DIR) / item["file_name"]


def old_archive(db):
    with db.begin() as conn:
        conn.execute(text("DROP TABLE product_bulk_updates"))
        conn.execute(text("DELETE FROM _migrations WHERE name = :name"), {"name": NEW_MIGRATION})
        conn.execute(text("UPDATE company_profiles SET name = 'In the backup'"))
    path = archive()
    assert backup._apply_pending_migrations() == 1
    with db.begin() as conn:
        conn.execute(text("UPDATE company_profiles SET name = 'After the backup'"))
        conn.execute(text("""
            INSERT INTO product_bulk_updates (id, company_id, changes)
            SELECT 'new-update', id, '{}' FROM company_profiles LIMIT 1
        """))
    return path


def test_older_backup_restores_and_recreates_new_table(backup_db):
    path = old_archive(backup_db)
    with backup_db.begin() as conn:
        schema_before = conn.execute(text("SELECT oid, nspacl FROM pg_namespace WHERE nspname = 'public'")).one()
        conn.execute(text("CREATE TABLE operator_notes (note TEXT)"))
        conn.execute(text("INSERT INTO operator_notes VALUES ('keep me')"))

    preflight = backup.preflight_restore(upload(path))
    assert preflight.compatibility == "requires_migration"
    assert preflight.migration_gap_count == 1
    assert backup.restore_backup(upload(path)) == ("requires_migration", 1)

    with backup_db.connect() as conn:
        assert conn.execute(text("SELECT name FROM company_profiles")).scalar_one() == "In the backup"
        assert conn.execute(text("SELECT count(*) FROM product_bulk_updates")).scalar_one() == 0
        assert conn.execute(text("SELECT count(*) FROM pg_constraint WHERE conrelid = 'product_bulk_updates'::regclass AND contype = 'f'")).scalar_one() == 2
        assert conn.execute(text("SELECT note FROM operator_notes")).scalar_one() == "keep me"
        assert conn.execute(text("SELECT oid, nspacl FROM pg_namespace WHERE nspname = 'public'")).one() == schema_before
    assert NEW_MIGRATION in backup.get_applied_migrations()


def test_same_version_backup_still_restores(backup_db):
    with backup_db.begin() as conn:
        conn.execute(text("UPDATE company_profiles SET name = 'In the backup'"))
    path = archive()
    with backup_db.begin() as conn:
        conn.execute(text("UPDATE company_profiles SET name = 'After the backup'"))
    assert backup.restore_backup(upload(path)) == ("exact", 0)
    with backup_db.connect() as conn:
        assert conn.execute(text("SELECT name FROM company_profiles")).scalar_one() == "In the backup"


def test_restore_error_rolls_back_table_cleanup_and_data(backup_db, monkeypatch):
    path = old_archive(backup_db)
    run = backup.subprocess.run

    def inject_sql_error(command, *args, **kwargs):
        result = run(command, *args, **kwargs)
        if command[0] == "pg_restore" and "-f" in command:
            result.stdout += "\nSELECT missing_function_to_fail_restore();\n"
        return result

    monkeypatch.setattr(backup.subprocess, "run", inject_sql_error)
    with pytest.raises(HTTPException, match="Restore failed"):
        backup.restore_backup(upload(path))

    with backup_db.connect() as conn:
        assert conn.execute(text("SELECT name FROM company_profiles")).scalar_one() == "After the backup"
        assert conn.execute(text("SELECT id FROM product_bulk_updates")).scalar_one() == "new-update"
    assert NEW_MIGRATION in backup.get_applied_migrations()
