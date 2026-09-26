"""Step 7D tests for main-app handoff to the standalone updater."""
from __future__ import annotations

import base64
import hashlib
import json
import os
from pathlib import Path
import struct
import subprocess
import sys

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from chitlog.core.update_handoff import load_and_verify_update_handoff
from chitlog.core.update_installer_staging import VerifiedInstallerArtifact
from chitlog.core.update_manifest import SignedUpdateManifest, UpdateManifestPayload
from chitlog.core.update_updater_launch import (
    StagedUpdaterExecutable,
    UpdaterNotPackagedError,
    UpdaterProcessLaunchError,
    packaged_updater_available,
    prepare_and_launch_updater,
    resolve_packaged_updater,
    stage_packaged_updater,
)


def write_minimal_pe(path: Path, *, machine: int = 0x014C) -> None:
    data = bytearray(512)
    data[0:2] = b"MZ"
    pe_offset = 0x80
    struct.pack_into("<I", data, 0x3C, pe_offset)
    data[pe_offset : pe_offset + 4] = b"PE\x00\x00"
    struct.pack_into("<H", data, pe_offset + 4, machine)
    path.write_bytes(bytes(data))


def signed_manifest_for(data: bytes, *, version: str = "1.2.0"):
    private_key = Ed25519PrivateKey.generate()
    public_key = private_key.public_key().public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )

    payload = UpdateManifestPayload.from_dict({
        "app": "ChitLog",
        "version": version,
        "channel": "stable",
        "platform": "windows",
        "architecture": "x64",
        "published_at": "2026-09-26T00:00:00Z",
        "minimum_supported_version": "1.0.0",
        "installer_url": "https://downloads.example.test/ChitLog.exe",
        "installer_sha256": hashlib.sha256(data).hexdigest(),
        "installer_size": len(data),
        "release_notes_url": (
            f"https://chitlog.example.test/releases/{version}"
        ),
        "mandatory": False,
    })

    signature = private_key.sign(payload.canonical_bytes())
    manifest = SignedUpdateManifest.from_dict({
        "schema_version": 1,
        "key_id": "test-key",
        "payload": payload.to_dict(),
        "signature": base64.b64encode(signature).decode("ascii"),
    })
    return manifest, {"test-key": public_key}


def local_update_files(tmp_path: Path, data: bytes):
    install_dir = tmp_path / "program"
    install_dir.mkdir()
    app = install_dir / "ChitLog.exe"
    app.write_bytes(b"running ChitLog executable")

    packaged_updater = install_dir / "ChitLogUpdater.exe"
    write_minimal_pe(packaged_updater)

    staging = tmp_path / "cache" / "updates"
    staging.mkdir(parents=True)
    installer = staging / "ChitLog-1.2.0-Setup.exe"
    installer.write_bytes(data)
    artifact = VerifiedInstallerArtifact(
        path=installer,
        version="1.2.0",
        size_bytes=len(data),
        sha256=hashlib.sha256(data).hexdigest(),
    )
    return app, packaged_updater, staging, artifact


def test_resolve_packaged_updater_requires_exact_sibling_name(tmp_path):
    app_dir = tmp_path / "program"
    app_dir.mkdir()
    app = app_dir / "ChitLog.exe"
    app.write_bytes(b"app")

    with pytest.raises(UpdaterNotPackagedError):
        resolve_packaged_updater(app.resolve())

    updater = app_dir / "ChitLogUpdater.exe"
    write_minimal_pe(updater)

    assert resolve_packaged_updater(app.resolve()) == updater.resolve()
    assert packaged_updater_available(app.resolve()) is True


def test_stage_packaged_updater_copies_and_rechecks_exact_bytes(tmp_path):
    source = (tmp_path / "program" / "ChitLogUpdater.exe")
    source.parent.mkdir()
    write_minimal_pe(source, machine=0x8664)

    destination = tmp_path / "cache" / "updates"
    staged = stage_packaged_updater(
        source.resolve(),
        destination,
        target_version="1.2.0",
    )

    assert isinstance(staged, StagedUpdaterExecutable)
    assert staged.path.name == "ChitLogUpdater-1.2.0.exe"
    assert staged.path.parent == destination.resolve()
    assert staged.path.read_bytes() == source.read_bytes()
    assert staged.sha256 == hashlib.sha256(source.read_bytes()).hexdigest()
    assert list(destination.glob("*.part")) == []


