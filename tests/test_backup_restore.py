"""Step 18 DATA-only encrypted backup and selective restore tests."""
import secrets

import pytest

from chitlog.data.database import Database
from chitlog.services.backup_service import (
    BackupError,
    BackupPasswordError,
    BackupService,
    BackupValidationError,
    DATA_TABLES,
    META_TABLE,
    PROTECTED_TABLES,
    MAX_BACKUP_BYTES,
    _derive_backup_key,
    _open_sqlcipher,
)


def make_db(tmp_path):
    return Database(
        tmp_path / "live.db",
        secrets.token_bytes(32),
        tmp_path / "migration-snapshots",
    ).open()


def upsert_setting(db, key, value):
    with db.transaction() as connection:
        connection.execute(
            "INSERT INTO application_settings(key,value) VALUES (?,?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (key, value),
        )


def setting_value(db, key):
    row = db.connection.execute(
        "SELECT value FROM application_settings WHERE key=?",
        (key,),
    ).fetchone()
    return row[0] if row else None


def category_exists(db, name):
    return db.connection.execute(
        "SELECT 1 FROM categories WHERE name=?",
        (name,),
    ).fetchone() is not None


def set_auth_test_data(db, secret_hash, answer_hash):
    with db.transaction() as connection:
        connection.execute("DELETE FROM security_questions")
        connection.execute("DELETE FROM auth_profile")
        connection.execute(
            "INSERT INTO auth_profile(id,login_method,secret_hash) "
            "VALUES (1,'password',?)",
            (secret_hash,),
        )
        connection.execute(
            "INSERT INTO security_questions(position,question,answer_hash) "
            "VALUES (1,'Backup test question',?)",
            (answer_hash,),
        )


def test_data_backup_contains_business_tables_only_and_restores_data(tmp_path):
    db = make_db(tmp_path)
    try:
        service = BackupService(db, tmp_path / "backups")

        set_auth_test_data(
            db,
            "AUTH-SECRET-FROM-BACKUP-TIME",
            "SECURITY-ANSWER-FROM-BACKUP-TIME",
        )
        upsert_setting(db, "step18_system_marker", "SYSTEM-BACKUP-TIME")

        with db.transaction() as connection:
            connection.execute(
                "INSERT INTO categories(kind,name) VALUES ('expense',?)",
                ("Data Backup Marker",),
            )

        backup = tmp_path / "portable.chitdata"
        password = "correct horse battery staple"
        service.create_backup(backup, password)

        # Extract the encrypted payload and verify protected tables do not exist
        # at all. This is stronger than merely deleting their rows.
        temp_db, backup_connection, header = service._extract_and_validate_package(
            backup, password
        )
        try:
            tables = service._user_tables(backup_connection)
            assert tables == set(DATA_TABLES) | {META_TABLE}
            for protected in PROTECTED_TABLES:
                assert protected not in tables
            assert header["contains_credentials"] is False
            assert header["contains_system_settings"] is False
        finally:
            backup_connection.close()
            temp_db.unlink(missing_ok=True)

        # Change both business data and local credentials/settings after backup.
        with db.transaction() as connection:
            connection.execute(
                "DELETE FROM categories WHERE name=?",
                ("Data Backup Marker",),
            )
        set_auth_test_data(
            db,
            "CURRENT-LOGIN-SECRET-MUST-STAY",
            "CURRENT-RECOVERY-SECRET-MUST-STAY",
        )
        upsert_setting(db, "step18_system_marker", "CURRENT-SYSTEM-MUST-STAY")

        service.restore_backup(backup, password)

        # Business data comes from the backup.
        assert category_exists(db, "Data Backup Marker")

        # Authentication/recovery/system settings remain CURRENT and are not restored.
        auth = db.connection.execute(
            "SELECT secret_hash FROM auth_profile WHERE id=1"
        ).fetchone()[0]
        answer = db.connection.execute(
            "SELECT answer_hash FROM security_questions WHERE position=1"
        ).fetchone()[0]
        assert auth == "CURRENT-LOGIN-SECRET-MUST-STAY"
        assert answer == "CURRENT-RECOVERY-SECRET-MUST-STAY"
        assert setting_value(db, "step18_system_marker") == "CURRENT-SYSTEM-MUST-STAY"

        # Restore safety snapshot remains local/full and exists.
        assert list(
            (tmp_path / "backups" / "restore-safety").glob("pre-data-restore-*.db")
        )
    finally:
        db.close()


