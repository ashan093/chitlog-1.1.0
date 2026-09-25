"""Step 4B tests for Settings -> Updates preferences UI."""
from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys


def test_step4b_updates_card_and_controls_are_present():
    project = Path(__file__).resolve().parents[1]
    page = (project / "chitlog/ui/pages/settings.py").read_text(encoding="utf-8")
    for expected in (
        'Card("Updates")',
        '"Automatically check for updates"',
        '"Stable (recommended)", "stable"',
        '"Beta", "beta"',
        'button("Check for Updates")',
        "update_preferences_service",
        "service.configure(",
        "self.update_preferences_changed.emit()",
    ):
        assert expected in page
    assert "update_checker" not in page
    assert "update_transport" not in page
    assert "http.client" not in page


def test_step4b_application_wires_update_preferences_service():
    project = Path(__file__).resolve().parents[1]
    application = (project / "chitlog/application.py").read_text(encoding="utf-8")
    main_window = (project / "chitlog/ui/main_window.py").read_text(encoding="utf-8")
    assert "UpdatePreferencesRepository" in application
    assert "UpdatePreferencesService" in application
    assert "update_preferences_service = UpdatePreferencesService(" in application
    assert "update_preferences_service=update_preferences_service" in application
    assert "self.update_preferences_service = update_preferences_service" in main_window
    assert "update_preferences_service=self.update_preferences_service" in main_window


def test_step4b_manual_check_is_visible_but_not_connected_yet():
    project = Path(__file__).resolve().parents[1]
    page = (project / "chitlog/ui/pages/settings.py").read_text(encoding="utf-8")
    assert 'self.check_updates_button = button("Check for Updates")' in page
    assert "self.check_updates_button.setEnabled(False)" in page
    assert "update_checker" not in page
    assert "fetch_manifest_bytes" not in page


def test_step4b_settings_runtime_persists_update_preferences_offscreen():
    project = Path(__file__).resolve().parents[1]
    code = r'''
import secrets
import tempfile
from pathlib import Path
from PySide6.QtWidgets import QApplication
from chitlog.core.security import hash_secret, hash_security_answer
from chitlog.core.version import APP_VERSION
from chitlog.data.database import Database
from chitlog.data.settings_repository import SettingsRepository
from chitlog.data.update_preferences_repository import UpdatePreferencesRepository
from chitlog.services.settings_service import SettingsService
from chitlog.services.update_preferences_service import UpdatePreferencesService
from chitlog.ui.pages.settings import SettingsPage
app = QApplication([])
with tempfile.TemporaryDirectory() as d:
    root = Path(d)
    db = Database(root / "settings.db", secrets.token_bytes(32), root / "snapshots").open()
    try:
        with db.transaction() as connection:
            connection.execute(
                "INSERT INTO auth_profile(id,login_method,secret_hash) VALUES (1,'password',?)",
                (hash_secret("password", "current-password"),),
            )
            connection.executemany(
                "INSERT INTO security_questions(position,question,answer_hash) VALUES (?,?,?)",
                [
                    (1, "Question one?", hash_security_answer("answer one")),
                    (2, "Question two?", hash_security_answer("answer two")),
                ],
            )
            connection.executemany(
                "INSERT INTO application_settings(key,value) VALUES (?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                [("theme", "dark"), ("currency_code", "LKR"), ("currency_symbol", "Rs"), ("setup_complete", "true")],
            )
        settings_service = SettingsService(SettingsRepository(db))
        update_service = UpdatePreferencesService(UpdatePreferencesRepository(db))
        page = SettingsPage(settings_service, notification_service=None, backup_service=None, update_preferences_service=update_service)
        page.show()
        app.processEvents()
        assert page.update_current_version_label.text() == APP_VERSION
        assert page.update_auto_check.isChecked() is True
        assert page.update_channel_combo.currentData() == "stable"
        assert page.update_interval_label.text() == "Every 24 hours"
        assert page.update_auto_install_label.text() == "Off"
        assert page.apply_update_preferences_button.isEnabled() is False
        assert page.check_updates_button.isEnabled() is False
        page.update_auto_check.setChecked(False)
        page.update_channel_combo.setCurrentIndex(page.update_channel_combo.findData("beta"))
        app.processEvents()
        assert page.apply_update_preferences_button.isEnabled() is True
        page.apply_update_preferences_button.click()
        app.processEvents()
        saved = update_service.snapshot()
        assert saved.auto_check_enabled is False
        assert saved.channel == "beta"
        assert saved.auto_install_enabled is False
        assert saved.check_interval_seconds == 24 * 60 * 60
        assert page.apply_update_preferences_button.isEnabled() is False
        assert "preferences saved" in page.update_preferences_feedback.text().lower()
        page.close()
    finally:
        db.close()
'''
    result = subprocess.run(
        [sys.executable, "-c", code], cwd=project,
        env=dict(os.environ, QT_QPA_PLATFORM="offscreen"),
        capture_output=True, text=True, timeout=30,
    )
    assert result.returncode == 0, result.stderr


def test_existing_settings_page_still_supports_no_update_service():
    project = Path(__file__).resolve().parents[1]
    code = r'''
import secrets
import tempfile
from pathlib import Path
from PySide6.QtWidgets import QApplication
from chitlog.core.security import hash_secret, hash_security_answer
from chitlog.data.database import Database
from chitlog.data.settings_repository import SettingsRepository
from chitlog.services.settings_service import SettingsService
from chitlog.ui.pages.settings import SettingsPage
app = QApplication([])
with tempfile.TemporaryDirectory() as d:
    root = Path(d)
    db = Database(root / "settings.db", secrets.token_bytes(32), root / "snapshots").open()
    try:
        with db.transaction() as connection:
            connection.execute(
                "INSERT INTO auth_profile(id,login_method,secret_hash) VALUES (1,'password',?)",
                (hash_secret("password", "current-password"),),
            )
            connection.executemany(
                "INSERT INTO security_questions(position,question,answer_hash) VALUES (?,?,?)",
                [(1, "Question one?", hash_security_answer("answer one")), (2, "Question two?", hash_security_answer("answer two"))],
            )
        page = SettingsPage(SettingsService(SettingsRepository(db)))
        page.show()
        app.processEvents()
        assert page.update_auto_check.isEnabled() is False
        assert page.update_channel_combo.isEnabled() is False
        assert page.check_updates_button.isEnabled() is False
        page.close()
    finally:
        db.close()
'''
    result = subprocess.run(
        [sys.executable, "-c", code], cwd=project,
        env=dict(os.environ, QT_QPA_PLATFORM="offscreen"),
        capture_output=True, text=True, timeout=30,
    )
    assert result.returncode == 0, result.stderr