def test_prepare_and_launch_creates_verified_handoff_and_staged_updater(tmp_path):
    installer_data = b"verified release installer" * 100
    manifest, trusted = signed_manifest_for(installer_data)
    app, packaged_updater, staging, artifact = local_update_files(
        tmp_path,
        installer_data,
    )

    seen = {}

    def fake_launcher(staged_updater, handoff_path):
        seen["staged"] = staged_updater
        seen["handoff"] = handoff_path
        assert staged_updater.path != packaged_updater.resolve()
        assert staged_updater.path.parent == staging.resolve()
        assert handoff_path.parent == staging.resolve()
        return 43210

    result = prepare_and_launch_updater(
        manifest,
        artifact,
        app.resolve(),
        staging,
        parent_pid=2468,
        trusted_keys=trusted,
        current_version="1.1.0",
        launcher=fake_launcher,
    )

    assert result.process_id == 43210
    assert result.target_version == "1.2.0"
    assert result.updater_path == seen["staged"].path
    assert result.handoff_path == seen["handoff"]

    verified = load_and_verify_update_handoff(
        result.handoff_path,
        trusted_keys=trusted,
        current_version="1.1.0",
    )
    assert verified.handoff.parent_pid == 2468
    assert verified.payload.version == "1.2.0"
    assert verified.application_path == app.resolve()


def test_launch_failure_cleans_new_handoff_and_staged_updater(tmp_path):
    installer_data = b"verified release installer"
    manifest, trusted = signed_manifest_for(installer_data)
    app, _packaged_updater, staging, artifact = local_update_files(
        tmp_path,
        installer_data,
    )

    def fail_launch(staged_updater, handoff_path):
        raise UpdaterProcessLaunchError("simulated")

    with pytest.raises(UpdaterProcessLaunchError):
        prepare_and_launch_updater(
            manifest,
            artifact,
            app.resolve(),
            staging,
            parent_pid=2468,
            trusted_keys=trusted,
            current_version="1.1.0",
            launcher=fail_launch,
        )

    assert list(staging.glob("*handoff.json")) == []
    assert list(staging.glob("ChitLogUpdater-*.exe")) == []
    assert artifact.path.is_file()


