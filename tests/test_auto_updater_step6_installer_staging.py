"""Step 6A tests for safe offline installer staging."""
from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from chitlog.core.update_installer_staging import (
    InstallerHashError,
    InstallerSizeError,
    InstallerStagingError,
    InstallerStreamError,
    stage_installer_chunks,
    verify_installer_file,
)
from chitlog.core.update_manifest import UpdateManifestPayload


MAX_BYTES = 300 * 1024 * 1024


def payload_for(data: bytes, *, version: str = "1.2.0"):
    return UpdateManifestPayload.from_dict({
        "app": "ChitLog",
        "version": version,
        "channel": "stable",
        "platform": "windows",
        "architecture": "x64",
        "published_at": "2026-09-26T00:00:00Z",
        "minimum_supported_version": "1.0.0",
        "installer_url": "https://updates.example.test/ChitLog-Setup.exe",
        "installer_sha256": hashlib.sha256(data).hexdigest(),
        "installer_size": len(data),
        "release_notes_url": "https://chitlog.example.test/releases/1.2.0",
        "mandatory": False,
    })


def test_valid_chunks_are_verified_and_atomically_finalized(tmp_path):
    data = (b"ChitLog installer test bytes" * 4096) + b"done"
    payload = payload_for(data)

    artifact = stage_installer_chunks(
        [data[:100], data[100:5000], data[5000:]],
        payload,
        tmp_path / "downloads",
        max_installer_bytes=MAX_BYTES,
    )

    assert artifact.path.name == "ChitLog-1.2.0-Setup.exe"
    assert artifact.path.read_bytes() == data
    assert artifact.size_bytes == len(data)
    assert artifact.sha256 == hashlib.sha256(data).hexdigest()
    assert artifact.version == "1.2.0"
    assert list((tmp_path / "downloads").glob("*.part")) == []


def test_empty_chunks_are_ignored_without_changing_hash(tmp_path):
    data = b"abc123"
    artifact = stage_installer_chunks(
        [b"", data[:3], b"", data[3:], b""],
        payload_for(data),
        tmp_path,
        max_installer_bytes=MAX_BYTES,
    )
    assert artifact.path.read_bytes() == data


def test_hash_mismatch_removes_part_and_creates_no_final_file(tmp_path):
    signed = b"signed bytes"
    # Keep the candidate exactly the same byte length as the signed
    # artifact so this test reaches SHA-256 verification rather than
    # correctly failing earlier at the signed-size boundary.
    received = b"tampered!!!!"

    with pytest.raises(InstallerHashError):
        stage_installer_chunks(
            [received],
            payload_for(signed),
            tmp_path,
            max_installer_bytes=MAX_BYTES,
        )

    assert list(tmp_path.glob("*.part")) == []
    assert list(tmp_path.glob("*.exe")) == []


def test_short_stream_is_rejected_and_cleaned(tmp_path):
    signed = b"1234567890"

    with pytest.raises(InstallerSizeError):
        stage_installer_chunks(
            [b"123"],
            payload_for(signed),
            tmp_path,
            max_installer_bytes=MAX_BYTES,
        )

    assert list(tmp_path.glob("*.part")) == []
    assert list(tmp_path.glob("*.exe")) == []


def test_stream_larger_than_signed_size_stops_immediately(tmp_path):
    signed = b"1234"

    with pytest.raises(InstallerSizeError, match="exceeded"):
        stage_installer_chunks(
            [b"1234", b"5"],
            payload_for(signed),
            tmp_path,
            max_installer_bytes=MAX_BYTES,
        )

    assert list(tmp_path.glob("*.part")) == []


def test_signed_size_above_local_limit_is_rejected_before_iteration(tmp_path):
    data = b"0123456789"
    consumed = []

    def source():
        consumed.append(True)
        yield data

    with pytest.raises(InstallerSizeError, match="local safety limit"):
        stage_installer_chunks(
            source(),
            payload_for(data),
            tmp_path,
            max_installer_bytes=5,
        )

    assert consumed == []
    assert not tmp_path.exists() or list(tmp_path.iterdir()) == []


