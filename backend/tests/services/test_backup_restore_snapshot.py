"""What happens to the pre-restore snapshot of an older-backup restore (#1079).

Nothing here shells out to pg_dump, pg_restore or psql: those steps are patched,
so this runs without the PostgreSQL client tools. The same paths against a real
database are in tests/db/test_backup_restore_postgres.py.
"""

import io
from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory

import pytest
from fastapi import HTTPException, UploadFile

from src.services import backup, backup_scheduler

OLD = ["20260101000001_a"]
CURRENT = ["20260101000001_a", "20260101000002_b"]


@pytest.fixture
def restore(monkeypatch, tmp_path):
    """restore_backup of a backup one migration behind; returns the _apply_dump calls."""
    monkeypatch.setattr(backup, "BACKUP_DIR", tmp_path)
    monkeypatch.setattr(backup_scheduler, "BACKUP_DIR", tmp_path)

    def prepare(upload):
        temp_dir = TemporaryDirectory()
        dump_path = Path(temp_dir.name) / "database.dump"
        dump_path.write_bytes(b"backup dump")
        manifest = backup.BackupManifest(datetime.now(timezone.utc), "0.1.0", OLD, OLD[-1])
        return backup._PreparedBackup(temp_dir, dump_path, manifest)

    calls = []
    monkeypatch.setattr(backup, "_prepare_uploaded_backup", prepare)
    monkeypatch.setattr(backup, "_probe_dump", lambda path: "")
    monkeypatch.setattr(backup, "get_applied_migrations", lambda: list(CURRENT))
    monkeypatch.setattr(backup, "_db_parts", lambda: {"password": None})
    monkeypatch.setattr(backup, "_dispose_engines", lambda: None)
    monkeypatch.setattr(backup, "_terminate_other_db_sessions", lambda env: None)
    monkeypatch.setattr(backup, "_run_pg_dump", lambda path: path.write_bytes(b"current dump"))
    monkeypatch.setattr(backup, "_post_backup_table_drops", lambda toc: "")
    monkeypatch.setattr(backup, "_app_table_drops", lambda keep: "")
    monkeypatch.setattr(backup, "_apply_pending_migrations", lambda: 1)
    monkeypatch.setattr(backup, "_apply_dump", lambda path, env, prefix="": calls.append(path.read_bytes()))
    return calls


def run_restore():
    return backup.restore_backup(UploadFile(filename="old.enc", file=io.BytesIO(b"")))


def pre_restore_backups(directory):
    return sorted(path.name for path in Path(directory).glob(f"{backup.PRE_RESTORE_BACKUP_PREFIX}*"))


def fail_migration():
    raise backup.MigrationFailed("migration 20260101000002_b", ValueError("division by zero"))


def test_snapshot_is_removed_after_a_successful_restore(restore, tmp_path):
    assert run_restore() == ("requires_migration", 1)
    assert restore == [b"backup dump"]
    assert pre_restore_backups(tmp_path) == []


def test_snapshot_is_removed_after_a_successful_rollback(restore, monkeypatch, tmp_path):
    monkeypatch.setattr(backup, "_apply_pending_migrations", fail_migration)

    with pytest.raises(HTTPException, match="rolled back, your data is unchanged"):
        run_restore()

    assert restore == [b"backup dump", b"current dump"]
    assert pre_restore_backups(tmp_path) == []


def test_snapshot_is_kept_and_named_when_the_rollback_fails_too(restore, monkeypatch, tmp_path):
    monkeypatch.setattr(backup, "_apply_pending_migrations", fail_migration)

    def apply_dump(path, env, prefix=""):
        restore.append(path.read_bytes())
        if len(restore) == 2:
            raise HTTPException(status_code=500, detail="Restore failed: connection lost")

    monkeypatch.setattr(backup, "_apply_dump", apply_dump)

    with pytest.raises(HTTPException) as failure:
        run_restore()

    [kept] = pre_restore_backups(tmp_path)
    assert failure.value.status_code == 500
    assert "also failed (Restore failed: connection lost)" in failure.value.detail
    assert f"saved as the backup {kept} on the Backups page" in failure.value.detail
    # An ordinary encrypted backup of the data before the restore: it lists,
    # downloads and restores like any other, and retention never deletes it.
    assert kept.endswith(".enc")
    assert backup.get_backup_file_path(kept) == tmp_path / kept
    assert [item["migration_head"] for item in backup.list_backups()] == [CURRENT[-1]]
    (tmp_path / f"{backup.AUTO_BACKUP_PREFIX}20000101_000000.enc").write_bytes(b"old")
    assert backup_scheduler.prune_auto_backups(keep=1) == []
    assert pre_restore_backups(tmp_path) == [kept]


def test_failed_restore_before_the_migrations_removes_the_snapshot(restore, monkeypatch, tmp_path):
    def apply_dump(path, env, prefix=""):
        raise HTTPException(status_code=500, detail="Restore failed: syntax error")

    monkeypatch.setattr(backup, "_apply_dump", apply_dump)

    with pytest.raises(HTTPException, match="syntax error"):
        run_restore()

    assert pre_restore_backups(tmp_path) == []


def test_backup_at_the_apps_schema_restores_onto_a_database_left_behind(monkeypatch, tmp_path):
    migrations = tmp_path / "migrations"
    migrations.mkdir()
    for name in CURRENT:
        (migrations / f"{name}.py").write_text("")
    monkeypatch.setattr(backup, "MIGRATIONS_DIR", migrations)

    assert backup._classify_compatibility(CURRENT, OLD)[0] == "database_behind"
    assert backup._classify_compatibility(CURRENT + ["20991231000001_from_a_newer_app"], OLD)[0] == "newer_than_app"
