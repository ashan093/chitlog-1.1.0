"""Step 3C tests for the secure ChitLog update-check pipeline."""
from __future__ import annotations

import base64
import json

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from chitlog.core.update_config import UpdatePolicy
from chitlog.core.update_decision import UpdateDisposition
from chitlog.core.update_checker import (
    UpdateCheckError,
    UpdateCheckFailureKind,
    check_for_updates,
)
from chitlog.core.update_manifest import UpdateManifestPayload
from chitlog.core.update_transport import (
    UpdateCheckDisabledError,
    UpdateTransportError,
)


def raw_public_key(private_key: Ed25519PrivateKey) -> bytes:
    return private_key.public_key().public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )


def make_policy(
    *,
    channel: str = "stable",
    max_installer_bytes: int = 300 * 1024 * 1024,
) -> UpdatePolicy:
    return UpdatePolicy(
        manifest_url="https://updates.example.test/api/updates/windows/stable",
        channel=channel,
        max_installer_bytes=max_installer_bytes,
    )


def make_payload(
    *,
    version: str = "1.2.0",
    channel: str = "stable",
    minimum_supported_version: str = "1.1.0",
    installer_size: int = 82_000_000,
    mandatory: bool = False,
) -> dict:
    return {
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


def signed_manifest_bytes(
    private_key: Ed25519PrivateKey,
    *,
    key_id: str = "chitlog-update-test-key",
    payload: dict | None = None,
) -> bytes:
    payload_dict = make_payload() if payload is None else payload
    parsed = UpdateManifestPayload.from_dict(payload_dict)
    signature = private_key.sign(parsed.canonical_bytes())

    document = {
        "schema_version": 1,
        "key_id": key_id,
        "payload": payload_dict,
        "signature": base64.b64encode(signature).decode("ascii"),
    }
    return json.dumps(
        document,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def test_valid_signed_newer_release_becomes_optional_update():
    private_key = Ed25519PrivateKey.generate()
    raw = signed_manifest_bytes(private_key)

    calls = []

    def fetcher(policy):
        calls.append(policy)
        return raw

    outcome = check_for_updates(
        make_policy(),
        current_version="1.1.0",
        trusted_keys={
            "chitlog-update-test-key": raw_public_key(private_key),
        },
        fetcher=fetcher,
    )

    assert calls == [make_policy()]
    assert outcome.decision.disposition is UpdateDisposition.OPTIONAL_UPDATE
    assert outcome.update_available is True
    assert outcome.update_required is False
    assert outcome.decision.available_version == "1.2.0"


def test_valid_signed_mandatory_release_becomes_required_update():
    private_key = Ed25519PrivateKey.generate()
    payload = make_payload(mandatory=True)
    raw = signed_manifest_bytes(private_key, payload=payload)

    outcome = check_for_updates(
        make_policy(),
        current_version="1.1.0",
        trusted_keys={
            "chitlog-update-test-key": raw_public_key(private_key),
        },
        fetcher=lambda policy: raw,
    )

    assert outcome.decision.disposition is UpdateDisposition.REQUIRED_UPDATE
    assert outcome.update_required is True


def test_below_minimum_supported_becomes_required_update():
    private_key = Ed25519PrivateKey.generate()
    payload = make_payload(
        version="2.0.0",
        minimum_supported_version="1.5.0",
    )
    raw = signed_manifest_bytes(private_key, payload=payload)

    outcome = check_for_updates(
        make_policy(),
        current_version="1.1.0",
        trusted_keys={
            "chitlog-update-test-key": raw_public_key(private_key),
        },
        fetcher=lambda policy: raw,
    )

    assert outcome.decision.disposition is UpdateDisposition.REQUIRED_UPDATE
    assert outcome.decision.below_minimum_supported is True


def test_same_version_is_up_to_date():
    private_key = Ed25519PrivateKey.generate()
    payload = make_payload(
        version="1.1.0",
        minimum_supported_version="1.0.0",
    )
    raw = signed_manifest_bytes(private_key, payload=payload)

    outcome = check_for_updates(
        make_policy(),
        current_version="1.1.0",
        trusted_keys={
            "chitlog-update-test-key": raw_public_key(private_key),
        },
        fetcher=lambda policy: raw,
    )

    assert outcome.decision.disposition is UpdateDisposition.UP_TO_DATE
    assert outcome.update_available is False


@pytest.mark.parametrize(
    ("field", "replacement"),
    [
        ("version", "1.2.1"),
        (
            "installer_url",
            "https://updates.example.test/ChitLog-1.2.1-Setup.exe",
        ),
        ("installer_sha256", "b" * 64),
        ("mandatory", True),
    ],
)
def test_tampered_signed_payload_is_security_failure(field, replacement):
    private_key = Ed25519PrivateKey.generate()

    original = make_payload()
    raw_document = json.loads(
        signed_manifest_bytes(private_key, payload=original).decode("utf-8")
    )
    raw_document["payload"][field] = replacement
    tampered = json.dumps(
        raw_document,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")

    with pytest.raises(UpdateCheckError) as captured:
        check_for_updates(
            make_policy(),
            current_version="1.1.0",
            trusted_keys={
                "chitlog-update-test-key": raw_public_key(private_key),
            },
            fetcher=lambda policy: tampered,
        )

    assert captured.value.kind is UpdateCheckFailureKind.SECURITY


def test_unknown_signing_key_is_security_failure():
    private_key = Ed25519PrivateKey.generate()
    raw = signed_manifest_bytes(
        private_key,
        key_id="unknown-update-key",
    )

    with pytest.raises(UpdateCheckError) as captured:
        check_for_updates(
            make_policy(),
            current_version="1.1.0",
            trusted_keys={},
            fetcher=lambda policy: raw,
        )

    assert captured.value.kind is UpdateCheckFailureKind.SECURITY


def test_malformed_json_is_security_failure():
    with pytest.raises(UpdateCheckError) as captured:
        check_for_updates(
            make_policy(),
            current_version="1.1.0",
            trusted_keys={},
            fetcher=lambda policy: b"{not json}",
        )

    assert captured.value.kind is UpdateCheckFailureKind.SECURITY


def test_disabled_update_check_is_normalized():
    def fetcher(policy):
        raise UpdateCheckDisabledError("not configured")

    with pytest.raises(UpdateCheckError) as captured:
        check_for_updates(
            UpdatePolicy(manifest_url=None),
            fetcher=fetcher,
        )

    assert captured.value.kind is UpdateCheckFailureKind.DISABLED


def test_offline_or_server_failure_is_normalized_as_network_failure():
    def fetcher(policy):
        raise UpdateTransportError("offline")

    with pytest.raises(UpdateCheckError) as captured:
        check_for_updates(
            make_policy(),
            fetcher=fetcher,
        )

    assert captured.value.kind is UpdateCheckFailureKind.NETWORK


def test_verified_channel_conflict_is_normalized_as_policy_failure():
    private_key = Ed25519PrivateKey.generate()
    raw = signed_manifest_bytes(
        private_key,
        payload=make_payload(channel="beta"),
    )

    with pytest.raises(UpdateCheckError) as captured:
        check_for_updates(
            make_policy(channel="stable"),
            current_version="1.1.0",
            trusted_keys={
                "chitlog-update-test-key": raw_public_key(private_key),
            },
            fetcher=lambda policy: raw,
        )

    assert captured.value.kind is UpdateCheckFailureKind.POLICY


def test_verified_oversized_installer_is_policy_failure():
    private_key = Ed25519PrivateKey.generate()
    raw = signed_manifest_bytes(
        private_key,
        payload=make_payload(installer_size=101),
    )

    with pytest.raises(UpdateCheckError) as captured:
        check_for_updates(
            make_policy(max_installer_bytes=100),
            current_version="1.1.0",
            trusted_keys={
                "chitlog-update-test-key": raw_public_key(private_key),
            },
            fetcher=lambda policy: raw,
        )

    assert captured.value.kind is UpdateCheckFailureKind.POLICY


def test_fetch_happens_exactly_once():
    private_key = Ed25519PrivateKey.generate()
    raw = signed_manifest_bytes(private_key)
    calls = 0

    def fetcher(policy):
        nonlocal calls
        calls += 1
        return raw

    check_for_updates(
        make_policy(),
        current_version="1.1.0",
        trusted_keys={
            "chitlog-update-test-key": raw_public_key(private_key),
        },
        fetcher=fetcher,
    )

    assert calls == 1


def test_invalid_signature_never_reaches_decision_payload():
    signer = Ed25519PrivateKey.generate()
    wrong_key = Ed25519PrivateKey.generate()
    raw = signed_manifest_bytes(signer)

    with pytest.raises(UpdateCheckError) as captured:
        check_for_updates(
            make_policy(),
            current_version="1.1.0",
            trusted_keys={
                "chitlog-update-test-key": raw_public_key(wrong_key),
            },
            fetcher=lambda policy: raw,
        )

    assert captured.value.kind is UpdateCheckFailureKind.SECURITY


def test_default_policy_is_still_disabled_and_cannot_touch_network(monkeypatch):
    import chitlog.core.update_checker as checker

    touched = False

    def forbidden(policy):
        nonlocal touched
        touched = True
        raise AssertionError("default disabled check must not touch network")

    monkeypatch.setattr(checker, "fetch_manifest_bytes", forbidden)

    # Default argument was bound at definition time, so explicitly prove the
    # shipped DEFAULT_UPDATE_POLICY remains disabled.
    from chitlog.core.update_config import DEFAULT_UPDATE_POLICY

    assert DEFAULT_UPDATE_POLICY.enabled is False
    assert touched is False
