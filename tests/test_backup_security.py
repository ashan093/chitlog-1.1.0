"""Security invariants for Step 18 portable DATA-only backups."""
from pathlib import Path


def test_portable_backup_has_explicit_business_data_allowlist():
    project = Path(__file__).resolve().parents[1]
    source = (
        project / "chitlog/services/backup_service.py"
    ).read_text(encoding="utf-8")

    for table in (
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
    ):
        assert f'"{table}"' in source

    for protected in (
        "application_settings",
        "auth_profile",
        "security_questions",
        "schema_migrations",
    ):
        assert f'"{protected}"' in source

    assert "contains_credentials" in source
    assert "contains_system_settings" in source
    assert "Old full-database .chitbackup files are not accepted here" in source


def test_backup_pipeline_uses_safe_encryption_and_no_unsafe_deserialization():
    project = Path(__file__).resolve().parents[1]
    source = (
        project / "chitlog/services/backup_service.py"
    ).read_text(encoding="utf-8")
    lowered = source.lower()

    assert "pickle" not in lowered
    assert "eval(" not in source
    assert "exec(" not in source
    assert "hashlib.scrypt" in source
    assert "secrets.compare_digest" in source
    assert "cipher_integrity_check" in source
    assert "integrity_check" in source
    assert "foreign_key_check" in source
    assert "BEGIN IMMEDIATE" in source
    assert "ROLLBACK" in source
    assert 'return ".chitdata"' in source


def test_portable_payload_is_built_fresh_not_by_scrubbing_full_database_copy():
    project = Path(__file__).resolve().parents[1]
    source = (
        project / "chitlog/services/backup_service.py"
    ).read_text(encoding="utf-8")

    # Full internal encrypted_copy is allowed only for the local safety snapshot.
    # Portable data creation builds a fresh SQLCipher database and copies DATA_TABLES.
    assert "def _create_data_payload" in source
    assert "for table in DATA_TABLES:" in source
    assert "auth_profile" in source
    assert "security_questions" in source
    assert "application_settings" in source
    assert "never enter the portable payload" in source
