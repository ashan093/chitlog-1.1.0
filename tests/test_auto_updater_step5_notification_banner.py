"""Step 5A tests for the verified update-available banner."""
from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys


def test_banner_source_has_no_update_transport_or_downloader():
    project = Path(__file__).resolve().parents[1]
    source = (
        project / "chitlog/ui/update_notification_banner.py"
    ).read_text(encoding="utf-8")

    assert "UpdateDecision" in source
    assert "UpdateDisposition" in source
    assert "QDesktopServices.openUrl" in source

    for forbidden in (
        "update_transport",
        "fetch_manifest_bytes",
        "check_for_updates(",
        "http.client",
        "urllib.request",
        "requests",
        "httpx",
        "subprocess",
        "installer_sha256",
    ):
        assert forbidden not in source


def test_optional_required_later_duplicate_and_up_to_date_behavior():
    project = Path(__file__).resolve().parents[1]

    code = r"""
from PySide6.QtWidgets import QApplication

from chitlog.core.update_config import UpdatePolicy
from chitlog.core.update_decision import (
    UpdateDisposition,
    decide_update,
)
from chitlog.core.update_manifest import UpdateManifestPayload
from chitlog.ui.update_notification_banner import UpdateNotificationBanner

app = QApplication([])

def payload(version, *, mandatory=False):
    return UpdateManifestPayload.from_dict({
        "app": "ChitLog",
        "version": version,
        "channel": "stable",
        "platform": "windows",
        "architecture": "x64",
        "published_at": "2026-09-26T00:00:00Z",
        "minimum_supported_version": "1.0.0",
        "installer_url": "https://updates.example.test/ChitLog-Setup.exe",
        "installer_sha256": "0" * 64,
        "installer_size": 123456,
        "release_notes_url": "https://chitlog.example.test/releases/" + version,
        "mandatory": mandatory,
    })

policy = UpdatePolicy(channel="stable", manifest_url=None)
banner = UpdateNotificationBanner()
banner.show()
banner.hide()

optional = decide_update(
    payload("1.2.0"),
    current_version="1.1.0",
    policy=policy,
)
assert optional.disposition is UpdateDisposition.OPTIONAL_UPDATE
assert banner.present(optional) is True
assert banner.isVisible() is True
assert banner.current_version == "1.2.0"
assert "1.2.0" in banner.title_label.text()
assert banner.eyebrow_label.text() == "UPDATE AVAILABLE"
assert banner.update_now_button.isEnabled() is False
assert banner.view_changes_button.isEnabled() is True
assert banner.later_button.isEnabled() is True

assert banner.present(optional) is False
assert banner.current_version == "1.2.0"

banner.dismiss_for_session()
assert banner.isVisible() is False
assert banner.present(optional) is False
assert banner.isVisible() is False

newer = decide_update(
    payload("1.3.0"),
    current_version="1.1.0",
    policy=policy,
)
assert banner.present(newer) is True
assert banner.isVisible() is True
assert banner.current_version == "1.3.0"

required = decide_update(
    payload("1.4.0", mandatory=True),
    current_version="1.1.0",
    policy=policy,
)
assert required.disposition is UpdateDisposition.REQUIRED_UPDATE
assert banner.present(required) is True
assert banner.isVisible() is True
assert banner.eyebrow_label.text() == "IMPORTANT UPDATE"
assert "required update" in banner.title_label.text().lower()
assert banner.later_button.isEnabled() is True

up_to_date = decide_update(
    payload("1.1.0"),
    current_version="1.1.0",
    policy=policy,
)
assert up_to_date.disposition is UpdateDisposition.UP_TO_DATE
assert banner.present(up_to_date) is False
assert banner.isVisible() is False
assert banner.decision is None
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


def test_release_notes_validation_requires_https_and_host():
    project = Path(__file__).resolve().parents[1]

    code = r"""
from dataclasses import replace

from chitlog.core.update_config import UpdatePolicy
from chitlog.core.update_decision import decide_update
from chitlog.core.update_manifest import UpdateManifestPayload
from chitlog.ui.update_notification_banner import UpdateNotificationBanner

payload = UpdateManifestPayload.from_dict({
    "app": "ChitLog",
    "version": "1.2.0",
    "channel": "stable",
    "platform": "windows",
    "architecture": "x64",
    "published_at": "2026-09-26T00:00:00Z",
    "minimum_supported_version": "1.0.0",
    "installer_url": "https://updates.example.test/ChitLog-Setup.exe",
    "installer_sha256": "0" * 64,
    "installer_size": 123456,
    "release_notes_url": "https://chitlog.example.test/releases/1.2.0",
    "mandatory": False,
})
decision = decide_update(
    payload,
    current_version="1.1.0",
    policy=UpdatePolicy(channel="stable", manifest_url=None),
)

valid = UpdateNotificationBanner._release_notes_url(decision)
assert valid is not None
assert valid.scheme().lower() == "https"

unsafe_payload = replace(
    decision.payload,
    release_notes_url="http://example.test/release",
)
unsafe_decision = replace(decision, payload=unsafe_payload)
assert (
    UpdateNotificationBanner._release_notes_url(unsafe_decision)
    is None
)
"""
    result = subprocess.run(
        [sys.executable, "-c", code],
        cwd=project,
        capture_output=True,
        text=True,
        timeout=20,
    )
    assert result.returncode == 0, result.stderr


def test_main_window_subscribes_to_shared_verified_runner():
    project = Path(__file__).resolve().parents[1]
    source = (
        project / "chitlog/ui/main_window.py"
    ).read_text(encoding="utf-8")

    assert "UpdateNotificationBanner" in source
    assert "self.update_notification_banner" in source
    assert "self.update_check_runner.succeeded.connect(" in source
    assert "self._secure_update_check_succeeded" in source
    assert "self.update_notification_banner.present(decision)" in source


def test_step5a_does_not_change_update_check_privacy_semantics():
    project = Path(__file__).resolve().parents[1]
    banner = (
        project / "chitlog/ui/update_notification_banner.py"
    ).read_text(encoding="utf-8")
    main_window = (
        project / "chitlog/ui/main_window.py"
    ).read_text(encoding="utf-8")

    combined = banner + "\n" + main_window

    assert "check_for_updates(" not in combined
    assert "fetch_manifest_bytes" not in combined
    assert "http.client" not in banner
