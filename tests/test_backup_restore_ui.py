"""Step 18 data-only backup UI integration checks."""
from pathlib import Path


def test_settings_page_is_data_backup_only():
    project = Path(__file__).resolve().parents[1]
    backup_ui = (
        project / "chitlog/ui/pages/backup_settings.py"
    ).read_text(encoding="utf-8")

    assert 'Card("Data Backup & Restore")' in backup_ui
    assert 'button("Create Data Backup", "primary")' in backup_ui
    assert 'button("Restore Data Backup")' in backup_ui
    assert "*.chitdata" in backup_ui
    assert ".chitbackup" not in backup_ui
    assert "login/PIN/password" in backup_ui
    assert "security-question answers" in backup_ui
    assert "NOT restored or changed" in backup_ui
    assert "System Backup" not in backup_ui


def test_data_restore_completion_is_explicit_before_close():
    project = Path(__file__).resolve().parents[1]
    backup_ui = (
        project / "chitlog/ui/pages/backup_settings.py"
    ).read_text(encoding="utf-8")
    main_window = (
        project / "chitlog/ui/main_window.py"
    ).read_text(encoding="utf-8")

    assert "Business data restored successfully" in backup_ui
    assert "other application settings were kept unchanged" in backup_ui
    assert 'button("Close ChitLog", "primary")' in backup_ui
    assert "_show_restore_complete(self)" in backup_ui
    assert "QTimer.singleShot(1600, QApplication.quit)" not in main_window
    assert "page.backup_card.restore_completed.connect(QApplication.quit)" in main_window
