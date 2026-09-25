"""Step 3A tests for ChitLog's offline update decision layer."""
from __future__ import annotations

from dataclasses import replace

import pytest

from chitlog.core.update_config import UpdatePolicy
from chitlog.core.update_decision import (
    UpdateDecisionError,
    UpdateDisposition,
    decide_update,
)
from chitlog.core.update_manifest import UpdateManifestPayload


def payload(
    *,
    version: str = "1.2.0",
    channel: str = "stable",
    minimum_supported_version: str = "1.1.0",
    installer_size: int = 82_000_000,
    mandatory: bool = False,
) -> UpdateManifestPayload:
    return UpdateManifestPayload.from_dict(
        {
            "app": "ChitLog",
            "version": version,
            "channel": channel,
            "platform": "windows",
            "architecture": "x64",
            "published_at": "2026-10-01T12:30:45Z",
            "minimum_supported_version": minimum_supported_version,
            "installer_url": (
                f"https://updates.example.test/ChitLog-{version}-Setup.exe"
            ),
            "installer_sha256": "a" * 64,
            "installer_size": installer_size,
            "release_notes_url": (
                f"https://updates.example.test/releases/{version}"
            ),
            "mandatory": mandatory,
        }
    )


def policy(
    *,
    channel: str = "stable",
    max_installer_bytes: int = 300 * 1024 * 1024,
) -> UpdatePolicy:
    return UpdatePolicy(
        manifest_url=None,
        channel=channel,
        max_installer_bytes=max_installer_bytes,
    )


def test_newer_release_is_optional_by_default():
    result = decide_update(
        payload(),
        current_version="1.1.0",
        policy=policy(),
    )

    assert result.disposition is UpdateDisposition.OPTIONAL_UPDATE
    assert result.update_available is True
    assert result.update_required is False
    assert result.current_version == "1.1.0"
    assert result.available_version == "1.2.0"
    assert result.below_minimum_supported is False


def test_mandatory_release_is_required():
    result = decide_update(
        payload(mandatory=True),
        current_version="1.1.0",
        policy=policy(),
    )

    assert result.disposition is UpdateDisposition.REQUIRED_UPDATE
    assert result.update_required is True
    assert result.mandatory is True


def test_running_version_below_minimum_supported_forces_required_update():
    result = decide_update(
        payload(
            version="2.0.0",
            minimum_supported_version="1.5.0",
            mandatory=False,
        ),
        current_version="1.1.0",
        policy=policy(),
    )

    assert result.disposition is UpdateDisposition.REQUIRED_UPDATE
    assert result.below_minimum_supported is True
    assert result.mandatory is False


@pytest.mark.parametrize(
    ("current", "available"),
    [
        ("1.1.0", "1.1.0"),
        ("1.2.0", "1.1.0"),
        ("2.0.0", "1.9.9"),
    ],
)
def test_same_or_newer_running_version_is_up_to_date(current, available):
    result = decide_update(
        payload(
            version=available,
            minimum_supported_version="1.0.0",
        ),
        current_version=current,
        policy=policy(),
    )

    assert result.disposition is UpdateDisposition.UP_TO_DATE
    assert result.update_available is False
    assert result.update_required is False


def test_channel_mismatch_is_rejected():
    with pytest.raises(UpdateDecisionError, match="channel"):
        decide_update(
            payload(channel="beta"),
            current_version="1.1.0",
            policy=policy(channel="stable"),
        )


def test_matching_beta_channel_is_accepted():
    result = decide_update(
        payload(channel="beta"),
        current_version="1.1.0",
        policy=policy(channel="beta"),
    )
    assert result.disposition is UpdateDisposition.OPTIONAL_UPDATE


def test_installer_larger_than_local_safety_limit_is_rejected():
    with pytest.raises(UpdateDecisionError, match="size"):
        decide_update(
            payload(installer_size=101),
            current_version="1.1.0",
            policy=policy(max_installer_bytes=100),
        )


def test_installer_exactly_at_local_safety_limit_is_allowed():
    result = decide_update(
        payload(installer_size=100),
        current_version="1.1.0",
        policy=policy(max_installer_bytes=100),
    )
    assert result.update_available is True


@pytest.mark.parametrize("current", ["1.1", "v1.1.0", "", "1.01.0"])
def test_invalid_running_version_is_rejected(current):
    with pytest.raises(UpdateDecisionError, match="Running"):
        decide_update(
            payload(),
            current_version=current,
            policy=policy(),
        )


def test_payload_type_is_enforced():
    with pytest.raises(TypeError):
        decide_update(
            {"version": "1.2.0"},
            current_version="1.1.0",
            policy=policy(),
        )


def test_policy_type_is_enforced():
    with pytest.raises(TypeError):
        decide_update(
            payload(),
            current_version="1.1.0",
            policy="stable",
        )


def test_verified_payload_is_preserved_on_result():
    verified_payload = payload()
    result = decide_update(
        verified_payload,
        current_version="1.1.0",
        policy=policy(),
    )
    assert result.payload is verified_payload
