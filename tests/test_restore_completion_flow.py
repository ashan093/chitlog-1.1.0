"""Step 18 data-only restore completion regression check."""
from pathlib import Path


def test_data_restore_explains_credentials_and_settings_are_preserved():
    project = Path(__file__).resolve().parents[1]
    backup_ui = (
        project / "chitlog/ui/pages/backup_settings.py"
    ).read_text(encoding="utf-8")

    assert "Business data restored successfully" in backup_ui
    assert "login credentials" in backup_ui
    assert "security questions" in backup_ui
    assert "theme, currency" in backup_ui
    assert "notification settings" in backup_ui
    assert "kept unchanged" in backup_ui
    assert "restored login, settings, and records" not in backup_ui
