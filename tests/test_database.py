"""Real SQLCipher tests with random test keys and disposable data only."""
import secrets
import shutil
import sqlite3
import sys
from pathlib import Path
from uuid import uuid4
import pytest
import sqlcipher3 as sql
from chitlog.core.key_store import load_database_key, KeyStorageError, windows_backend
from chitlog.data.database import Database, DatabaseError
from chitlog.data.migrations import migrate, MIGRATIONS, SchemaError


@pytest.fixture
def db(tmp_path):
    instance = Database(tmp_path / "test.db", secrets.token_bytes(32), tmp_path / "snapshots").open()
    yield instance
    instance.close()


def test_create_reopen_and_schema_history(db):
    assert db.version == len(MIGRATIONS)
    assert db.connection.execute("SELECT count(*) FROM schema_migrations").fetchone()[0] == len(MIGRATIONS)
    db.close()
    db.open()
    assert db.version == len(MIGRATIONS)
    assert db.connection.execute("SELECT count(*) FROM schema_migrations").fetchone()[0] == len(MIGRATIONS)


def test_copied_database_rejects_plain_sqlite_and_wrong_key(db, tmp_path):
    marker = "private-test-marker-" + uuid4().hex
    with db.transaction() as c:
        c.execute("CREATE TABLE test_records(note TEXT NOT NULL)")
        c.execute("INSERT INTO test_records VALUES (?)", (marker,))
    copy = tmp_path / "copied.db"
    shutil.copyfile(db.path, copy)  # idle DELETE journal; no pending writes
    raw = copy.read_bytes()
    assert not raw.startswith(b"SQLite format 3")
    assert marker.encode() not in raw
    plain = sqlite3.connect(f"{copy.as_uri()}?mode=ro", uri=True)
    try:
        with pytest.raises(sqlite3.DatabaseError):
            plain.execute("SELECT * FROM sqlite_master").fetchall()
    finally:
        plain.close()
    with pytest.raises(DatabaseError):
        Database(copy, secrets.token_bytes(32), tmp_path / "backups").open()
    assert copy.read_bytes() == raw
    db.validate()


def test_transaction_rollback_and_parameterized_text(db):
    with db.transaction() as c:
        c.execute("CREATE TABLE test_records(note TEXT NOT NULL)")
    value = "'); DROP TABLE test_records; -- <script>sample</script>"
    with db.transaction() as c:
        c.execute("INSERT INTO test_records VALUES (?)", (value,))
    with pytest.raises(RuntimeError):
        with db.transaction() as c:
            c.execute("INSERT INTO test_records VALUES (?)", ("rollback",))
            raise RuntimeError("test")
    assert db.connection.execute("SELECT note FROM test_records").fetchall() == [(value,)]


def test_foreign_key_and_nested_transaction_rejection(db):
    with db.transaction() as c:
        c.execute("CREATE TABLE parent(id INTEGER PRIMARY KEY)")
        c.execute("CREATE TABLE child(id INTEGER REFERENCES parent(id))")
    with pytest.raises(sql.IntegrityError):
        with db.transaction() as c:
            c.execute("INSERT INTO child VALUES (?)", (99,))
    with db.transaction():
        with pytest.raises(DatabaseError):
            with db.transaction():
                pass
        with pytest.raises(DatabaseError):
            db.snapshot()


def test_snapshot_encrypted_and_reopenable(db):
    with db.transaction() as c:
        c.execute("CREATE TABLE sample(value TEXT)")
        c.execute("INSERT INTO sample VALUES (?)", ("snapshot-marker",))
    snapshot = db.snapshot()
    assert b"snapshot-marker" not in snapshot.read_bytes()
    assert not snapshot.read_bytes().startswith(b"SQLite format 3")
    other = Database(snapshot, db._key, db.backup_dir).open()
    try:
        assert other.connection.execute("SELECT value FROM sample").fetchone() == ("snapshot-marker",)
    finally:
        other.close()


def test_migration_failure_rolls_back_and_retains_snapshot(db):
    next_version = len(MIGRATIONS) + 1
    migrations = MIGRATIONS + ((next_version, "deliberate_failure", (
        "CREATE TABLE should_rollback(id INTEGER)", "THIS IS INVALID SQL"
    )),)
    with pytest.raises(sql.Error):
        migrate(db.connection, db.snapshot, migrations)
    assert db.version == len(MIGRATIONS)
    assert not db.connection.execute("SELECT name FROM sqlite_master WHERE name='should_rollback'").fetchall()
    snapshots = list(db.backup_dir.glob("migration-*.db"))
    assert len(snapshots) == 1
    assert not snapshots[0].read_bytes().startswith(b"SQLite format 3")


