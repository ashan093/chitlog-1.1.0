"""Step 18 portable encrypted DATA-only backup and selective restore."""
from __future__ import annotations

import base64
import hashlib
import json
import os
from pathlib import Path
import secrets
import shutil
import struct
from datetime import datetime, timezone
from uuid import uuid4

import sqlcipher3 as sql

from chitlog.data.database import Database
from chitlog.data.migrations import APP_ID, MIGRATIONS


MAGIC = b"CHITLOG-DATA-BACKUP\x00"
FORMAT_VERSION = 2
MAX_HEADER_BYTES = 8192
MAX_BACKUP_BYTES = 256 * 1024 * 1024
SALT_BYTES = 16
PASSWORD_MIN_LENGTH = 12
SAFETY_RETENTION = 5
META_TABLE = "chitlog_data_backup_meta"

# Current ChitLog V1 business-data tables only.
# These are the only tables allowed into a portable data backup.
DATA_TABLES = (
    "categories",
    "transactions",
    "dismissed_recent_items",
    "budgets",
    "budget_carry_forward",
    "liabilities",
    "liability_payments",
    "workers",
    "worker_work_records",
    "worker_attendance",
    "worker_payments",
    "worker_payroll_carry_forward",
)

# Portable data backups must never contain any row or schema from these tables.
PROTECTED_TABLES = (
    "schema_migrations",
    "application_settings",
    "auth_profile",
    "security_questions",
)


class BackupError(RuntimeError):
    """Base class for safe user-facing backup failures."""


class BackupValidationError(BackupError):
    """The backup is invalid, corrupted, unsupported, or unauthorized."""


class BackupPasswordError(BackupValidationError):
    """The supplied backup password is wrong or the encrypted payload is unreadable."""


class RestoreError(BackupError):
    """Data restore could not complete safely."""


