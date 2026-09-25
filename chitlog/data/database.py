"""SQLCipher connections, transactions, validation, and encrypted snapshots."""
from contextlib import contextmanager
from pathlib import Path
from uuid import uuid4
from datetime import datetime, timezone
import sqlcipher3 as sql
from chitlog.data.migrations import migrate, schema_version


MIGRATION_SNAPSHOT_RETENTION = 5


class DatabaseError(RuntimeError):
    """Safe user-facing database failure."""


class Database:
    def __init__(self, path: Path, key: bytes, backup_dir: Path):
        if not isinstance(key, bytes) or len(key) != 32:
            raise ValueError("A 32-byte random database key is required.")
        self.path = path
        self._key = key
        self.backup_dir = backup_dir
        self.connection = None
        self.cipher_version = ""

    def _connect(self, path: Path):
        connection = sql.connect(str(path), isolation_level=None, timeout=5)
        try:
            version = connection.execute("PRAGMA cipher_version").fetchone()
            if not version or not version[0].startswith("4."):
                raise DatabaseError("A supported SQLCipher 4 engine is required.")
            self.cipher_version = version[0]
            connection.enable_load_extension(False)
            # PRAGMA cannot bind parameters. bytes.hex() produces only hexadecimal;
            # it is a generated key, not user SQL. Never enable SQL trace logging.
            connection.execute('PRAGMA key = "x\'' + self._key.hex() + '\'"')
            connection.execute("PRAGMA cipher_compatibility=4")
            connection.execute("SELECT count(*) FROM sqlite_master").fetchone()
            connection.execute("PRAGMA foreign_keys=ON")
            connection.execute("PRAGMA trusted_schema=OFF")
            connection.execute("PRAGMA temp_store=MEMORY")
            connection.execute("PRAGMA synchronous=FULL")
            if connection.execute("PRAGMA journal_mode=DELETE").fetchone()[0] != "delete":
                raise DatabaseError("The encrypted database journal mode could not be set.")
            if connection.execute("PRAGMA foreign_keys").fetchone()[0] != 1:
                raise DatabaseError("Foreign-key enforcement could not be enabled.")
            return connection
        except BaseException:
            connection.close()
            raise

    def open(self):
        if self.connection is not None:
            raise DatabaseError("The database is already open.")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        try:
            self.connection = self._connect(self.path)
            self.validate()
            migrate(self.connection, self.snapshot)
            self.validate()
            return self
        except Exception:
            self.close()
            raise DatabaseError("The database could not be opened or validated. Its key and existing data were not reset.") from None

    def validate(self):
        c = self.connection
        if c is None:
            raise DatabaseError("The database is not open.")
        if c.execute("PRAGMA cipher_integrity_check").fetchall():
            raise DatabaseError("Encrypted database integrity validation failed.")
        if c.execute("PRAGMA integrity_check").fetchall() != [("ok",)]:
            raise DatabaseError("Database structure validation failed.")
        if c.execute("PRAGMA foreign_key_check").fetchall():
            raise DatabaseError("Database relationships failed validation.")

    @property
    def version(self):
        return schema_version(self.connection)

    @contextmanager
    def transaction(self):
        c = self.connection
        if c is None or c.in_transaction:
            raise DatabaseError("A transaction requires an open, idle connection.")
        c.execute("BEGIN IMMEDIATE")
        try:
            yield c
            c.execute("COMMIT")
        except BaseException:
            if c.in_transaction:
                c.execute("ROLLBACK")
            raise

    def snapshot(self) -> Path:
        """Internal migration recovery copy, encrypted under the same OS-held key.

        Not a portable user backup. Native backup API gives a consistent snapshot.
        Refuse active transactions. Never overwrite an earlier snapshot.
        """
        if self.connection is None or self.connection.in_transaction:
            raise DatabaseError("A snapshot requires an open, idle connection.")
        self.validate()
        self.backup_dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        path = self.backup_dir / f"migration-{stamp}-{uuid4().hex}.db"
        target = None
        created = False
        try:
            with path.open("xb"):
                created = True
            target = self._connect(path)
            self.connection.backup(target)
            if target.execute("PRAGMA cipher_integrity_check").fetchall():
                raise DatabaseError("Migration snapshot failed encryption validation.")
            if target.execute("PRAGMA integrity_check").fetchall() != [("ok",)]:
                raise DatabaseError("Migration snapshot failed structure validation.")
            if target.execute("PRAGMA foreign_key_check").fetchall():
                raise DatabaseError("Migration snapshot failed relationship validation.")
            self._rotate_migration_snapshots()
            return path
        except BaseException:
            if target is not None:
                target.close()
                target = None
            if created:
                path.unlink(missing_ok=True)
            raise
        finally:
            if target is not None:
                target.close()

    def _rotate_migration_snapshots(self) -> None:
        """Keep a bounded set of encrypted pre-migration recovery copies."""
        try:
            snapshots = sorted(
                self.backup_dir.glob("migration-*.db"),
                key=lambda path: (
                    path.stat().st_mtime_ns,
                    path.name,
                ),
                reverse=True,
            )
        except OSError:
            return

        for old in snapshots[MIGRATION_SNAPSHOT_RETENTION:]:
            try:
                old.unlink()
            except OSError:
                # Retention cleanup is best-effort. A locked historical
                # snapshot must never cause the active database migration to
                # fail after a valid new safety snapshot was created.
                pass

    @staticmethod
    def _validate_connection(connection) -> None:
        if connection.execute("PRAGMA cipher_integrity_check").fetchall():
            raise DatabaseError("Encrypted database integrity validation failed.")
        if connection.execute("PRAGMA integrity_check").fetchall() != [("ok",)]:
            raise DatabaseError("Database structure validation failed.")
        if connection.execute("PRAGMA foreign_key_check").fetchall():
            raise DatabaseError("Database relationships failed validation.")

    def _connect_with_key(self, path: Path, key: bytes):
        """Open one SQLCipher database with an explicit raw 32-byte key."""
        if not isinstance(key, bytes) or len(key) != 32:
            raise ValueError("A 32-byte database key is required.")
        connection = sql.connect(str(path), isolation_level=None, timeout=5)
        try:
            version = connection.execute("PRAGMA cipher_version").fetchone()
            if not version or not version[0].startswith("4."):
                raise DatabaseError("A supported SQLCipher 4 engine is required.")
            connection.enable_load_extension(False)
            connection.execute('PRAGMA key = "x\'' + key.hex() + '\'"')
            connection.execute("PRAGMA cipher_compatibility=4")
            connection.execute("SELECT count(*) FROM sqlite_master").fetchone()
            connection.execute("PRAGMA foreign_keys=ON")
            connection.execute("PRAGMA trusted_schema=OFF")
            connection.execute("PRAGMA temp_store=MEMORY")
            connection.execute("PRAGMA synchronous=FULL")
            if connection.execute("PRAGMA journal_mode=DELETE").fetchone()[0] != "delete":
                raise DatabaseError("The encrypted database journal mode could not be set.")
            return connection
        except BaseException:
            connection.close()
            raise

    @staticmethod
    def _quoted_path(path: Path) -> str:
        # SQL parameters are not supported for SQLCipher ATTACH KEY syntax.
        # The path is generated/selected locally; escape SQLite string quotes.
        return str(path.resolve()).replace("'", "''")

    def _export_connection(self, source_connection, path: Path, key: bytes) -> Path:
        """Export decrypted source data into a newly encrypted SQLCipher DB.

        SQLCipher documents sqlcipher_export() for copying databases when the
        destination uses a different key. A plain sqlite3_backup() connection
        copy is intentionally not used here because its page/salt behavior can
        produce a file that validates only until the destination connection is
        closed, then fails HMAC validation on the next process start.
        """
        if source_connection.in_transaction:
            raise DatabaseError("Encrypted export requires an idle source database.")
        if not isinstance(key, bytes) or len(key) != 32:
            raise ValueError("A 32-byte database key is required.")
        if path.exists():
            raise DatabaseError("The export destination already exists.")
        path.parent.mkdir(parents=True, exist_ok=True)

        alias = "chitlog_export"
        quoted = self._quoted_path(path)
        attached = False
        try:
            source_connection.execute(
                f'ATTACH DATABASE \'{quoted}\' AS {alias} KEY "x\'{key.hex()}\'"'
            )
            attached = True
            source_connection.execute(f"PRAGMA {alias}.cipher_compatibility=4")
            source_connection.execute(f"SELECT sqlcipher_export('{alias}')")

            # sqlcipher_export copies schema/data; explicitly preserve these
            # file-header application values as well.
            app_id = int(
                source_connection.execute("PRAGMA application_id").fetchone()[0]
            )
            user_version = int(
                source_connection.execute("PRAGMA user_version").fetchone()[0]
            )
            source_connection.execute(f"PRAGMA {alias}.application_id={app_id}")
            source_connection.execute(f"PRAGMA {alias}.user_version={user_version}")
        except BaseException:
            path.unlink(missing_ok=True)
            raise
        finally:
            if attached:
                try:
                    source_connection.execute(f"DETACH DATABASE {alias}")
                except Exception:
                    path.unlink(missing_ok=True)
                    raise

        # Critical durability check: do not trust the connection used during
        # export. Close/detach happened above; now open a brand-new connection
        # exactly as the next ChitLog process will.
        probe = None
        try:
            probe = self._connect_with_key(path, key)
            self._validate_connection(probe)
        except BaseException:
            path.unlink(missing_ok=True)
            raise
        finally:
            if probe is not None:
                probe.close()
        return path

    def encrypted_copy(self, path: Path, *, key: bytes | None = None) -> Path:
        """Create a durable encrypted copy, optionally under another key."""
        if self.connection is None or self.connection.in_transaction:
            raise DatabaseError("A backup copy requires an open, idle database.")
        target_key = self._key if key is None else key
        return self._export_connection(self.connection, path, target_key)

    def copy_connection_to_current_key(self, source_connection, path: Path) -> Path:
        """Re-encrypt a validated external database under this install's key."""
        if self.connection is None or self.connection.in_transaction:
            raise DatabaseError("Restore staging requires an open, idle database.")
        return self._export_connection(source_connection, path, self._key)

    def close(self):
        if self.connection is not None:
            self.connection.close()
            self.connection = None
