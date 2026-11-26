"""Exercise actual pg_dump/pg_restore/psql against a disposable database."""

import io
import shutil
import uuid
from pathlib import Path

import pytest
from fastapi import HTTPException, UploadFile
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import OperationalError

from src.core.config import settings
from src.db.base import Base
from src.services import backup
from src.services import backup_scheduler


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


def pre_restore_backups():
    return sorted(Path(backup.BACKUP_DIR).glob(f"{backup.PRE_RESTORE_BACKUP_PREFIX}*"))


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
    assert pre_restore_backups() == []


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
    assert pre_restore_backups() == []

    with backup_db.connect() as conn:
        assert conn.execute(text("SELECT name FROM company_profiles")).scalar_one() == "After the backup"
        assert conn.execute(text("SELECT id FROM product_bulk_updates")).scalar_one() == "new-update"
    assert NEW_MIGRATION in backup.get_applied_migrations()


FAILING_MIGRATION = "20991231000001_fails_on_backup_data"


def add_migration_that_fails_on_backup_data(monkeypatch, tmp_path):
    """Apply one more migration that the current data passes and the backup's data does not."""
    migrations = tmp_path / "migrations"
    migrations.mkdir()
    for path in backup.MIGRATIONS_DIR.glob("*.py"):
        (migrations / path.name).symlink_to(path)
    (migrations / f"{FAILING_MIGRATION}.py").write_text(
        "from sqlalchemy import text\n\n"
        "def up(conn):\n"
        "    conn.execute(text(\"SELECT 1 / (CASE WHEN name = 'In the backup' THEN 0 ELSE 1 END) FROM company_profiles\"))\n"
    )
    monkeypatch.setattr(backup, "MIGRATIONS_DIR", migrations)
    assert backup._apply_pending_migrations() == 1


def assert_database_as_before_restore(db):
    with db.connect() as conn:
        assert conn.execute(text("SELECT name FROM company_profiles")).scalar_one() == "After the backup"
        assert conn.execute(text("SELECT id FROM product_bulk_updates")).scalar_one() == "new-update"
    applied = backup.get_applied_migrations()
    assert NEW_MIGRATION in applied
    assert FAILING_MIGRATION in applied


def test_failed_migration_after_restore_rolls_back_and_names_it(backup_db, monkeypatch, tmp_path):
    path = old_archive(backup_db)
    add_migration_that_fails_on_backup_data(monkeypatch, tmp_path)

    with pytest.raises(HTTPException) as failure:
        backup.restore_backup(upload(path))

    assert failure.value.status_code == 500
    assert "rolled back" in failure.value.detail
    assert f"migration {FAILING_MIGRATION} failed: division by zero" in failure.value.detail
    assert_database_as_before_restore(backup_db)
    assert pre_restore_backups() == []


def test_failed_rollback_after_failed_migration_is_reported(backup_db, monkeypatch, tmp_path):
    path = old_archive(backup_db)
    add_migration_that_fails_on_backup_data(monkeypatch, tmp_path)
    drops = backup._app_table_drops
    # Only the rollback drops every app table; make that step fail.
    monkeypatch.setattr(
        backup,
        "_app_table_drops",
        lambda keep: drops(keep) if keep else "SELECT missing_function_to_fail_rollback();\n",
    )

    with pytest.raises(HTTPException) as failure:
        backup.restore_backup(upload(path))

    assert f"migration {FAILING_MIGRATION} failed" in failure.value.detail
    assert "also failed" in failure.value.detail
    with backup_db.connect() as conn:
        assert conn.execute(text("SELECT name FROM company_profiles")).scalar_one() == "In the backup"

    # The data from before the restore survives as an ordinary backup (#1079).
    [kept] = pre_restore_backups()
    assert f"saved as the backup {kept.name} on the Backups page" in failure.value.detail
    assert kept.name in [item["file_name"] for item in backup.list_backups()]
    assert backup.get_backup_file_path(kept.name) == kept
    monkeypatch.setattr(backup_scheduler, "BACKUP_DIR", backup.BACKUP_DIR)
    for stamp in ("20000101_000000", "20000102_000000"):
        (Path(backup.BACKUP_DIR) / f"{backup.AUTO_BACKUP_PREFIX}{stamp}.enc").write_bytes(b"old")
    assert backup_scheduler.prune_auto_backups(keep=1) == [f"{backup.AUTO_BACKUP_PREFIX}20000101_000000.enc"]
    assert kept.exists()

    # ...and restoring it from the Backups page puts that data back, although the
    # database is now behind the app's schema.
    monkeypatch.setattr(backup, "_app_table_drops", drops)
    assert backup.preflight_restore(upload(kept)).compatibility == "database_behind"
    assert backup.restore_backup(upload(kept)) == ("database_behind", 0)
    assert_database_as_before_restore(backup_db)


def test_error_outside_a_migration_after_restore_also_rolls_back(backup_db, monkeypatch):
    path = old_archive(backup_db)

    def lose_connection():
        raise OperationalError("SELECT 1", {}, Exception("server closed the connection unexpectedly"))

    monkeypatch.setattr(backup, "_apply_pending_migrations", lose_connection)

    with pytest.raises(HTTPException) as failure:
        backup.restore_backup(upload(path))

    assert failure.value.status_code == 500
    assert "rolled back" in failure.value.detail
    assert "running the pending migrations failed: server closed the connection unexpectedly" in failure.value.detail
    with backup_db.connect() as conn:
        assert conn.execute(text("SELECT name FROM company_profiles")).scalar_one() == "After the backup"
        assert conn.execute(text("SELECT id FROM product_bulk_updates")).scalar_one() == "new-update"
    assert NEW_MIGRATION in backup.get_applied_migrations()


def fail_pg_dump(output_path):
    raise HTTPException(status_code=500, detail="pg_dump failed: disk full")


def test_failed_snapshot_cancels_older_backup_restore(backup_db, monkeypatch):
    path = old_archive(backup_db)
    monkeypatch.setattr(backup, "_run_pg_dump", fail_pg_dump)

    with pytest.raises(HTTPException) as failure:
        backup.restore_backup(upload(path))

    assert failure.value.status_code == 500
    assert "Restore cancelled, nothing was changed" in failure.value.detail
    assert "pg_dump failed: disk full" in failure.value.detail
    with backup_db.connect() as conn:
        assert conn.execute(text("SELECT name FROM company_profiles")).scalar_one() == "After the backup"
        assert conn.execute(text("SELECT id FROM product_bulk_updates")).scalar_one() == "new-update"
    assert NEW_MIGRATION in backup.get_applied_migrations()


def test_same_version_restore_takes_no_snapshot(backup_db, monkeypatch):
    with backup_db.begin() as conn:
        conn.execute(text("UPDATE company_profiles SET name = 'In the backup'"))
    path = archive()
    monkeypatch.setattr(backup, "_run_pg_dump", fail_pg_dump)

    assert backup.restore_backup(upload(path)) == ("exact", 0)
    with backup_db.connect() as conn:
        assert conn.execute(text("SELECT name FROM company_profiles")).scalar_one() == "In the backup"
