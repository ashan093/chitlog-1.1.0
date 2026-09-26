"""Step 4C tests for the non-blocking manual update check."""
from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys


def test_runner_source_uses_dedicated_qthread_and_avoids_widgets_database():
    project = Path(__file__).resolve().parents[1]
    source = (
        project / "chitlog/ui/update_check_runner.py"
    ).read_text(encoding="utf-8")

    assert "class _UpdateCheckThread(QThread):" in source
    assert "def run(self) -> None:" in source
    assert "check_for_updates" in source
    assert "policy_from_preferences" in source
    assert "moveToThread" not in source
    assert "terminate()" not in source

    for forbidden in (
        "QLabel",
        "QPushButton",
        "SettingsRepository",
        "Database(",
        "application_settings",
    ):
        assert forbidden not in source


def test_settings_manual_check_has_no_direct_network_client():
    project = Path(__file__).resolve().parents[1]
    source = (
        project / "chitlog/ui/pages/settings.py"
    ).read_text(encoding="utf-8")

    assert "UpdateCheckRunner" in source
    assert "self._start_manual_update_check" in source
    assert "policy_from_preferences(preferences)" in source
    assert "UpdateDisposition.UP_TO_DATE" in source
    assert "UpdateDisposition.REQUIRED_UPDATE" in source

    for forbidden in (
        "http.client",
        "urllib.request",
        "requests",
        "httpx",
        "fetch_manifest_bytes",
    ):
        assert forbidden not in source


def test_policy_from_preferences_preserves_channel_and_interval():
    project = Path(__file__).resolve().parents[1]

    code = r"""
from types import SimpleNamespace

from chitlog.core.update_config import DEFAULT_MANIFEST_URL
from chitlog.ui.update_check_runner import policy_from_preferences

preferences = SimpleNamespace(
    channel="beta",
    check_interval_seconds=43200,
)
policy = policy_from_preferences(preferences)

assert policy.manifest_url == DEFAULT_MANIFEST_URL
assert policy.channel == "beta"
assert policy.check_interval_seconds == 43200
assert policy.request_timeout_seconds == 10
assert policy.max_manifest_bytes == 256 * 1024
assert policy.max_installer_bytes == 300 * 1024 * 1024
"""
    result = subprocess.run(
        [sys.executable, "-c", code],
        cwd=project,
        capture_output=True,
        text=True,
        timeout=20,
    )
    assert result.returncode == 0, result.stderr


def test_runner_executes_checker_off_gui_thread_and_reports_success():
    project = Path(__file__).resolve().parents[1]

    code = r"""
from types import SimpleNamespace

from PySide6.QtCore import QCoreApplication, QEventLoop, QThread, QTimer

from chitlog.core.update_config import UpdatePolicy
from chitlog.ui.update_check_runner import UpdateCheckRunner

app = QCoreApplication([])
gui_thread = QThread.currentThread()
state = {
    "worker_thread": None,
    "outcome": None,
    "finished": False,
}
expected = SimpleNamespace(decision=SimpleNamespace())

def checker(policy):
    state["worker_thread"] = QThread.currentThread()
    return expected

runner = UpdateCheckRunner(checker=checker)
runner.succeeded.connect(
    lambda outcome: state.__setitem__("outcome", outcome)
)
runner.finished.connect(
    lambda: state.__setitem__("finished", True)
)

loop = QEventLoop()
runner.finished.connect(loop.quit)
QTimer.singleShot(3000, loop.quit)

assert runner.start(UpdatePolicy(manifest_url=None)) is True
assert runner.start(UpdatePolicy(manifest_url=None)) is False
loop.exec()

assert state["finished"] is True
assert state["outcome"] is expected
assert state["worker_thread"] is not None
assert state["worker_thread"] is not gui_thread
assert runner.running is False

# Flush deferred QObject deletion before interpreter shutdown.
app.processEvents()
"""
    result = subprocess.run(
        [sys.executable, "-c", code],
        cwd=project,
        capture_output=True,
        text=True,
        timeout=20,
    )
    assert result.returncode == 0, (
        f"returncode={result.returncode}\n"
        f"stdout={result.stdout}\n"
        f"stderr={result.stderr}"
    )


def test_runner_normalizes_core_update_error_for_gui():
    project = Path(__file__).resolve().parents[1]

    code = r"""
from PySide6.QtCore import QCoreApplication, QEventLoop, QTimer

from chitlog.core.update_checker import (
    UpdateCheckError,
    UpdateCheckFailureKind,
)
from chitlog.core.update_config import UpdatePolicy
from chitlog.ui.update_check_runner import UpdateCheckRunner

app = QCoreApplication([])
state = {"failure": None}

def checker(policy):
    raise UpdateCheckError(
        UpdateCheckFailureKind.NETWORK,
        "safe network failure",
    )

runner = UpdateCheckRunner(checker=checker)
runner.failed.connect(
    lambda failure: state.__setitem__("failure", failure)
)

loop = QEventLoop()
runner.finished.connect(loop.quit)
QTimer.singleShot(3000, loop.quit)

assert runner.start(UpdatePolicy(manifest_url=None)) is True
loop.exec()

failure = state["failure"]
assert failure is not None
assert failure.kind == "network"
assert failure.message == "safe network failure"
assert runner.running is False
app.processEvents()
"""
    result = subprocess.run(
        [sys.executable, "-c", code],
        cwd=project,
        capture_output=True,
        text=True,
        timeout=20,
    )
    assert result.returncode == 0, (
        f"returncode={result.returncode}\n"
        f"stdout={result.stdout}\n"
        f"stderr={result.stderr}"
    )


def test_settings_button_runs_default_disabled_check_without_network():
    project = Path(__file__).resolve().parents[1]

    code = r"""
import secrets
import tempfile
from pathlib import Path

from PySide6.QtCore import QEventLoop, QTimer
from PySide6.QtWidgets import QApplication

from chitlog.core.security import hash_secret, hash_security_answer
from chitlog.data.database import Database
from chitlog.data.settings_repository import SettingsRepository
from chitlog.data.update_preferences_repository import UpdatePreferencesRepository
from chitlog.services.settings_service import SettingsService
from chitlog.services.update_preferences_service import UpdatePreferencesService
from chitlog.ui.pages.settings import SettingsPage

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

        page = SettingsPage(
            SettingsService(SettingsRepository(db)),
            update_preferences_service=UpdatePreferencesService(
                UpdatePreferencesRepository(db)
            ),
        )
        page.show()
        app.processEvents()

        assert page.check_updates_button.isEnabled() is True

        loop = QEventLoop()
        page.update_check_runner.finished.connect(loop.quit)
        page.check_updates_button.click()

        assert page.check_updates_button.isEnabled() is False

        QTimer.singleShot(3000, loop.quit)
        loop.exec()
        app.processEvents()

        assert page.update_check_runner.running is False
        assert page.check_updates_button.isEnabled() is True
        text = page.update_preferences_feedback.text().lower()
        assert "not configured yet" in text
        assert "offline" in text

        page.close()
        app.processEvents()
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
    assert result.returncode == 0, (
        f"returncode={result.returncode}\n"
        f"stdout={result.stdout}\n"
        f"stderr={result.stderr}"
    )


def test_unsaved_preferences_disable_manual_check_until_apply():
    project = Path(__file__).resolve().parents[1]
    source = (
        project / "chitlog/ui/pages/settings.py"
    ).read_text(encoding="utf-8")

    assert (
        "not changed and not self.update_check_runner.running"
        in source
    )
    assert (
        '"Save update preference changes before checking."'
        in source
    )
