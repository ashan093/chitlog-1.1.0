"""Step 7A tests for the signed standalone-updater handoff foundation."""
from __future__ import annotations

import base64
from dataclasses import replace
import hashlib
import json
from pathlib import Path

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from chitlog.core.update_checker import check_for_updates
from chitlog.core.update_config import UpdatePolicy
from chitlog.core.update_handoff import (
    MAX_HANDOFF_BYTES,
    UpdateHandoff,
    UpdateHandoffError,
    UpdateHandoffPathError,
    UpdateHandoffSecurityError,
    create_update_handoff,
    load_and_verify_update_handoff,
    write_update_handoff,
)
from chitlog.core.update_installer_staging import (
    InstallerHashError,
    VerifiedInstallerArtifact,
)
from chitlog.core.update_manifest import (
    SignedUpdateManifest,
    UpdateManifestPayload,
)


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


def manifest_json_bytes(manifest: SignedUpdateManifest) -> bytes:
    return json.dumps(
        {
            "schema_version": manifest.schema_version,
            "key_id": manifest.key_id,
            "payload": manifest.payload.to_dict(),
            "signature": base64.b64encode(
                manifest.signature
            ).decode("ascii"),
        },
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def create_local_files(tmp_path, data: bytes, version: str = "1.2.0"):
    staging = tmp_path / "updates"
    staging.mkdir()
    installer = staging / f"ChitLog-{version}-Setup.exe"
    installer.write_bytes(data)
    app = tmp_path / "ChitLog.exe"
    app.write_bytes(b"current application")
    artifact = VerifiedInstallerArtifact(
        path=installer,
        version=version,
        size_bytes=len(data),
        sha256=hashlib.sha256(data).hexdigest(),
    )
    return staging, app, artifact


def test_secure_update_check_preserves_verified_signed_manifest():
    data = b"installer"
    manifest, trusted = signed_manifest_for(data)
    raw = manifest_json_bytes(manifest)

    outcome = check_for_updates(
        UpdatePolicy(
            manifest_url="https://updates.example.test/manifest.json",
            channel="stable",
        ),
        current_version="1.1.0",
        trusted_keys=trusted,
        fetcher=lambda policy: raw,
    )

    assert outcome.update_available is True
    assert outcome.manifest == manifest
    assert outcome.manifest.payload == outcome.decision.payload


def test_outcome_rejects_manifest_decision_payload_mismatch():
    from chitlog.core.update_checker import UpdateCheckOutcome
    from chitlog.core.update_decision import decide_update

    data = b"installer"
    manifest, _ = signed_manifest_for(data, version="1.2.0")
    other, _ = signed_manifest_for(data, version="1.3.0")
    decision = decide_update(
        manifest.payload,
        current_version="1.1.0",
        policy=UpdatePolicy(channel="stable"),
    )

    with pytest.raises(ValueError, match="does not match"):
        UpdateCheckOutcome(
            decision=decision,
            manifest=other,
        )


def test_handoff_round_trip_reverifies_signature_installer_and_paths(tmp_path):
    data = b"verified installer bytes" * 100
    manifest, trusted = signed_manifest_for(data)
    staging, app, artifact = create_local_files(tmp_path, data)

    handoff = create_update_handoff(
        manifest,
        artifact,
        app,
        parent_pid=4321,
        trusted_keys=trusted,
        current_version="1.1.0",
        created_at="2026-09-26T05:00:00Z",
    )
    handoff_path = write_update_handoff(staging, handoff)

    verified = load_and_verify_update_handoff(
        handoff_path,
        trusted_keys=trusted,
        current_version="1.1.0",
    )

    assert verified.payload.version == "1.2.0"
    assert verified.decision.update_available is True
    assert verified.installer.path == artifact.path.resolve()
    assert verified.application_path == app.resolve()
    assert verified.handoff.parent_pid == 4321
    assert verified.handoff.created_at == "2026-09-26T05:00:00Z"
    assert handoff_path.parent == staging.resolve()
    assert list(staging.glob("*.part")) == []


def test_tampered_embedded_manifest_signature_is_rejected(tmp_path):
    data = b"installer"
    manifest, trusted = signed_manifest_for(data)
    staging, app, artifact = create_local_files(tmp_path, data)

    handoff = create_update_handoff(
        manifest,
        artifact,
        app,
        parent_pid=1,
        trusted_keys=trusted,
        current_version="1.1.0",
    )
    value = handoff.to_dict()
    value["manifest"]["signature"] = base64.b64encode(b"x" * 64).decode(
        "ascii"
    )
    handoff_path = staging / "tampered-handoff.json"
    handoff_path.write_text(
        json.dumps(value),
        encoding="utf-8",
    )

    with pytest.raises(UpdateHandoffSecurityError, match="signature"):
        load_and_verify_update_handoff(
            handoff_path,
            trusted_keys=trusted,
            current_version="1.1.0",
        )


def test_tampered_installer_is_rejected_again_by_standalone_boundary(tmp_path):
    data = b"original verified installer"
    manifest, trusted = signed_manifest_for(data)
    staging, app, artifact = create_local_files(tmp_path, data)

    handoff = create_update_handoff(
        manifest,
        artifact,
        app,
        parent_pid=99,
        trusted_keys=trusted,
        current_version="1.1.0",
    )
    handoff_path = write_update_handoff(staging, handoff)

    artifact.path.write_bytes(b"tampered installer contents")

    with pytest.raises(InstallerHashError):
        load_and_verify_update_handoff(
            handoff_path,
            trusted_keys=trusted,
            current_version="1.1.0",
        )


def test_installer_outside_handoff_directory_is_rejected(tmp_path):
    data = b"installer"
    manifest, trusted = signed_manifest_for(data)
    staging, app, artifact = create_local_files(tmp_path, data)

    handoff = create_update_handoff(
        manifest,
        artifact,
        app,
        parent_pid=7,
        trusted_keys=trusted,
        current_version="1.1.0",
    )

    other = tmp_path / "other"
    other.mkdir()
    handoff_path = other / "ChitLog-1.2.0-handoff.json"
    handoff_path.write_bytes(handoff.to_json_bytes())

    with pytest.raises(UpdateHandoffPathError, match="outside"):
        load_and_verify_update_handoff(
            handoff_path,
            trusted_keys=trusted,
            current_version="1.1.0",
        )


def test_old_signed_release_cannot_be_replayed_as_an_update(tmp_path):
    data = b"installer"
    manifest, trusted = signed_manifest_for(data, version="1.1.0")
    staging, app, artifact = create_local_files(
        tmp_path,
        data,
        version="1.1.0",
    )

    with pytest.raises(UpdateHandoffSecurityError, match="not newer"):
        create_update_handoff(
            manifest,
            artifact,
            app,
            parent_pid=55,
            trusted_keys=trusted,
            current_version="1.1.0",
        )


def test_relative_or_non_exe_application_path_is_rejected(tmp_path):
    data = b"installer"
    manifest, trusted = signed_manifest_for(data)
    staging, app, artifact = create_local_files(tmp_path, data)

    with pytest.raises(UpdateHandoffPathError, match="absolute"):
        create_update_handoff(
            manifest,
            artifact,
            Path("ChitLog.exe"),
            parent_pid=22,
            trusted_keys=trusted,
            current_version="1.1.0",
        )

    text_file = tmp_path / "ChitLog.txt"
    text_file.write_bytes(b"not exe")

    with pytest.raises(UpdateHandoffPathError, match=".exe"):
        create_update_handoff(
            manifest,
            artifact,
            text_file,
            parent_pid=22,
            trusted_keys=trusted,
            current_version="1.1.0",
        )


@pytest.mark.parametrize("pid", [0, -1, True, 0x100000000])
def test_invalid_parent_pid_is_rejected(tmp_path, pid):
    data = b"installer"
    manifest, trusted = signed_manifest_for(data)
    staging, app, artifact = create_local_files(tmp_path, data)

    with pytest.raises(UpdateHandoffError, match="parent_pid"):
        create_update_handoff(
            manifest,
            artifact,
            app,
            parent_pid=pid,
            trusted_keys=trusted,
            current_version="1.1.0",
        )


def test_unknown_handoff_field_and_oversized_input_are_rejected(tmp_path):
    data = b"installer"
    manifest, trusted = signed_manifest_for(data)
    staging, app, artifact = create_local_files(tmp_path, data)

    handoff = create_update_handoff(
        manifest,
        artifact,
        app,
        parent_pid=5,
        trusted_keys=trusted,
        current_version="1.1.0",
    )
    value = handoff.to_dict()
    value["unexpected"] = True

    with pytest.raises(UpdateHandoffError, match="unknown"):
        UpdateHandoff.from_dict(value)

    with pytest.raises(UpdateHandoffError, match="too large"):
        UpdateHandoff.from_json_bytes(b"{" + b"x" * MAX_HANDOFF_BYTES + b"}")


def test_write_requires_installer_beside_handoff(tmp_path):
    data = b"installer"
    manifest, trusted = signed_manifest_for(data)
    staging, app, artifact = create_local_files(tmp_path, data)

    handoff = create_update_handoff(
        manifest,
        artifact,
        app,
        parent_pid=33,
        trusted_keys=trusted,
        current_version="1.1.0",
    )

    other = tmp_path / "other"
    with pytest.raises(UpdateHandoffPathError, match="same directory"):
        write_update_handoff(other, handoff)


def test_step7a_has_no_network_or_process_execution():
    project = Path(__file__).resolve().parents[1]
    source = (
        project / "chitlog/core/update_handoff.py"
    ).read_text(encoding="utf-8")

    for forbidden in (
        "http.client",
        "urllib.request",
        "requests",
        "httpx",
        "socket",
        "subprocess",
        "Popen",
        "os.startfile",
        "ShellExecute",
        "QProcess",
    ):
        assert forbidden not in source

    assert "verify_manifest_signature(" in source
    assert "verify_installer_file(" in source
    assert "os.replace(" in source
