"""Step 2A tests for the signed ChitLog update-manifest format."""
from __future__ import annotations

import base64
import json

import pytest

from chitlog.core.update_manifest import (
    MANIFEST_SCHEMA_VERSION,
    SignedUpdateManifest,
    UpdateManifestError,
    UpdateManifestPayload,
    canonical_payload_bytes,
)


def valid_payload():
    return {
        "app": "ChitLog",
        "version": "1.2.0",
        "channel": "stable",
        "platform": "windows",
        "architecture": "x64",
        "published_at": "2026-10-01T12:30:45Z",
        "minimum_supported_version": "1.1.0",
        "installer_url": "https://updates.example.test/ChitLog-1.2.0-Setup.exe",
        "installer_sha256": "a" * 64,
        "installer_size": 82_000_000,
        "release_notes_url": "https://updates.example.test/releases/1.2.0",
        "mandatory": False,
    }


def valid_manifest():
    return {
        "schema_version": MANIFEST_SCHEMA_VERSION,
        "key_id": "chitlog-update-2026-01",
        "payload": valid_payload(),
        "signature": base64.b64encode(b"s" * 64).decode("ascii"),
    }


def test_valid_payload_round_trips_and_has_deterministic_canonical_bytes():
    payload = UpdateManifestPayload.from_dict(valid_payload())

    first = payload.canonical_bytes()
    reordered = dict(reversed(list(valid_payload().items())))
    second = canonical_payload_bytes(reordered)

    assert first == second
    assert json.loads(first.decode("utf-8")) == valid_payload()
    assert b" " not in first
    assert b"\n" not in first


def test_valid_signed_manifest_parses_from_utf8_json_bytes():
    manifest = SignedUpdateManifest.from_json_bytes(
        json.dumps(valid_manifest(), ensure_ascii=False).encode("utf-8")
    )
    assert manifest.schema_version == 1
    assert manifest.key_id == "chitlog-update-2026-01"
    assert manifest.payload.version == "1.2.0"
    assert manifest.signature == b"s" * 64
    assert manifest.signed_bytes() == manifest.payload.canonical_bytes()


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("app", "OtherApp"),
        ("version", "v1.2.0"),
        ("channel", "nightly"),
        ("platform", "linux"),
        ("architecture", "arm64"),
        ("published_at", "2026-10-01T12:30:45+05:30"),
        ("installer_url", "http://updates.example.test/setup.exe"),
        ("installer_url", "https://user:pw@updates.example.test/setup.exe"),
        ("installer_url", "https://updates.example.test/setup.exe#fragment"),
        ("installer_sha256", "A" * 64),
        ("installer_sha256", "a" * 63),
        ("installer_size", 0),
        ("installer_size", -1),
        ("installer_size", True),
        ("mandatory", "false"),
        ("release_notes_url", "http://updates.example.test/release"),
    ],
)
def test_payload_rejects_invalid_values(field, value):
    payload = valid_payload()
    payload[field] = value
    with pytest.raises(UpdateManifestError):
        UpdateManifestPayload.from_dict(payload)


def test_minimum_supported_version_cannot_be_newer_than_release():
    payload = valid_payload()
    payload["minimum_supported_version"] = "2.0.0"
    with pytest.raises(UpdateManifestError):
        UpdateManifestPayload.from_dict(payload)


@pytest.mark.parametrize("mutation", ["missing", "unknown"])
def test_payload_requires_exact_field_set(mutation):
    payload = valid_payload()
    if mutation == "missing":
        payload.pop("mandatory")
    else:
        payload["unexpected"] = "value"
    with pytest.raises(UpdateManifestError):
        UpdateManifestPayload.from_dict(payload)


@pytest.mark.parametrize("mutation", ["missing", "unknown"])
def test_manifest_requires_exact_field_set(mutation):
    manifest = valid_manifest()
    if mutation == "missing":
        manifest.pop("key_id")
    else:
        manifest["unexpected"] = "value"
    with pytest.raises(UpdateManifestError):
        SignedUpdateManifest.from_dict(manifest)


@pytest.mark.parametrize("schema", [0, 2, True, "1"])
def test_manifest_rejects_wrong_schema_version(schema):
    manifest = valid_manifest()
    manifest["schema_version"] = schema
    with pytest.raises(UpdateManifestError):
        SignedUpdateManifest.from_dict(manifest)


@pytest.mark.parametrize(
    "key_id",
    [
        "",
        " space",
        "has space",
        "slash/key",
        "x" * 65,
    ],
)
def test_manifest_rejects_invalid_key_id(key_id):
    manifest = valid_manifest()
    manifest["key_id"] = key_id
    with pytest.raises(UpdateManifestError):
        SignedUpdateManifest.from_dict(manifest)


@pytest.mark.parametrize(
    "signature",
    [
        "",
        "***not-base64***",
        base64.b64encode(b"x" * 63).decode("ascii"),
        base64.b64encode(b"x" * 65).decode("ascii"),
    ],
)
def test_manifest_rejects_invalid_ed25519_signature_shape(signature):
    manifest = valid_manifest()
    manifest["signature"] = signature
    with pytest.raises(UpdateManifestError):
        SignedUpdateManifest.from_dict(manifest)


def test_manifest_rejects_bom_invalid_utf8_and_invalid_json():
    with pytest.raises(UpdateManifestError):
        SignedUpdateManifest.from_json_bytes(
            b"\xef\xbb\xbf" + json.dumps(valid_manifest()).encode("utf-8")
        )

    with pytest.raises(UpdateManifestError):
        SignedUpdateManifest.from_json_bytes(b"\xff\xfe")

    with pytest.raises(UpdateManifestError):
        SignedUpdateManifest.from_json_bytes(b"{not json}")


def test_canonical_payload_handles_unicode_deterministically():
    payload = valid_payload()
    payload["release_notes_url"] = (
        "https://updates.example.test/releases/1.2.0?lang=en"
    )
    parsed = UpdateManifestPayload.from_dict(payload)
    assert parsed.canonical_bytes() == canonical_payload_bytes(parsed.to_dict())
