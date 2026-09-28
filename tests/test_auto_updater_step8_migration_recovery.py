"""Step 8B tests for durable pre-migration recovery snapshots."""
import secrets

import pytest

from chitlog.data.database import Database, DatabaseError
from chitlog.data.migrations import MIGRATIONS, migrate


@pytest.fixture
def database(tmp_path):
    instance = Database(
        tmp_path / "chitlog.db",
        secrets.token_bytes(32),
        tmp_path / "migration-recovery",
    ).open()
    yield instance
    instance.close()


def _next_migration():
    next_version = len(MIGRATIONS) + 1
    return MIGRATIONS + (
        (next_version, "step8b_probe", ("CREATE TABLE step8b_probe(id INTEGER)",)),
    )


def test_snapshot_is_closed_and_reopened_before_acceptance(database, monkeypatch):
    original_connect = database._connect
    snapshot_opens = []

    def traced_connect(path):
        connection = original_connect(path)
        if path != database.path:
            snapshot_opens.append(path)
        return connection

    monkeypatch.setattr(database, "_connect", traced_connect)
    snapshot = database.snapshot()

    assert snapshot_opens == [snapshot, snapshot]


def test_failed_fresh_reopen_blocks_migration_and_removes_bad_snapshot(
    database, monkeypatch
):
    original_connect = database._connect
    non_live_opens = 0

    def fail_fresh_probe(path):
        nonlocal non_live_opens
        if path != database.path:
            non_live_opens += 1
            if non_live_opens == 2:
                raise DatabaseError("test-only persisted snapshot reopen failure")
        return original_connect(path)

    monkeypatch.setattr(database, "_connect", fail_fresh_probe)

    with pytest.raises(
        DatabaseError,
        match="test-only persisted snapshot reopen failure",
    ):
        migrate(database.connection, database.snapshot, _next_migration())

    assert database.version == len(MIGRATIONS)
    assert database.connection.execute(
        "SELECT name FROM sqlite_master WHERE name='step8b_probe'"
    ).fetchall() == []
    assert list(database.backup_dir.glob("migration-*.db")) == []


def test_successful_migration_keeps_verified_pre_migration_copy(database, tmp_path):
    migrate(database.connection, database.snapshot, _next_migration())

    assert database.version == len(MIGRATIONS) + 1
    snapshots = list(database.backup_dir.glob("migration-*.db"))
    assert len(snapshots) == 1

    recovery = Database(
        snapshots[0],
        database._key,
        tmp_path / "recovery-probe-backups",
    ).open()
    try:
        assert recovery.version == len(MIGRATIONS)
        assert recovery.connection.execute(
            "SELECT name FROM sqlite_master WHERE name='step8b_probe'"
        ).fetchall() == []
    finally:
        recovery.close()


def test_no_recovery_copy_when_no_schema_advance_is_needed(database):
    migrate(database.connection, database.snapshot)
    assert database.version == len(MIGRATIONS)
    assert list(database.backup_dir.glob("migration-*.db")) == []
