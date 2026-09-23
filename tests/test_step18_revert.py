"""Confirm Step 20 keeps the confirmed Step 18 data-only backup model."""
from pathlib import Path


def test_backup_is_step18_data_only_format_not_step19_package_format():
    project = Path(__file__).resolve().parents[1]
    service = (
        project / "chitlog/services/backup_service.py"
    ).read_text(encoding="utf-8")
    ui = (
        project / "chitlog/ui/pages/backup_settings.py"
    ).read_text(encoding="utf-8")

    assert 'MAGIC = b"CHITLOG-DATA-BACKUP\\x00"' in service
    assert "FORMAT_VERSION = 2" in service
    assert 'return ".chitdata"' in service
    assert "contains_credentials" in service
    assert "contains_system_settings" in service
    assert "HMAC-SHA256" not in service
    assert 'Card("Data Backup & Restore")' in ui
    assert "Google Drive" not in ui
