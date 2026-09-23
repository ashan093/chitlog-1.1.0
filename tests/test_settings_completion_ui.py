"""Step 20 completed Settings UI and wiring."""
from pathlib import Path


def test_step20_settings_page_connects_all_required_sections():
    project = Path(__file__).resolve().parents[1]
    page = (
        project / "chitlog/ui/pages/settings.py"
    ).read_text(encoding="utf-8")

    for text in (
        'Card("Currency")',
        'Card("Appearance")',
        'Card("Security")',
        "NotificationsPage",
        "BackupSettingsCard",
        'Card("Application Information")',
    ):
        assert text in page

    assert "Change Login Credentials" in page
    assert "Update Recovery Questions" in page
    assert "Cloud backup" in page
    assert "Not included in this version" in page
    assert "Works offline" in page
    assert 'info_grid.addRow("Developed by", QLabel("Ashan Madusanka"))' in page
    assert '"Copyright",' in page
    assert 'QLabel("© 2026 Ashan Madusanka. All rights reserved.")' in page
    assert 'info_grid.addRow("License", QLabel("Proprietary"))' in page


def test_main_window_uses_settings_page_not_notification_page_as_settings_shell():
    project = Path(__file__).resolve().parents[1]
    source = (
        project / "chitlog/ui/main_window.py"
    ).read_text(encoding="utf-8")

    assert "from chitlog.ui.pages.settings import SettingsPage" in source
    assert "page = SettingsPage(" in source
    assert "page.theme_requested.connect(self.select_theme)" in source
    assert "notification_settings_changed" in source
    assert "restore_completed.connect(QApplication.quit)" in source


def test_step19_google_drive_feature_is_removed_from_v1_wiring_and_requirements():
    project = Path(__file__).resolve().parents[1]
    application = (
        project / "chitlog/application.py"
    ).read_text(encoding="utf-8")
    requirements = (project / "requirements.txt").read_text(encoding="utf-8")

    assert "GoogleDrive" not in application
    assert "google-auth" not in requirements
    assert "google-api-python-client" not in requirements

    assert not (project / "chitlog/core/google_drive_token_store.py").exists()
    assert not (project / "chitlog/services/google_drive_backup_service.py").exists()
    assert not (project / "chitlog/ui/pages/google_drive_backup.py").exists()


def test_application_wires_settings_service():
    project = Path(__file__).resolve().parents[1]
    source = (
        project / "chitlog/application.py"
    ).read_text(encoding="utf-8")

    assert "SettingsRepository" in source
    assert "SettingsService" in source
    assert "settings_service=settings_service" in source