def test_wrong_password_does_not_change_live_data_or_settings(tmp_path):
    db = make_db(tmp_path)
    try:
        service = BackupService(db, tmp_path / "backups")
        with db.transaction() as connection:
            connection.execute(
                "INSERT INTO categories(kind,name) VALUES ('expense',?)",
                ("Wrong Password Marker",),
            )
        backup = tmp_path / "portable.chitdata"
        service.create_backup(backup, "correct horse battery staple")

        with db.transaction() as connection:
            connection.execute(
                "DELETE FROM categories WHERE name=?",
                ("Wrong Password Marker",),
            )
        upsert_setting(db, "step18_system_marker", "do-not-change")

        with pytest.raises(BackupPasswordError):
            service.restore_backup(backup, "wrong password 12345")

        assert not category_exists(db, "Wrong Password Marker")
        assert setting_value(db, "step18_system_marker") == "do-not-change"
    finally:
        db.close()


def test_corrupted_data_backup_is_rejected_before_live_data_changes(tmp_path):
    db = make_db(tmp_path)
    try:
        service = BackupService(db, tmp_path / "backups")
        backup = tmp_path / "portable.chitdata"
        service.create_backup(backup, "correct horse battery staple")

        upsert_setting(db, "step18_system_marker", "safe")
        data = bytearray(backup.read_bytes())
        data[-100] ^= 0x55
        backup.write_bytes(data)

        with pytest.raises(BackupValidationError):
            service.restore_backup(backup, "correct horse battery staple")
        assert setting_value(db, "step18_system_marker") == "safe"
        db.validate()
    finally:
        db.close()


def test_old_full_backup_extension_is_rejected(tmp_path):
    db = make_db(tmp_path)
    try:
        service = BackupService(db, tmp_path / "backups")
        old = tmp_path / "old.chitbackup"
        old.write_bytes(b"old full backup")
        with pytest.raises(BackupValidationError, match="Old full-database"):
            service.restore_backup(old, "correct horse battery staple")
    finally:
        db.close()


def test_invalid_extension_oversize_short_password_and_overwrite_are_rejected(tmp_path):
    db = make_db(tmp_path)
    try:
        service = BackupService(db, tmp_path / "backups")

        wrong = tmp_path / "backup.zip"
        wrong.write_bytes(b"not a backup")
        with pytest.raises(BackupValidationError):
            service.restore_backup(wrong, "correct horse battery staple")

        huge = tmp_path / "huge.chitdata"
        with huge.open("wb") as handle:
            handle.truncate(MAX_BACKUP_BYTES + 100_000)
        with pytest.raises(BackupValidationError):
            service.restore_backup(huge, "correct horse battery staple")

        backup = tmp_path / "portable.chitdata"
        with pytest.raises(BackupError):
            service.create_backup(backup, "short")

        service.create_backup(backup, "correct horse battery staple")
        with pytest.raises(BackupError):
            service.create_backup(backup, "correct horse battery staple")
    finally:
        db.close()


def test_data_restore_is_transactional_when_source_relationship_is_invalid(tmp_path):
    db = make_db(tmp_path)
    try:
        service = BackupService(db, tmp_path / "backups")
        password = "correct horse battery staple"

        with db.transaction() as connection:
            connection.execute(
                "INSERT INTO categories(kind,name) VALUES ('expense',?)",
                ("Transactional Marker",),
            )
        backup = tmp_path / "portable.chitdata"
        service.create_backup(backup, password)

        # Live DB changes after the backup.
        with db.transaction() as connection:
            connection.execute(
                "DELETE FROM categories WHERE name=?",
                ("Transactional Marker",),
            )
            connection.execute(
                "INSERT INTO categories(kind,name) VALUES ('expense',?)",
                ("Live Marker Must Survive Failure",),
            )

        # We do not tamper with the package here because SHA-256 is supposed to
        # reject tampering before SQL is opened. The transaction behavior is
        # independently guaranteed by the restore service BEGIN/ROLLBACK path.
        source = (work := service._extract_and_validate_package(backup, password))
        temp_db, backup_connection, _ = source
        try:
            # Simulate a validated source that becomes structurally unacceptable
            # to the restore routine by monkeying its reported columns.
            original = service._table_columns

            def bad_columns(connection, table):
                columns = original(connection, table)
                if connection is backup_connection and table == "categories":
                    return columns + ["not_a_real_column"]
                return columns

            service._table_columns = bad_columns
            with pytest.raises(BackupValidationError):
                service._restore_data_tables(backup_connection)
        finally:
            backup_connection.close()
            temp_db.unlink(missing_ok=True)

        assert category_exists(db, "Live Marker Must Survive Failure")
        assert not category_exists(db, "Transactional Marker")
        db.validate()
    finally:
        db.close()
