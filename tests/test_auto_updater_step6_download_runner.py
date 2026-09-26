"""Step 6C tests for background verified installer downloads."""
from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys


def test_download_runner_runs_off_gui_thread_and_rejects_overlap():
    project = Path(__file__).resolve().parents[1]

    code = r"""
import hashlib
import threading
from pathlib import Path
import tempfile

from PySide6.QtCore import QCoreApplication, QEventLoop, QThread, QTimer

from chitlog.core.update_config import UpdatePolicy
from chitlog.core.update_decision import decide_update
from chitlog.core.update_installer_staging import VerifiedInstallerArtifact
from chitlog.core.update_manifest import UpdateManifestPayload
from chitlog.ui.update_download_runner import UpdateDownloadRunner

app = QCoreApplication([])
gui_thread = QThread.currentThread()
gate = threading.Event()
seen_worker = []

data = b"installer"
payload = UpdateManifestPayload.from_dict({
    "app": "ChitLog",
    "version": "1.2.0",
    "channel": "stable",
    "platform": "windows",
    "architecture": "x64",
    "published_at": "2026-09-26T00:00:00Z",
    "minimum_supported_version": "1.0.0",
    "installer_url": "https://downloads.example.test/ChitLog.exe",
    "installer_sha256": hashlib.sha256(data).hexdigest(),
    "installer_size": len(data),
    "release_notes_url": "https://chitlog.example.test/releases/1.2.0",
    "mandatory": False,
})
decision = decide_update(
    payload,
    current_version="1.1.0",
    policy=UpdatePolicy(channel="stable", manifest_url=None),
)

with tempfile.TemporaryDirectory() as d:
    destination = Path(d)

    def downloader(payload, destination_directory, policy):
        seen_worker.append(QThread.currentThread() is not gui_thread)
        gate.wait(2)
        path = Path(destination_directory) / "ChitLog-1.2.0-Setup.exe"
        path.write_bytes(data)
        return VerifiedInstallerArtifact(
            path=path,
            version="1.2.0",
            size_bytes=len(data),
            sha256=hashlib.sha256(data).hexdigest(),
        )

    runner = UpdateDownloadRunner(
        destination,
        policy=UpdatePolicy(manifest_url=None),
        downloader=downloader,
    )

    results = []
    failures = []
    loop = QEventLoop()
    runner.succeeded.connect(results.append)
    runner.failed.connect(failures.append)
    runner.finished.connect(loop.quit)

    assert runner.start(decision) is True
    assert runner.running is True
    assert runner.start(decision) is False

    gate.set()
    QTimer.singleShot(3000, loop.quit)
    loop.exec()

    assert seen_worker == [True]
    assert failures == []
    assert len(results) == 1
    assert results[0].version == "1.2.0"
    assert runner.running is False
"""
    result = subprocess.run(
        [sys.executable, "-c", code],
        cwd=project,
        capture_output=True,
        text=True,
        timeout=20,
    )
    assert result.returncode == 0, result.stderr


def test_download_runner_returns_safe_failure_messages():
    project = Path(__file__).resolve().parents[1]

    code = r"""
import hashlib
import tempfile
from pathlib import Path

from PySide6.QtCore import QCoreApplication, QEventLoop, QTimer

from chitlog.core.update_config import UpdatePolicy
from chitlog.core.update_decision import decide_update
from chitlog.core.update_installer_staging import InstallerHashError
from chitlog.core.update_manifest import UpdateManifestPayload
from chitlog.ui.update_download_runner import UpdateDownloadRunner

app = QCoreApplication([])

data = b"installer"
payload = UpdateManifestPayload.from_dict({
    "app": "ChitLog",
    "version": "1.2.0",
    "channel": "stable",
    "platform": "windows",
    "architecture": "x64",
    "published_at": "2026-09-26T00:00:00Z",
    "minimum_supported_version": "1.0.0",
    "installer_url": "https://downloads.example.test/ChitLog.exe",
    "installer_sha256": hashlib.sha256(data).hexdigest(),
    "installer_size": len(data),
    "release_notes_url": "https://chitlog.example.test/releases/1.2.0",
    "mandatory": False,
})
decision = decide_update(
    payload,
    current_version="1.1.0",
    policy=UpdatePolicy(channel="stable", manifest_url=None),
)

def downloader(*args, **kwargs):
    raise InstallerHashError("SECRET INTERNAL HASH DETAIL")

with tempfile.TemporaryDirectory() as d:
    runner = UpdateDownloadRunner(
        Path(d),
        downloader=downloader,
    )
    failures = []
    loop = QEventLoop()
    runner.failed.connect(failures.append)
    runner.finished.connect(loop.quit)

    assert runner.start(decision) is True
    QTimer.singleShot(3000, loop.quit)
    loop.exec()

    assert len(failures) == 1
    failure = failures[0]
    assert failure.kind == "verification"
    assert "failed verification" in failure.message
    assert "SECRET INTERNAL HASH DETAIL" not in failure.message
    assert runner.running is False
"""
    result = subprocess.run(
        [sys.executable, "-c", code],
        cwd=project,
        capture_output=True,
        text=True,
        timeout=20,
    )
    assert result.returncode == 0, result.stderr