def test_install_runner_operates_off_gui_thread_and_blocks_overlap(tmp_path):
    import importlib.util

    if importlib.util.find_spec("PySide6") is None:
        pytest.skip("PySide6 is unavailable in this validation environment.")

    project = Path(__file__).resolve().parents[1]

    code = r'''
import base64
import hashlib
from pathlib import Path
import tempfile
import threading

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from PySide6.QtCore import QCoreApplication, QEventLoop, QThread, QTimer

from chitlog.core.update_checker import UpdateCheckOutcome
from chitlog.core.update_config import UpdatePolicy
from chitlog.core.update_decision import decide_update
from chitlog.core.update_installer_staging import VerifiedInstallerArtifact
from chitlog.core.update_manifest import SignedUpdateManifest, UpdateManifestPayload
from chitlog.core.update_updater_launch import UpdaterLaunchResult
from chitlog.ui.update_install_runner import UpdateInstallRunner

app = QCoreApplication([])
gui_thread = QThread.currentThread()
gate = threading.Event()
seen = []

data = b"installer"
private = Ed25519PrivateKey.generate()
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
manifest = SignedUpdateManifest.from_dict({
    "schema_version": 1,
    "key_id": "test-key",
    "payload": payload.to_dict(),
    "signature": base64.b64encode(
        private.sign(payload.canonical_bytes())
    ).decode("ascii"),
})
decision = decide_update(
    payload,
    current_version="1.1.0",
    policy=UpdatePolicy(channel="stable"),
)
outcome = UpdateCheckOutcome(decision=decision, manifest=manifest)

with tempfile.TemporaryDirectory() as d:
    root = Path(d)
    installer = root / "ChitLog-1.2.0-Setup.exe"
    installer.write_bytes(data)
    artifact = VerifiedInstallerArtifact(
        path=installer,
        version="1.2.0",
        size_bytes=len(data),
        sha256=hashlib.sha256(data).hexdigest(),
    )

    def coordinator(manifest, artifact, application_path, destination_directory, *, parent_pid):
        seen.append(QThread.currentThread() is not gui_thread)
        gate.wait(2)
        return UpdaterLaunchResult(
            updater_path=root / "ChitLogUpdater-1.2.0.exe",
            handoff_path=root / "handoff.json",
            target_version="1.2.0",
            process_id=999,
        )

    runner = UpdateInstallRunner(
        root,
        root / "ChitLog.exe",
        coordinator=coordinator,
        parent_pid=123,
    )
    results = []
    failures = []
    loop = QEventLoop()
    runner.succeeded.connect(results.append)
    runner.failed.connect(failures.append)
    runner.finished.connect(loop.quit)

    assert runner.start(outcome, artifact) is True
    assert runner.running is True
    assert runner.start(outcome, artifact) is False
    gate.set()
    QTimer.singleShot(3000, loop.quit)
    loop.exec()

    assert seen == [True]
    assert failures == []
    assert len(results) == 1
    assert results[0].process_id == 999
    assert runner.running is False
'''

    result = subprocess.run(
        [sys.executable, "-c", code],
        cwd=project,
        capture_output=True,
        text=True,
        timeout=20,
    )
    assert result.returncode == 0, result.stderr


def test_step7d_ui_and_application_wiring_is_present():
    project = Path(__file__).resolve().parents[1]
    main_window = (
        project / "chitlog/ui/main_window.py"
    ).read_text(encoding="utf-8")
    banner = (
        project / "chitlog/ui/update_notification_banner.py"
    ).read_text(encoding="utf-8")
    application = (
        project / "chitlog/application.py"
    ).read_text(encoding="utf-8")

    assert main_window.count("update_install_runner=None") == 2
    for expected in (
        "self._verified_update_outcome = None",
        "self._verified_installer_artifact = None",
        "install_requested.connect(",
        "self._start_update_install",
        "self._confirm_update_install",
        '"Install Update"',
        "self._update_install_started",
        "QTimer.singleShot(0, app.quit)",
        "self._update_install_failed",
        "update_install_runner=update_install_runner",
    ):
        assert expected in main_window

    for expected in (
        "install_requested = Signal(object)",
        "self._installer_ready = False",
        'self.update_now_button.setText("Install Update")',
        "def begin_install(self)",
        "def show_install_failure(self, message: str)",
    ):
        assert expected in banner

    for expected in (
        "from chitlog.ui.update_install_runner import UpdateInstallRunner",
        "update_install_runner = UpdateInstallRunner(",
        'paths.cache / "updates"',
        "Path(sys.executable).resolve()",
        "update_install_runner=update_install_runner",
    ):
        assert expected in application


def test_step7d_launcher_has_no_command_shell_or_untrusted_process_api():
    project = Path(__file__).resolve().parents[1]
    source = (
        project / "chitlog/core/update_updater_launch.py"
    ).read_text(encoding="utf-8")

    assert 'info.lpVerb = "open"' in source
    assert 'UPDATER_EXECUTABLE_NAME = "ChitLogUpdater.exe"' in source
    assert 'return f\'--handoff "{text}"\'' in source
    assert "create_update_handoff(" in source
    assert "write_update_handoff(" in source
    assert "_verify_staged_updater(staged_updater)" in source

    for forbidden in (
        "subprocess",
        "Popen",
        "os.system",
        "os.startfile",
        "cmd.exe",
        "powershell",
        "shell=True",
        "TerminateProcess",
    ):
        assert forbidden not in source
