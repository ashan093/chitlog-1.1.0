"""Step 9 tests for ChitLog's production Ed25519 update trust anchor."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from chitlog.core.update_manifest import SignedUpdateManifest
from chitlog.core.update_signature import (
    InvalidUpdateSignatureError,
    PRODUCTION_UPDATE_KEY_ID,
    PRODUCTION_UPDATE_PUBLIC_KEY_SHA256,
    TRUSTED_UPDATE_PUBLIC_KEYS,
    UnknownUpdateKeyError,
    parse_and_verify_manifest,
    verify_manifest_signature,
)


ROOT = Path(__file__).resolve().parents[1]

EXPECTED_PUBLIC_KEY_HEX = (
    "d6a28064cc1352c6fcb64fdc2c9e275c"
    "a0e4ff15dfc0a33757d69057633501d2"
)
EXPECTED_PUBLIC_KEY_SHA256 = (
    "eeb2edd191b0074c318db350001491fd"
    "89e94801a087685a4223052ec2d0151b"
)
EXPECTED_PROOF_PAYLOAD_SHA256 = (
    "9be6a2ea90f8970120117b34a985907f"
    "39615fc057434ce3477cb4f749db5a16"
)

PRODUCTION_PROOF_MANIFEST = (
    b'{"key_id":"chitlog-update-2026-01","payload":{'
    b'"app":"ChitLog","architecture":"x64","channel":"stable",'
    b'"installer_sha256":"0123456789abcdef0123456789abcdef'
    b'0123456789abcdef0123456789abcdef","installer_size":12345678,'
    b'"installer_url":"https://updates.chitlog.example/proof/'
    b'ChitLog-1.2.0-Setup.exe","mandatory":false,'
    b'"minimum_supported_version":"1.1.0","platform":"windows",'
    b'"published_at":"2026-09-28T12:00:00Z",'
    b'"release_notes_url":"https://updates.chitlog.example/proof/'
    b'releases/1.2.0","version":"1.2.0"},"schema_version":1,'
    b'"signature":"Q+KeoQl1d76i9PjIfFjtX+chyl01YuPbOA2mAMk/vik'
    b'PcQZa011bxplGRmCgbLO53hAr6MOmYeCsQkDi163uBg=="}'
)


def test_production_registry_has_exact_expected_trust_anchor():
    assert PRODUCTION_UPDATE_KEY_ID == "chitlog-update-2026-01"
    assert PRODUCTION_UPDATE_PUBLIC_KEY_SHA256 == EXPECTED_PUBLIC_KEY_SHA256
    assert set(TRUSTED_UPDATE_PUBLIC_KEYS) == {PRODUCTION_UPDATE_KEY_ID}

    public_key = TRUSTED_UPDATE_PUBLIC_KEYS[PRODUCTION_UPDATE_KEY_ID]
    assert public_key.hex() == EXPECTED_PUBLIC_KEY_HEX
    assert hashlib.sha256(public_key).hexdigest() == EXPECTED_PUBLIC_KEY_SHA256


def test_real_production_key_verifies_fixed_proof_manifest():
    payload = parse_and_verify_manifest(PRODUCTION_PROOF_MANIFEST)

    assert payload.version == "1.2.0"
    assert payload.channel == "stable"
    assert payload.minimum_supported_version == "1.1.0"
    assert payload.installer_size == 12_345_678


def test_proof_payload_matches_locally_recorded_canonical_hash():
    manifest = SignedUpdateManifest.from_json_bytes(PRODUCTION_PROOF_MANIFEST)

    assert (
        hashlib.sha256(manifest.signed_bytes()).hexdigest()
        == EXPECTED_PROOF_PAYLOAD_SHA256
    )


def test_production_proof_tampering_is_rejected():
    document = json.loads(PRODUCTION_PROOF_MANIFEST.decode("utf-8"))
    document["payload"]["installer_size"] += 1

    tampered = SignedUpdateManifest.from_dict(document)
    with pytest.raises(InvalidUpdateSignatureError):
        verify_manifest_signature(tampered)


def test_removed_or_unknown_key_id_is_not_trusted():
    document = json.loads(PRODUCTION_PROOF_MANIFEST.decode("utf-8"))
    document["key_id"] = "chitlog-update-revoked-example"

    changed = SignedUpdateManifest.from_dict(document)
    with pytest.raises(UnknownUpdateKeyError):
        verify_manifest_signature(changed)


def test_production_registry_is_read_only():
    with pytest.raises(TypeError):
        TRUSTED_UPDATE_PUBLIC_KEYS["untrusted-key"] = b"x" * 32


def test_runtime_verifier_contains_no_private_signing_material():
    source = (
        ROOT / "chitlog/core/update_signature.py"
    ).read_text(encoding="utf-8")

    assert "Ed25519PrivateKey" not in source
    assert "BEGIN PRIVATE KEY" not in source
    assert "PRIVATE_KEY" not in source
    assert "BestAvailableEncryption" not in source
