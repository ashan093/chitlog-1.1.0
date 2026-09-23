"""Step 22 source invariants for backups, SQL, deletes, and offline V1."""
from pathlib import Path


def test_database_security_pragmas_and_no_sql_trace_logging():
    project = Path(__file__).resolve().parents[1]
    source = (project / "chitlog/data/database.py").read_text(encoding="utf-8")

    assert "PRAGMA cipher_integrity_check" in source
    assert "PRAGMA foreign_keys=ON" in source
    assert "PRAGMA trusted_schema=OFF" in source
    assert "PRAGMA synchronous=FULL" in source
    assert "set_trace_callback" not in source


def test_step18_backup_remains_data_only_and_selective():
    project = Path(__file__).resolve().parents[1]
    source = (
        project / "chitlog/services/backup_service.py"
    ).read_text(encoding="utf-8")

    assert "DATA_TABLES" in source
    assert "PROTECTED_TABLES" in source
    assert '"auth_profile"' in source
    assert '"security_questions"' in source
    assert '"application_settings"' in source
    assert "BEGIN IMMEDIATE" in source
    assert "ROLLBACK" in source
    assert "foreign_key_check" in source
    assert "integrity_check" in source


def test_soft_delete_and_restore_paths_remain_present_for_financial_records():
    project = Path(__file__).resolve().parents[1]

    transaction = (
        project / "chitlog/data/transaction_repository.py"
    ).read_text(encoding="utf-8")
    worker_payment = (
        project / "chitlog/data/worker_payment_repository.py"
    ).read_text(encoding="utf-8")
    worker_work = (
        project / "chitlog/data/worker_work_repository.py"
    ).read_text(encoding="utf-8")

    assert "soft_delete" in transaction and "restore" in transaction
    assert "soft_delete" in worker_payment and "restore" in worker_payment
    assert "soft_delete" in worker_work and "restore" in worker_work


def test_money_core_uses_decimal_and_integer_minor_units():
    project = Path(__file__).resolve().parents[1]
    source = (
        project / "chitlog/core/money.py"
    ).read_text(encoding="utf-8")

    assert "from decimal import Decimal" in source
    assert "minor = int(" in source
    assert "float(" not in source