def _quote_identifier(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


def _derive_backup_key(password: str, salt: bytes) -> bytes:
    if not isinstance(password, str) or len(password) < PASSWORD_MIN_LENGTH:
        raise BackupError(
            f"Backup password must contain at least {PASSWORD_MIN_LENGTH} characters."
        )
    if len(password) > 256:
        raise BackupError("Backup password is too long.")
    try:
        return hashlib.scrypt(
            password.encode("utf-8"),
            salt=salt,
            n=2**15,
            r=8,
            p=1,
            dklen=32,
            maxmem=64 * 1024 * 1024,
        )
    except (ValueError, MemoryError):
        raise BackupError("The backup encryption key could not be created.") from None


def _open_sqlcipher(path: Path, key: bytes):
    connection = sql.connect(str(path), isolation_level=None, timeout=5)
    try:
        version = connection.execute("PRAGMA cipher_version").fetchone()
        if not version or not version[0].startswith("4."):
            raise BackupValidationError("A supported SQLCipher 4 engine is required.")
        connection.enable_load_extension(False)
        connection.execute("PRAGMA key = \"x'" + key.hex() + "'\"")
        connection.execute("PRAGMA cipher_compatibility=4")
        connection.execute("SELECT count(*) FROM sqlite_master").fetchone()
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute("PRAGMA trusted_schema=OFF")
        connection.execute("PRAGMA temp_store=MEMORY")
        connection.execute("PRAGMA journal_mode=DELETE")
        return connection
    except BaseException:
        connection.close()
        raise


class BackupService:
    """Create encrypted business-data backups without credentials or app settings."""

    def __init__(self, database: Database, local_backup_dir: Path):
        self.database = database
        self.local_backup_dir = Path(local_backup_dir)
        self.safety_dir = self.local_backup_dir / "restore-safety"
        self.local_backup_dir.mkdir(parents=True, exist_ok=True)
        self.safety_dir.mkdir(parents=True, exist_ok=True)

    @property
    def extension(self) -> str:
        return ".chitdata"

    def suggested_filename(self) -> str:
        stamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        return f"ChitLog-Data-{stamp}{self.extension}"

    @staticmethod
    def _user_tables(connection) -> set[str]:
        return {
            str(row[0])
            for row in connection.execute(
                "SELECT name FROM sqlite_master "
                "WHERE type='table' AND name NOT LIKE 'sqlite_%'"
            ).fetchall()
        }

    @staticmethod
    def _table_sql(connection, table: str) -> str:
        row = connection.execute(
            "SELECT sql FROM sqlite_master WHERE type='table' AND name=?",
            (table,),
        ).fetchone()
        if not row or not row[0]:
            raise BackupValidationError(f"Required data table is missing: {table}.")
        return str(row[0])

    @staticmethod
    def _table_columns(connection, table: str) -> list[str]:
        rows = connection.execute(
            f"PRAGMA table_info({_quote_identifier(table)})"
        ).fetchall()
        if not rows:
            raise BackupValidationError(f"Required data table is invalid: {table}.")
        return [str(row[1]) for row in rows]

    def _validate_live_data_schema(self) -> int:
        if self.database.connection is None:
            raise BackupError("The ChitLog database is not open.")

        version = int(
            self.database.connection.execute("PRAGMA user_version").fetchone()[0]
        )
        current_version = len(MIGRATIONS)
        if version != current_version:
            raise BackupError(
                "Data backup requires the current ChitLog database version."
            )

        tables = self._user_tables(self.database.connection)
        missing = [table for table in DATA_TABLES if table not in tables]
        if missing:
            raise BackupError(
                "Data backup cannot continue because required data tables are missing."
            )

        # The protected tables are intentionally verified here so backup creation
        # cannot silently proceed against an unexpected/partial ChitLog schema.
        protected_missing = [table for table in PROTECTED_TABLES if table not in tables]
        if protected_missing:
            raise BackupError(
                "Data backup cannot continue because the ChitLog system schema is incomplete."
            )
        return version

    def _create_data_payload(self, path: Path, key: bytes) -> int:
        """Build a fresh SQLCipher database containing ONLY DATA_TABLES.

        We deliberately do not clone the whole ChitLog database and then delete
        credentials. The portable file is created from an empty encrypted DB so
        auth_profile, security_questions, application_settings and migration
        rows never enter the portable payload at all.
        """
        schema_version = self._validate_live_data_schema()
        if path.exists():
            raise BackupError("The temporary backup destination already exists.")

        destination = None
        try:
            destination = _open_sqlcipher(path, key)
            destination.execute("PRAGMA foreign_keys=OFF")
            destination.execute("BEGIN IMMEDIATE")
            try:
                destination.execute(
                    "CREATE TABLE chitlog_data_backup_meta ("
                    "key TEXT PRIMARY KEY, value TEXT NOT NULL)"
                )

                for table in DATA_TABLES:
                    create_sql = self._table_sql(self.database.connection, table)
                    destination.execute(create_sql)

                now = datetime.now(timezone.utc).isoformat()
                metadata = (
                    ("format", "ChitLogDataBackup"),
                    ("format_version", str(FORMAT_VERSION)),
                    ("schema_version", str(schema_version)),
                    ("created_utc", now),
                    ("contains_credentials", "false"),
                    ("contains_system_settings", "false"),
                )
                destination.executemany(
                    f"INSERT INTO {_quote_identifier(META_TABLE)}(key,value) "
                    "VALUES (?,?)",
                    metadata,
                )

                for table in DATA_TABLES:
                    columns = self._table_columns(self.database.connection, table)
                    column_sql = ",".join(_quote_identifier(column) for column in columns)
                    placeholders = ",".join("?" for _ in columns)
                    source = self.database.connection.execute(
                        f"SELECT {column_sql} FROM {_quote_identifier(table)}"
                    )
                    insert_sql = (
                        f"INSERT INTO {_quote_identifier(table)}({column_sql}) "
                        f"VALUES ({placeholders})"
                    )
                    while True:
                        rows = source.fetchmany(500)
                        if not rows:
                            break
                        destination.executemany(insert_sql, rows)

                destination.execute(f"PRAGMA application_id={APP_ID}")
                destination.execute(f"PRAGMA user_version={schema_version}")
                destination.execute("COMMIT")
            except BaseException:
                if destination.in_transaction:
                    destination.execute("ROLLBACK")
                raise
            finally:
                destination.execute("PRAGMA foreign_keys=ON")

            if destination.execute("PRAGMA foreign_key_check").fetchall():
                raise BackupError("The data backup contains invalid relationships.")
            if destination.execute("PRAGMA integrity_check").fetchall() != [("ok",)]:
                raise BackupError("The data backup failed its database integrity check.")
        except BackupError:
            path.unlink(missing_ok=True)
            raise
        except Exception:
            path.unlink(missing_ok=True)
            raise BackupError("The encrypted data backup could not be created safely.") from None
        finally:
            if destination is not None:
                destination.close()

        # Durability/password check using a brand-new connection.
        probe = None
        try:
            probe = _open_sqlcipher(path, key)
            self._validate_data_payload(probe)
        except BackupError:
            path.unlink(missing_ok=True)
            raise
        except Exception:
            path.unlink(missing_ok=True)
            raise BackupError("The encrypted data backup could not be reopened safely.") from None
        finally:
            if probe is not None:
                probe.close()

        return schema_version

    def _validate_data_payload(self, connection) -> int:
        try:
            if connection.execute("PRAGMA cipher_integrity_check").fetchall():
                raise BackupValidationError("Backup encryption integrity check failed.")
            if connection.execute("PRAGMA integrity_check").fetchall() != [("ok",)]:
                raise BackupValidationError("Backup database integrity check failed.")
            if connection.execute("PRAGMA foreign_key_check").fetchall():
                raise BackupValidationError("Backup relationships failed validation.")

            app_id = int(connection.execute("PRAGMA application_id").fetchone()[0])
            if app_id != APP_ID:
                raise BackupValidationError("This is not a recognized ChitLog data backup.")

            version = int(connection.execute("PRAGMA user_version").fetchone()[0])
            if version != len(MIGRATIONS):
                raise BackupValidationError(
                    "This data backup was created by a different ChitLog database version."
                )

            tables = self._user_tables(connection)
            expected_tables = set(DATA_TABLES) | {META_TABLE}
            if tables != expected_tables:
                raise BackupValidationError(
                    "The data backup contains unexpected or missing database tables."
                )

            # Strong guarantee: protected ChitLog system/auth tables are not even
            # present in a portable data backup.
            if any(table in tables for table in PROTECTED_TABLES):
                raise BackupValidationError(
                    "The data backup unexpectedly contains protected system data."
                )

            meta = dict(
                connection.execute(
                    f"SELECT key,value FROM {_quote_identifier(META_TABLE)}"
                ).fetchall()
            )
            if (
                meta.get("format") != "ChitLogDataBackup"
                or meta.get("format_version") != str(FORMAT_VERSION)
                or meta.get("schema_version") != str(version)
                or meta.get("contains_credentials") != "false"
                or meta.get("contains_system_settings") != "false"
            ):
                raise BackupValidationError("The data backup metadata is invalid.")

            # Restore is deliberately current-version-only. Compare every
            # business table definition with the running application's schema.
            for table in DATA_TABLES:
                if self._table_sql(connection, table) != self._table_sql(
                    self.database.connection, table
                ):
                    raise BackupValidationError(
                        "The data backup structure does not match this ChitLog version."
                    )
            return version
        except BackupValidationError:
            raise
        except Exception:
            raise BackupPasswordError(
                "The backup password is incorrect or the data backup is unreadable."
            ) from None

    @staticmethod
    def _hash_file(path: Path) -> str:
        digest = hashlib.sha256()
        with path.open("rb") as handle:
            while True:
                chunk = handle.read(1024 * 1024)
                if not chunk:
                    break
                digest.update(chunk)
        return digest.hexdigest()

    def create_backup(self, destination: Path, password: str) -> Path:
        destination = Path(destination)
        if destination.suffix.lower() != self.extension:
            raise BackupError(f"Data backup filename must end with {self.extension}.")
        if destination.exists():
            raise BackupError("That data backup already exists. Choose a new filename.")
        destination.parent.mkdir(parents=True, exist_ok=True)

        self.database.validate()
        salt = secrets.token_bytes(SALT_BYTES)
        backup_key = _derive_backup_key(password, salt)

        temp_db = self.local_backup_dir / f".data-backup-stage-{uuid4().hex}.db"
        part = destination.with_name(destination.name + f".part-{uuid4().hex}")
        try:
            schema_version = self._create_data_payload(temp_db, backup_key)
            payload_size = temp_db.stat().st_size
            if payload_size <= 0 or payload_size > MAX_BACKUP_BYTES:
                raise BackupError("The encrypted data backup size is outside the allowed limit.")

            header = {
                "format": "ChitLogDataBackup",
                "version": FORMAT_VERSION,
                "created_utc": datetime.now(timezone.utc).isoformat(),
                "schema_version": schema_version,
                "salt": base64.b64encode(salt).decode("ascii"),
                "kdf": "scrypt-n32768-r8-p1",
                "payload_bytes": payload_size,
                "payload_sha256": self._hash_file(temp_db),
                "data_tables": list(DATA_TABLES),
                "contains_credentials": False,
                "contains_system_settings": False,
            }
            header_bytes = json.dumps(
                header, sort_keys=True, separators=(",", ":")
            ).encode("utf-8")
            if len(header_bytes) > MAX_HEADER_BYTES:
                raise BackupError("Data backup metadata is unexpectedly large.")

            with part.open("xb") as output, temp_db.open("rb") as payload:
                output.write(MAGIC)
                output.write(struct.pack(">I", len(header_bytes)))
                output.write(header_bytes)
                shutil.copyfileobj(payload, output, length=1024 * 1024)
                output.flush()
                os.fsync(output.fileno())

            if part.stat().st_size > MAX_BACKUP_BYTES + MAX_HEADER_BYTES + 1024:
                raise BackupError("The encrypted data backup exceeds the allowed size.")
            os.replace(part, destination)
            return destination
        except BackupError:
            raise
        except Exception:
            raise BackupError("The encrypted data backup could not be created safely.") from None
        finally:
            temp_db.unlink(missing_ok=True)
            part.unlink(missing_ok=True)

    def _extract_and_validate_package(
        self, source: Path, password: str
    ) -> tuple[Path, object, dict]:
        source = Path(source)
        if source.suffix.lower() != self.extension:
            if source.suffix.lower() == ".chitbackup":
                raise BackupValidationError(
                    "Old full-database .chitbackup files are not accepted here. "
                    "Create a new data-only .chitdata backup."
                )
            raise BackupValidationError(
                f"Only {self.extension} ChitLog data backups can be restored."
            )

        try:
            size = source.stat().st_size
        except OSError:
            raise BackupValidationError("The selected data backup cannot be read.") from None

        if size <= len(MAGIC) + 4 or size > MAX_BACKUP_BYTES + MAX_HEADER_BYTES + 1024:
            raise BackupValidationError("The data backup file size is not allowed.")

        temp_db = self.local_backup_dir / f".data-restore-source-{uuid4().hex}.db"
        try:
            with source.open("rb") as handle:
                if handle.read(len(MAGIC)) != MAGIC:
                    raise BackupValidationError(
                        "The selected file is not a ChitLog data-only backup."
                    )
                raw_length = handle.read(4)
                if len(raw_length) != 4:
                    raise BackupValidationError("The data backup header is incomplete.")
                header_length = struct.unpack(">I", raw_length)[0]
                if header_length <= 0 or header_length > MAX_HEADER_BYTES:
                    raise BackupValidationError("The data backup header size is invalid.")

                raw_header = handle.read(header_length)
                if len(raw_header) != header_length:
                    raise BackupValidationError("The data backup header is incomplete.")
                try:
                    header = json.loads(raw_header.decode("utf-8"))
                except (UnicodeDecodeError, json.JSONDecodeError):
                    raise BackupValidationError("The data backup header is malformed.") from None

                if (
                    not isinstance(header, dict)
                    or header.get("format") != "ChitLogDataBackup"
                    or header.get("version") != FORMAT_VERSION
                    or header.get("contains_credentials") is not False
                    or header.get("contains_system_settings") is not False
                    or header.get("data_tables") != list(DATA_TABLES)
                ):
                    raise BackupValidationError(
                        "This ChitLog data backup format is unsupported or invalid."
                    )
                if header.get("kdf") != "scrypt-n32768-r8-p1":
                    raise BackupValidationError("The data backup encryption method is unsupported.")

                try:
                    salt = base64.b64decode(header["salt"], validate=True)
                except Exception:
                    raise BackupValidationError(
                        "The data backup encryption metadata is invalid."
                    ) from None
                if len(salt) != SALT_BYTES:
                    raise BackupValidationError(
                        "The data backup encryption metadata is invalid."
                    )

                expected_payload_size = header.get("payload_bytes")
                expected_digest = header.get("payload_sha256")
                if (
                    not isinstance(expected_payload_size, int)
                    or expected_payload_size <= 0
                    or expected_payload_size > MAX_BACKUP_BYTES
                    or not isinstance(expected_digest, str)
                    or len(expected_digest) != 64
                ):
                    raise BackupValidationError("The data backup metadata is invalid.")

                digest = hashlib.sha256()
                written = 0
                with temp_db.open("xb") as output:
                    while True:
                        chunk = handle.read(1024 * 1024)
                        if not chunk:
                            break
                        written += len(chunk)
                        if written > MAX_BACKUP_BYTES:
                            raise BackupValidationError("The data backup payload is too large.")
                        digest.update(chunk)
                        output.write(chunk)

                if written != expected_payload_size:
                    raise BackupValidationError(
                        "The data backup payload size does not match."
                    )
                if not secrets.compare_digest(digest.hexdigest(), expected_digest):
                    raise BackupValidationError(
                        "The data backup file has been modified or corrupted."
                    )

            key = _derive_backup_key(password, salt)
            try:
                connection = _open_sqlcipher(temp_db, key)
                schema_version = self._validate_data_payload(connection)
            except BackupValidationError:
                raise
            except Exception:
                raise BackupPasswordError(
                    "The backup password is incorrect or the data backup is unreadable."
                ) from None

            if header.get("schema_version") != schema_version:
                connection.close()
                raise BackupValidationError(
                    "Data backup schema metadata does not match its payload."
                )
            return temp_db, connection, header
        except BackupValidationError:
            temp_db.unlink(missing_ok=True)
            raise
        except Exception:
            temp_db.unlink(missing_ok=True)
            raise BackupPasswordError(
                "The backup password is incorrect or the data backup is unreadable."
            ) from None

    def _create_safety_backup(self) -> Path:
        """Internal same-machine rollback snapshot; never offered as portable backup."""
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        safety = self.safety_dir / f"pre-data-restore-{stamp}-{uuid4().hex}.db"
        self.database.encrypted_copy(safety)
        self._rotate_safety_backups()
        return safety

    def _rotate_safety_backups(self) -> None:
        backups = sorted(
            self.safety_dir.glob("pre-data-restore-*.db"),
            key=lambda path: path.stat().st_mtime,
            reverse=True,
        )
        for old in backups[SAFETY_RETENTION:]:
            old.unlink(missing_ok=True)

    def _restore_data_tables(self, backup_connection) -> None:
        live = self.database.connection
        if live is None:
            raise RestoreError("The ChitLog database is not open.")

        # One atomic transaction: either every business-data table is restored
        # or the existing live data remains unchanged.
        live.execute("BEGIN IMMEDIATE")
        try:
            live.execute("PRAGMA defer_foreign_keys=ON")

            for table in reversed(DATA_TABLES):
                live.execute(f"DELETE FROM {_quote_identifier(table)}")

            for table in DATA_TABLES:
                live_columns = self._table_columns(live, table)
                backup_columns = self._table_columns(backup_connection, table)
                if live_columns != backup_columns:
                    raise BackupValidationError(
                        f"Data table structure does not match: {table}."
                    )

                column_sql = ",".join(
                    _quote_identifier(column) for column in live_columns
                )
                placeholders = ",".join("?" for _ in live_columns)
                source = backup_connection.execute(
                    f"SELECT {column_sql} FROM {_quote_identifier(table)}"
                )
                insert_sql = (
                    f"INSERT INTO {_quote_identifier(table)}({column_sql}) "
                    f"VALUES ({placeholders})"
                )
                while True:
                    rows = source.fetchmany(500)
                    if not rows:
                        break
                    live.executemany(insert_sql, rows)

            if live.execute("PRAGMA foreign_key_check").fetchall():
                raise RestoreError(
                    "Restored business data failed relationship validation."
                )
            if live.execute("PRAGMA integrity_check").fetchall() != [("ok",)]:
                raise RestoreError("Restored business data failed integrity validation.")

            live.execute("COMMIT")
        except BaseException:
            if live.in_transaction:
                live.execute("ROLLBACK")
            raise

        # Full encrypted DB remains authoritative and must still validate after
        # the selective data transaction.
        self.database.validate()

    def restore_backup(self, source: Path, password: str) -> Path:
        temp_source = None
        backup_connection = None
        safety = None

        try:
            temp_source, backup_connection, _header = self._extract_and_validate_package(
                Path(source), password
            )

            # Internal rollback safety copy includes the whole local DB, including
            # auth/settings, but it remains local and is never a portable backup.
            safety = self._create_safety_backup()

            # This replaces ONLY DATA_TABLES. auth_profile, security_questions,
            # application_settings and schema_migrations are untouched.
            self._restore_data_tables(backup_connection)
            return safety
        except BackupError:
            raise
        except Exception:
            raise RestoreError("The data backup could not be restored safely.") from None
        finally:
            if backup_connection is not None:
                backup_connection.close()
            if temp_source is not None:
                Path(temp_source).unlink(missing_ok=True)


def recover_latest_pre_restore_backup(
    database_path: Path,
    key: bytes,
    safety_dir: Path,
) -> tuple[Path, Path | None]:
    """Emergency recovery for earlier Step 18 full-database restore incidents.

    Kept only so users who already created an old pre-restore safety snapshot can
    recover it. New portable backups are DATA ONLY and do not use this path.
    """
    database_path = Path(database_path)
    safety_dir = Path(safety_dir)
    candidates = sorted(
        list(safety_dir.glob("pre-data-restore-*.db"))
        + list(safety_dir.glob("pre-restore-*.db")),
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    )
    if not candidates:
        raise RestoreError(
            "No validated restore safety backup was found. Do not create a new database key."
        )

    valid = None
    for candidate in candidates:
        probe = Database(candidate, key, safety_dir / ".recovery-probe")
        try:
            probe.connection = probe._connect_with_key(candidate, key)
            probe._validate_connection(probe.connection)
            valid = candidate
            break
        except Exception:
            pass
        finally:
            probe.close()

    if valid is None:
        raise RestoreError(
            "Restore safety backups were found, but none could be validated "
            "with the current Windows database key."
        )

    stage = database_path.with_name(f".recovery-stage-{uuid4().hex}.db")
    preserved = None
    try:
        shutil.copy2(valid, stage)

        stage_probe = Database(stage, key, safety_dir / ".recovery-probe")
        try:
            stage_probe.connection = stage_probe._connect_with_key(stage, key)
            stage_probe._validate_connection(stage_probe.connection)
        finally:
            stage_probe.close()

        if database_path.exists():
            stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
            preserved = safety_dir / f"failed-restored-live-{stamp}-{uuid4().hex}.db"
            os.replace(database_path, preserved)

        try:
            os.replace(stage, database_path)
            final_probe = Database(database_path, key, safety_dir / ".recovery-probe")
            try:
                final_probe.connection = final_probe._connect_with_key(
                    database_path, key
                )
                final_probe._validate_connection(final_probe.connection)
            finally:
                final_probe.close()
        except Exception:
            database_path.unlink(missing_ok=True)
            if preserved is not None and preserved.exists():
                os.replace(preserved, database_path)
            raise RestoreError(
                "Recovery validation failed. The previous live file was put back."
            ) from None

        return valid, preserved
    finally:
        stage.unlink(missing_ok=True)
