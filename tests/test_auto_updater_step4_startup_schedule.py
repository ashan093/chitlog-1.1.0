"""Step 4D2 tests for startup automatic update-check wiring."""
from __future__ import annotations

from pathlib import Path
import subprocess
import sys


def test_startup_scheduler_source_has_no_network_client():
    project = Path(__file__).resolve().parents[1]
    source = (
        project / "chitlog/ui/startup_update_scheduler.py"
    ).read_text(encoding="utf-8")

    assert "StartupUpdateCheckScheduler" in source
    assert "schedule_service.snapshot()" in source
    assert "self.runner.start(policy)" in source
    assert "policy.manifest_url is None" in source

    for forbidden in (
        "http.client",
        "urllib.request",
        "requests",
        "httpx",
        "update_transport",
        "fetch_manifest_bytes",
    ):
        assert forbidden not in source


def test_scheduler_obeys_disabled_not_due_unconfigured_busy_and_due_states():
    project = Path(__file__).resolve().parents[1]
    code = r"""
from types import SimpleNamespace
from PySide6.QtCore import QCoreApplication, QObject, Signal
from chitlog.core.update_config import UpdatePolicy
from chitlog.ui.startup_update_scheduler import StartupUpdateCheckScheduler

app = QCoreApplication([])

class Preferences:
    def snapshot(self):
        return SimpleNamespace(channel="stable", check_interval_seconds=86400)

class Schedule:
    def __init__(self, enabled=True, due=True):
        self.enabled = enabled
        self.due = due
    def snapshot(self):
        return SimpleNamespace(auto_check_enabled=self.enabled, due=self.due)

class Runner(QObject):
    succeeded = Signal(object)
    failed = Signal(object)
    finished = Signal()
    def __init__(self, running=False):
        super().__init__()
        self.running = running
        self.started = []
    def start(self, policy):
        if self.running:
            return False
        self.running = True
        self.started.append(policy)
        return True

prefs = Preferences()
real = lambda p: UpdatePolicy(manifest_url="https://updates.example.test/manifest.json")
none = lambda p: UpdatePolicy(manifest_url=None)

runner = Runner()
s = StartupUpdateCheckScheduler(prefs, Schedule(False, True), runner, policy_builder=real)
assert s.run_if_due() is False and runner.started == []

runner = Runner()
s = StartupUpdateCheckScheduler(prefs, Schedule(True, False), runner, policy_builder=real)
assert s.run_if_due() is False and runner.started == []

runner = Runner()
s = StartupUpdateCheckScheduler(prefs, Schedule(True, True), runner, policy_builder=none)
assert s.run_if_due() is False and runner.started == []

runner = Runner(running=True)
s = StartupUpdateCheckScheduler(prefs, Schedule(True, True), runner, policy_builder=real)
assert s.run_if_due() is False and runner.started == []

runner = Runner()
s = StartupUpdateCheckScheduler(prefs, Schedule(True, True), runner, policy_builder=real)
assert s.run_if_due() is True
assert len(runner.started) == 1
assert s.run_if_due() is False
assert len(runner.started) == 1
"""
    result = subprocess.run(
        [sys.executable, "-c", code],
        cwd=project,
        capture_output=True,
        text=True,
        timeout=20,
    )
    assert result.returncode == 0, result.stderr


def test_shared_runner_records_only_real_started_checks():
    project = Path(__file__).resolve().parents[1]
    code = r"""
from types import SimpleNamespace
from PySide6.QtCore import QCoreApplication, QEventLoop, QTimer
from chitlog.core.update_config import UpdatePolicy
from chitlog.ui.update_check_runner import UpdateCheckRunner

app = QCoreApplication([])
recorded = []

def checker(policy):
    return SimpleNamespace(decision=SimpleNamespace())

def on_start(policy):
    recorded.append(policy.manifest_url)

runner = UpdateCheckRunner(checker=checker, on_real_check_start=on_start)

loop = QEventLoop()
runner.finished.connect(loop.quit)
assert runner.start(UpdatePolicy(manifest_url=None)) is True
QTimer.singleShot(3000, loop.quit)
loop.exec()
assert recorded == []
assert runner.running is False

loop = QEventLoop()
runner.finished.connect(loop.quit)
policy = UpdatePolicy(manifest_url="https://updates.example.test/manifest.json")
assert runner.start(policy) is True
QTimer.singleShot(3000, loop.quit)
loop.exec()
assert recorded == ["https://updates.example.test/manifest.json"]
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
    assert result.returncode == 0, result.stderr


def test_main_window_injects_one_shared_runner_into_settings():
    project = Path(__file__).resolve().parents[1]
    source = (project / "chitlog/ui/main_window.py").read_text(encoding="utf-8")
    assert "update_check_runner=None" in source
    assert "self.update_check_runner = update_check_runner" in source
    assert "update_check_runner=self.update_check_runner" in source


def test_application_wires_schedule_shared_runner_and_startup_timer():
    project = Path(__file__).resolve().parents[1]
    source = (project / "chitlog/application.py").read_text(encoding="utf-8")
    for expected in (
        "UpdateScheduleStateRepository",
        "UpdateScheduleService",
        "UpdateCheckRunner",
        "StartupUpdateCheckScheduler",
        "on_real_check_start=",
        "service.record_check_attempt()",
        "update_check_runner=update_check_runner",
        "startup_update_scheduler.run_if_due",
        "1500",
    ):
        assert expected in source


def test_manual_and_automatic_paths_share_the_same_runner_contract():
    project = Path(__file__).resolve().parents[1]
    settings = (project / "chitlog/ui/pages/settings.py").read_text(encoding="utf-8")
    main_window = (project / "chitlog/ui/main_window.py").read_text(encoding="utf-8")
    assert "update_check_runner=None" in settings
    assert "self.update_check_runner = (" in settings
    assert "update_check_runner=self.update_check_runner" in main_window


def test_startup_rule_uses_persisted_interval_due_state():
    project = Path(__file__).resolve().parents[1]
    scheduler = (project / "chitlog/ui/startup_update_scheduler.py").read_text(encoding="utf-8")
    service = (project / "chitlog/services/update_schedule_service.py").read_text(encoding="utf-8")
    assert "schedule_service.snapshot()" in scheduler
    assert "if not schedule.due:" in scheduler
    assert "last_attempt + timedelta(" in service
    assert "preferences.check_interval_seconds" in service