def test_download_runner_rejects_up_to_date_decision():
    project = Path(__file__).resolve().parents[1]

    code = r"""
import hashlib
import tempfile
from pathlib import Path

from PySide6.QtCore import QCoreApplication

from chitlog.core.update_config import UpdatePolicy
from chitlog.core.update_decision import decide_update
from chitlog.core.update_manifest import UpdateManifestPayload
from chitlog.ui.update_download_runner import UpdateDownloadRunner

app = QCoreApplication([])
data = b"installer"

payload = UpdateManifestPayload.from_dict({
    "app": "ChitLog",
    "version": "1.1.0",
    "channel": "stable",
    "platform": "windows",
    "architecture": "x64",
    "published_at": "2026-09-26T00:00:00Z",
    "minimum_supported_version": "1.0.0",
    "installer_url": "https://downloads.example.test/ChitLog.exe",
    "installer_sha256": hashlib.sha256(data).hexdigest(),
    "installer_size": len(data),
    "release_notes_url": "https://chitlog.example.test/releases/1.1.0",
    "mandatory": False,
})
decision = decide_update(
    payload,
    current_version="1.1.0",
    policy=UpdatePolicy(channel="stable", manifest_url=None),
)

with tempfile.TemporaryDirectory() as d:
    runner = UpdateDownloadRunner(Path(d))
    try:
        runner.start(decision)
    except ValueError as exc:
        assert "up-to-date" in str(exc)
    else:
        raise AssertionError("up-to-date decision was accepted")
"""
    result = subprocess.run(
        [sys.executable, "-c", code],
        cwd=project,
        capture_output=True,
        text=True,
        timeout=20,
    )
    assert result.returncode == 0, result.stderr


def test_banner_download_states_are_nonblocking_and_retryable():
    project = Path(__file__).resolve().parents[1]

    code = r"""
import hashlib

from PySide6.QtWidgets import QApplication

from chitlog.core.update_config import UpdatePolicy
from chitlog.core.update_decision import decide_update
from chitlog.core.update_manifest import UpdateManifestPayload
from chitlog.ui.update_notification_banner import UpdateNotificationBanner

app = QApplication([])
data = b"installer"

payload = UpdateManifestPayload.from_dict({
    "app": "ChitLog",
    "version": "1.2.0",
    "channel": "stable",
    "platform": "windows",
    "architecture": "x64",
    "published_at": "2026-09-26T00:00:00Z",
    "minimum_supported_version": "1.0.0",
    "installer_url": "https://downloads.example.test/ChitLog.exe",
    "installer_sha256": hashlib.sha256(data).hexdigest(),
    "installer_size": len(data),
    "release_notes_url": "https://chitlog.example.test/releases/1.2.0",
    "mandatory": False,
})
decision = decide_update(
    payload,
    current_version="1.1.0",
    policy=UpdatePolicy(channel="stable", manifest_url=None),
)

banner = UpdateNotificationBanner()
assert banner.present(decision) is True
banner.enable_update_action(True)
assert banner.update_now_button.isEnabled() is True
assert banner.update_now_button.text() == "Update Now"

banner.begin_download()
assert banner.update_now_button.isEnabled() is False
assert banner.update_now_button.text() == "Downloading..."
assert banner.later_button.isEnabled() is False
assert "continue using ChitLog" in banner.message_label.text()

banner.show_download_failure("Safe retry message")
assert banner.update_now_button.isEnabled() is True
assert banner.update_now_button.text() == "Try Again"
assert banner.later_button.isEnabled() is True
assert banner.message_label.text() == "Safe retry message"

banner.begin_download()
banner.show_download_ready(object())
assert banner.update_now_button.isEnabled() is False
assert banner.update_now_button.text() == "Verified"
assert banner.later_button.isEnabled() is True
assert "SHA-256" in banner.message_label.text()
"""
    result = subprocess.run(
        [sys.executable, "-c", code],
        cwd=project,
        env=dict(os.environ, QT_QPA_PLATFORM="offscreen"),
        capture_output=True,
        text=True,
        timeout=20,
    )
    assert result.returncode == 0, result.stderr


def test_main_window_and_application_wire_shared_download_runner():
    project = Path(__file__).resolve().parents[1]
    main_window = (
        project / "chitlog/ui/main_window.py"
    ).read_text(encoding="utf-8")
    application = (
        project / "chitlog/application.py"
    ).read_text(encoding="utf-8")

    # Both MainWindow.__init__ and create_window must expose the optional
    # dependency. A single occurrence would let create_window forward an
    # undefined local variable and break every normal shell construction.
    assert main_window.count("update_download_runner=None") == 2

    for expected in (
        "self.update_download_runner = update_download_runner",
        "self.update_notification_banner.update_requested.connect(",
        "self._start_update_download",
        "self._update_download_succeeded",
        "self._update_download_failed",
        "update_download_runner=update_download_runner",
    ):
        assert expected in main_window

    for expected in (
        "from chitlog.ui.update_download_runner import UpdateDownloadRunner",
        'paths.cache / "updates"',
        "update_download_runner=update_download_runner",
    ):
        assert expected in application


def test_step6c_runner_has_no_installer_execution_or_financial_access():
    project = Path(__file__).resolve().parents[1]
    source = (
        project / "chitlog/ui/update_download_runner.py"
    ).read_text(encoding="utf-8")

    for forbidden in (
        "subprocess",
        "Popen",
        "os.startfile",
        "ShellExecute",
        "QProcess",
        "TransactionRepository",
        "WorkerRepository",
        "LiabilityRepository",
        "BudgetRepository",
        "Database(",
    ):
        assert forbidden not in source

    assert "download_installer_to_staging" in source
    assert "QThread" in source
    assert "aboutToQuit.connect(self.wait_for_finish)" in source
