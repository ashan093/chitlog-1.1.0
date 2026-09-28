"""Step 2B2 tests for ChitLog Ed25519 update-manifest verification."""
from __future__ import annotations

import base64
import copy
import json
from pathlib import Path

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from chitlog.core.update_manifest import (
    MANIFEST_SCHEMA_VERSION,
    SignedUpdateManifest,
    UpdateManifestPayload,
)
from chitlog.core.update_signature import (
    InvalidTrustedKeyError,
    InvalidUpdateSignatureError,
    PRODUCTION_UPDATE_KEY_ID,
    PRODUCTION_UPDATE_PUBLIC_KEY_SHA256,
    TRUSTED_UPDATE_PUBLIC_KEYS,
    UnknownUpdateKeyError,
    parse_and_verify_manifest,
    validate_trusted_key_registry,
    verify_manifest_signature,
)


ROOT = Path(__file__).resolve().parents[1]


def raw_public_key(private_key: Ed25519PrivateKey) -> bytes:
    return private_key.public_key().public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )


def payload_dict():
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


def signed_manifest_dict(
    private_key: Ed25519PrivateKey,
    *,
    key_id: str = "chitlog-update-2026-01",
    payload: dict | None = None,
):
    source_payload = payload_dict() if payload is None else payload
    parsed = UpdateManifestPayload.from_dict(source_payload)
    signature = private_key.sign(parsed.canonical_bytes())

    return {
        "schema_version": MANIFEST_SCHEMA_VERSION,
        "key_id": key_id,
        "payload": source_payload,
        "signature": base64.b64encode(signature).decode("ascii"),
    }


def signed_manifest(private_key: Ed25519PrivateKey, **kwargs):
    return SignedUpdateManifest.from_dict(
        signed_manifest_dict(private_key, **kwargs)
    )


def test_valid_signature_returns_verified_payload():
    private_key = Ed25519PrivateKey.generate()
    manifest = signed_manifest(private_key)

    verified = verify_manifest_signature(
        manifest,
        trusted_keys={
            "chitlog-update-2026-01": raw_public_key(private_key),
        },
    )

    assert verified.version == "1.2.0"
    assert verified.installer_sha256 == "a" * 64


def test_parse_and_verify_enforces_parse_then_signature_boundary():
    private_key = Ed25519PrivateKey.generate()
    document = signed_manifest_dict(private_key)

    verified = parse_and_verify_manifest(
        json.dumps(document).encode("utf-8"),
        trusted_keys={
            "chitlog-update-2026-01": raw_public_key(private_key),
        },
    )
    assert verified.version == "1.2.0"


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
def test_signed_payload_tampering_is_rejected(field, replacement):
    private_key = Ed25519PrivateKey.generate()
    document = signed_manifest_dict(private_key)

    # Modify the payload only after the original signature was created.
    document["payload"][field] = replacement
    manifest = SignedUpdateManifest.from_dict(document)

    with pytest.raises(InvalidUpdateSignatureError):
        verify_manifest_signature(
            manifest,
            trusted_keys={
                "chitlog-update-2026-01": raw_public_key(private_key),
            },
        )


def test_changed_signature_is_rejected():
    private_key = Ed25519PrivateKey.generate()
    manifest = signed_manifest(private_key)

    altered = SignedUpdateManifest(
        schema_version=manifest.schema_version,
        key_id=manifest.key_id,
        payload=manifest.payload,
        signature=b"\x00" * 64,
    )

    with pytest.raises(InvalidUpdateSignatureError):
        verify_manifest_signature(
            altered,
            trusted_keys={
                "chitlog-update-2026-01": raw_public_key(private_key),
            },
        )


def test_signature_from_wrong_private_key_is_rejected():
    signer = Ed25519PrivateKey.generate()
    wrong_key = Ed25519PrivateKey.generate()
    manifest = signed_manifest(signer)

    with pytest.raises(InvalidUpdateSignatureError):
        verify_manifest_signature(
            manifest,
            trusted_keys={
                "chitlog-update-2026-01": raw_public_key(wrong_key),
            },
        )


def test_unknown_key_id_is_rejected_before_trust():
    private_key = Ed25519PrivateKey.generate()
    manifest = signed_manifest(
        private_key,
        key_id="chitlog-update-future",
    )

    with pytest.raises(UnknownUpdateKeyError):
        verify_manifest_signature(
            manifest,
            trusted_keys={
                "chitlog-update-2026-01": raw_public_key(private_key),
            },
        )


def test_default_production_registry_contains_only_real_public_key():
    assert PRODUCTION_UPDATE_KEY_ID == "chitlog-update-2026-01"
    assert PRODUCTION_UPDATE_PUBLIC_KEY_SHA256 == (
        "eeb2edd191b0074c318db350001491fd"
        "89e94801a087685a4223052ec2d0151b"
    )
    assert set(TRUSTED_UPDATE_PUBLIC_KEYS) == {PRODUCTION_UPDATE_KEY_ID}
    assert (
        TRUSTED_UPDATE_PUBLIC_KEYS[PRODUCTION_UPDATE_KEY_ID].hex()
        == "d6a28064cc1352c6fcb64fdc2c9e275c"
        "a0e4ff15dfc0a33757d69057633501d2"
    )


def test_default_production_registry_rejects_untrusted_test_key_id():
    private_key = Ed25519PrivateKey.generate()
    manifest = signed_manifest(
        private_key,
        key_id="chitlog-update-test-key",
    )

    with pytest.raises(UnknownUpdateKeyError):
        verify_manifest_signature(manifest)


@pytest.mark.parametrize(
    "registry",
    [
        {"": b"x" * 32},
        {"bad key id": b"x" * 32},
        {"good-key": b"x" * 31},
        {"good-key": b"x" * 33},
        {"good-key": "not-bytes"},
    ],
)
def test_malformed_trusted_key_registry_is_rejected(registry):
    with pytest.raises(InvalidTrustedKeyError):
        validate_trusted_key_registry(registry)


def test_non_mapping_registry_is_rejected():
    with pytest.raises(InvalidTrustedKeyError):
        validate_trusted_key_registry([("key", b"x" * 32)])


def test_key_rotation_can_trust_old_and_new_public_keys():
    old_key = Ed25519PrivateKey.generate()
    new_key = Ed25519PrivateKey.generate()

    registry = {
        "chitlog-update-2026-01": raw_public_key(old_key),
        "chitlog-update-2027-01": raw_public_key(new_key),
    }

    old_manifest = signed_manifest(
        old_key,
        key_id="chitlog-update-2026-01",
    )
    new_manifest = signed_manifest(
        new_key,
        key_id="chitlog-update-2027-01",
    )

    assert verify_manifest_signature(
        old_manifest,
        trusted_keys=registry,
    ).version == "1.2.0"

    assert verify_manifest_signature(
        new_manifest,
        trusted_keys=registry,
    ).version == "1.2.0"


def test_private_signing_key_api_is_not_imported_into_production_verifier():
    source = (ROOT / "chitlog/core/update_signature.py").read_text(
        encoding="utf-8"
    )
    assert "Ed25519PrivateKey" not in source
    assert "BEGIN PRIVATE KEY" not in source
    assert "PRIVATE_KEY" not in source


def test_verified_result_is_the_strict_payload_model():
    private_key = Ed25519PrivateKey.generate()
    manifest = signed_manifest(private_key)

    result = verify_manifest_signature(
        manifest,
        trusted_keys={
            "chitlog-update-2026-01": raw_public_key(private_key),
        },
    )

    assert isinstance(result, UpdateManifestPayload)
