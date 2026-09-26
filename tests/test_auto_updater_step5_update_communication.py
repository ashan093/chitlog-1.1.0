"""Step 5B tests for update communication and auto-check privacy UX."""
from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys


def test_settings_explains_auto_check_off_without_creating_network_path():
    project = Path(__file__).resolve().parents[1]
    source = (
        project / "chitlog/ui/pages/settings.py"
    ).read_text(encoding="utf-8")

    for expected in (
        "update_auto_check_notice",
        "Automatic checks are off.",
        "will not contact",
        "cannot know whether",
        "Check for Updates",
        "Financial records are not sent.",
    ):
        assert expected in source

    for forbidden in (
        "http.client",
        "urllib.request",
        "requests",
        "httpx",
        "fetch_manifest_bytes",
    ):
        assert forbidden not in source


def test_auto_check_notice_tracks_saved_and_pending_state():
    project = Path(__file__).resolve().parents[1]

    code = r"""
import secrets
import tempfile
from pathlib import Path

from PySide6.QtCore import QObject, Signal
from PySide6.QtWidgets import QApplication

from chitlog.core.security import hash_secret, hash_security_answer
from chitlog.data.database import Database
from chitlog.data.settings_repository import SettingsRepository
from chitlog.data.update_preferences_repository import UpdatePreferencesRepository
from chitlog.services.settings_service import SettingsService
from chitlog.services.update_preferences_service import UpdatePreferencesService
from chitlog.ui.pages.settings import SettingsPage

class FakeRunner(QObject):
    succeeded = Signal(object)
    failed = Signal(object)
    finished = Signal()

    def __init__(self):
        super().__init__()
        self.running = False

    def start(self, policy):
        return False

app = QApplication([])

with tempfile.TemporaryDirectory() as d:
    root = Path(d)
    db = Database(
        root / "settings.db",
        secrets.token_bytes(32),
        root / "snapshots",
    ).open()

    try:
        with db.transaction() as connection:
            connection.execute(
                "INSERT INTO auth_profile(id,login_method,secret_hash) "
                "VALUES (1,'password',?)",
                (hash_secret("password", "current-password"),),
            )
            connection.executemany(
                "INSERT INTO security_questions(position,question,answer_hash) "
                "VALUES (?,?,?)",
                [
                    (1, "Question one?", hash_security_answer("answer one")),
                    (2, "Question two?", hash_security_answer("answer two")),
                ],
            )

        update_service = UpdatePreferencesService(
            UpdatePreferencesRepository(db)
        )

        page = SettingsPage(
            SettingsService(SettingsRepository(db)),
            update_preferences_service=update_service,
            update_check_runner=FakeRunner(),
        )
        page.show()
        app.processEvents()

        initial = page.update_auto_check_notice.text()
        assert "Automatic checks are on." in initial
        assert "Financial records are not sent." in initial
        assert page.check_updates_button.isEnabled() is True

        page.update_auto_check.setChecked(False)
        app.processEvents()

        pending = page.update_auto_check_notice.text()
        assert pending.startswith("After Apply:")
        assert "Automatic checks are off." in pending
        assert "will not contact" in pending
        assert "cannot know whether" in pending
        assert page.apply_update_preferences_button.isEnabled() is True
        assert page.check_updates_button.isEnabled() is False

        page.apply_update_preferences_button.click()
        app.processEvents()

        saved = update_service.snapshot()
        assert saved.auto_check_enabled is False
        assert page.apply_update_preferences_button.isEnabled() is False
        assert page.check_updates_button.isEnabled() is True

        final = page.update_auto_check_notice.text()
        assert not final.startswith("After Apply:")
        assert "Automatic checks are off." in final
        assert "Check for Updates manually" in final

        page.close()
    finally:
        db.close()
"""
    result = subprocess.run(
        [sys.executable, "-c", code],
        cwd=project,
        env=dict(os.environ, QT_QPA_PLATFORM="offscreen"),
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, result.stderr


def test_update_success_feedback_coordinates_with_global_notification():
    project = Path(__file__).resolve().parents[1]
    source = (
        project / "chitlog/ui/pages/settings.py"
    ).read_text(encoding="utf-8")

    assert "The verified update notification in the main window " in source
    assert "available release actions." in source


def test_step5b_does_not_add_update_announcement_network_bypass():
    project = Path(__file__).resolve().parents[1]
    source = (
        project / "chitlog/ui/pages/settings.py"
    ).read_text(encoding="utf-8")

    assert "update_auto_check_notice" in source
    assert "check_for_updates(" not in source
    assert "fetch_manifest_bytes" not in source