@pytest.mark.parametrize("bad_chunk", ["bytes", 123, object(), None])
def test_non_bytes_stream_chunk_is_rejected(tmp_path, bad_chunk):
    data = b"abcd"

    with pytest.raises(InstallerStreamError):
        stage_installer_chunks(
            [bad_chunk],
            payload_for(data),
            tmp_path,
            max_installer_bytes=MAX_BYTES,
        )

    assert list(tmp_path.glob("*.part")) == []


def test_failed_replacement_attempt_preserves_existing_final_file(tmp_path):
    original = b"previous verified installer"
    signed = b"new signed installer"

    final_path = tmp_path / "ChitLog-1.2.0-Setup.exe"
    final_path.write_bytes(original)

    with pytest.raises(InstallerHashError):
        stage_installer_chunks(
            [b"new tampered install"],
            payload_for(signed),
            tmp_path,
            max_installer_bytes=MAX_BYTES,
        )

    assert final_path.read_bytes() == original
    assert list(tmp_path.glob("*.part")) == []


def test_success_replaces_existing_final_file_only_after_verification(tmp_path):
    old = b"old installer"
    new = b"new verified installer"

    final_path = tmp_path / "ChitLog-1.2.0-Setup.exe"
    final_path.write_bytes(old)

    artifact = stage_installer_chunks(
        [new],
        payload_for(new),
        tmp_path,
        max_installer_bytes=MAX_BYTES,
    )

    assert artifact.path == final_path
    assert final_path.read_bytes() == new


def test_verify_existing_installer_accepts_valid_regular_file(tmp_path):
    data = b"already downloaded and verified candidate"
    path = tmp_path / "candidate.exe"
    path.write_bytes(data)

    artifact = verify_installer_file(
        path,
        payload_for(data),
        max_installer_bytes=MAX_BYTES,
    )

    assert artifact.path == path
    assert artifact.size_bytes == len(data)
    assert artifact.sha256 == hashlib.sha256(data).hexdigest()


def test_verify_existing_installer_rejects_size_and_hash_mismatch(tmp_path):
    signed = b"123456"
    path = tmp_path / "candidate.exe"

    path.write_bytes(b"123")
    with pytest.raises(InstallerSizeError):
        verify_installer_file(
            path,
            payload_for(signed),
            max_installer_bytes=MAX_BYTES,
        )

    path.write_bytes(b"abcdef")
    with pytest.raises(InstallerHashError):
        verify_installer_file(
            path,
            payload_for(signed),
            max_installer_bytes=MAX_BYTES,
        )


def test_verify_rejects_directory_instead_of_regular_file(tmp_path):
    with pytest.raises(InstallerStagingError, match="regular file"):
        verify_installer_file(
            tmp_path,
            payload_for(b"x"),
            max_installer_bytes=MAX_BYTES,
        )


@pytest.mark.parametrize("limit", [0, -1])
def test_nonpositive_local_limit_is_rejected(tmp_path, limit):
    with pytest.raises(ValueError, match="positive"):
        stage_installer_chunks(
            [b"x"],
            payload_for(b"x"),
            tmp_path,
            max_installer_bytes=limit,
        )


@pytest.mark.parametrize("limit", [True, 1.5, "100"])
def test_noninteger_local_limit_is_rejected(tmp_path, limit):
    with pytest.raises(TypeError, match="integer"):
        stage_installer_chunks(
            [b"x"],
            payload_for(b"x"),
            tmp_path,
            max_installer_bytes=limit,
        )


def test_staging_module_has_no_network_or_process_execution():
    project = Path(__file__).resolve().parents[1]
    source = (
        project / "chitlog/core/update_installer_staging.py"
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

    assert "hashlib.sha256" in source
    assert "os.replace" in source
    assert "tempfile.mkstemp" in source