def test_successful_migration_is_idempotent(db):
    next_version = len(MIGRATIONS) + 1
    migrations = MIGRATIONS + ((next_version, "test_upgrade", ("CREATE TABLE upgraded(id INTEGER)",)),)
    migrate(db.connection, db.snapshot, migrations)
    migrate(db.connection, db.snapshot, migrations)
    assert db.version == next_version
    assert len(list(db.backup_dir.glob("migration-*.db"))) == 1
    assert db.connection.execute("SELECT count(*) FROM schema_migrations").fetchone()[0] == next_version


def test_backup_failure_prevents_migration(db):
    def fail():
        raise OSError("no space")
    next_version = len(MIGRATIONS) + 1
    with pytest.raises(OSError):
        migrate(db.connection, fail, MIGRATIONS + ((next_version, "upgrade", ("CREATE TABLE extra(id INTEGER)",)),))
    assert db.version == len(MIGRATIONS)
    assert not db.connection.execute("SELECT name FROM sqlite_master WHERE name='extra'").fetchall()


def test_newer_schema_and_inconsistent_history_rejected(db):
    db.connection.execute("PRAGMA user_version=999")
    with pytest.raises(SchemaError):
        migrate(db.connection, db.snapshot)
    db.connection.execute(f"PRAGMA user_version={len(MIGRATIONS)}")
    db.connection.execute("UPDATE schema_migrations SET name='unexpected' WHERE version=?", (len(MIGRATIONS),))
    with pytest.raises(SchemaError):
        migrate(db.connection, db.snapshot)


def test_tampering_rejected_without_reset(db):
    path, key = db.path, db._key
    db.close()
    raw = bytearray(path.read_bytes())
    raw[200] ^= 0xFF
    path.write_bytes(raw)
    with pytest.raises(DatabaseError):
        Database(path, key, db.backup_dir).open()
    assert path.read_bytes() == bytes(raw)


class FakeVault:
    def __init__(self, value=None):
        self.value = value
        self.writes = 0
    def get_password(self, service, account):
        return self.value
    def set_password(self, service, account, value):
        self.value = value
        self.writes += 1


def test_key_created_once_and_missing_key_never_replaced(tmp_path):
    path = tmp_path / "db"
    vault = FakeVault()
    key = load_database_key(path, vault)
    assert len(key) == 32
    assert load_database_key(path, vault) == key
    assert vault.writes == 1
    path.write_bytes(b"existing")
    missing = FakeVault()
    with pytest.raises(KeyStorageError):
        load_database_key(path, missing)
    assert missing.writes == 0 and path.read_bytes() == b"existing"


def test_invalid_key_and_unavailable_vault_fail_closed(tmp_path):
    invalid = FakeVault("not-a-key")
    with pytest.raises(KeyStorageError):
        load_database_key(tmp_path / "db", invalid)
    assert invalid.writes == 0
    class BrokenVault(FakeVault):
        def get_password(self, *args):
            raise OSError("private-provider-message")
    with pytest.raises(KeyStorageError) as error:
        load_database_key(tmp_path / "db", BrokenVault())
    assert "private-provider-message" not in str(error.value)


@pytest.mark.skipif(sys.platform != "win32", reason="Requires real Windows Credential Manager")
def test_windows_vault_roundtrip():
    # Unique disposable credential, never the real ChitLog database key.
    vault = windows_backend()
    service, account = "ChitLog.Tests." + uuid4().hex, "test-key"
    value = secrets.token_hex(32)
    try:
        vault.set_password(service, account, value)
        assert vault.get_password(service, account) == value
    finally:
        if vault.get_password(service, account) is not None:
            vault.delete_password(service, account)


def test_snapshot_name_collision_preserves_existing_file(db, monkeypatch):
    import chitlog.data.database as module
    class FixedId:
        hex = "fixed"
    class FixedTime:
        @staticmethod
        def now(tz):
            return FixedTime()
        def strftime(self, fmt):
            return "fixedtime"
    monkeypatch.setattr(module, "uuid4", lambda: FixedId())
    monkeypatch.setattr(module, "datetime", FixedTime)
    db.backup_dir.mkdir()
    existing = db.backup_dir / "migration-fixedtime-fixed.db"
    existing.write_bytes(b"preserve previous backup")
    with pytest.raises(FileExistsError):
        db.snapshot()
    assert existing.read_bytes() == b"preserve previous backup"
