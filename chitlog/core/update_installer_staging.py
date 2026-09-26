"""Safe offline staging and SHA-256 verification for ChitLog installers.

This module does not perform networking and never executes an installer.
It accepts bytes from a caller, writes them to a temporary file, verifies the
signed manifest's exact size and SHA-256 digest, and only then atomically moves
the file into its final staging path.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import os
from pathlib import Path
import tempfile
from typing import Iterable

from chitlog.core.update_manifest import UpdateManifestPayload
from chitlog.core.version import Version


_CHUNK_SIZE = 1024 * 1024


class InstallerStagingError(RuntimeError):
    """Base error for safe installer staging."""


class InstallerSizeError(InstallerStagingError):
    """Installer size violates the signed manifest or local policy."""


class InstallerHashError(InstallerStagingError):
    """Installer SHA-256 does not match the signed manifest."""


class InstallerStreamError(InstallerStagingError):
    """Installer byte stream is malformed."""


@dataclass(frozen=True, slots=True)
class VerifiedInstallerArtifact:
    """A fully verified installer that is safe to hand to later stages."""

    path: Path
    version: str
    size_bytes: int
    sha256: str


def _validate_limit(max_installer_bytes: int) -> int:
    if isinstance(max_installer_bytes, bool) or not isinstance(
        max_installer_bytes,
        int,
    ):
        raise TypeError("Maximum installer size must be an integer.")
    if max_installer_bytes <= 0:
        raise ValueError("Maximum installer size must be positive.")
    return max_installer_bytes


def _safe_final_filename(payload: UpdateManifestPayload) -> str:
    """Build a fixed local filename from the already validated version."""

    # Re-parse at the file boundary rather than trusting arbitrary text in a
    # filesystem name. Strict MAJOR.MINOR.PATCH contains only digits/dots.
    version = str(Version.parse(payload.version))
    return f"ChitLog-{version}-Setup.exe"


def _expected_metadata(
    payload: UpdateManifestPayload,
    max_installer_bytes: int,
) -> tuple[int, str]:
    if not isinstance(payload, UpdateManifestPayload):
        raise TypeError("payload must be an UpdateManifestPayload.")

    limit = _validate_limit(max_installer_bytes)
    expected_size = int(payload.installer_size)

    if expected_size <= 0:
        raise InstallerSizeError(
            "Signed installer size must be positive."
        )
    if expected_size > limit:
        raise InstallerSizeError(
            "Signed installer size exceeds the local safety limit."
        )

    expected_hash = payload.installer_sha256
    if (
        not isinstance(expected_hash, str)
        or len(expected_hash) != 64
        or any(ch not in "0123456789abcdef" for ch in expected_hash)
    ):
        raise InstallerHashError(
            "Signed installer SHA-256 metadata is invalid."
        )

    return expected_size, expected_hash


def _verified_artifact(
    path: Path,
    payload: UpdateManifestPayload,
    size_bytes: int,
    sha256: str,
) -> VerifiedInstallerArtifact:
    return VerifiedInstallerArtifact(
        path=path,
        version=payload.version,
        size_bytes=size_bytes,
        sha256=sha256,
    )


def verify_installer_file(
    path: str | Path,
    payload: UpdateManifestPayload,
    *,
    max_installer_bytes: int,
) -> VerifiedInstallerArtifact:
    """Verify an existing regular file against signed installer metadata."""

    expected_size, expected_hash = _expected_metadata(
        payload,
        max_installer_bytes,
    )
    candidate = Path(path)

    if not candidate.is_file():
        raise InstallerStagingError(
            "Installer candidate is not a regular file."
        )

    try:
        stat_size = candidate.stat().st_size
    except OSError as exc:
        raise InstallerStagingError(
            "Installer candidate could not be inspected."
        ) from exc

    if stat_size != expected_size:
        raise InstallerSizeError(
            "Installer size does not match the signed manifest."
        )

    digest = hashlib.sha256()
    total = 0

    try:
        with candidate.open("rb") as handle:
            while True:
                chunk = handle.read(_CHUNK_SIZE)
                if not chunk:
                    break
                total += len(chunk)
                if total > expected_size:
                    raise InstallerSizeError(
                        "Installer exceeded the signed size while reading."
                    )
                digest.update(chunk)
    except InstallerStagingError:
        raise
    except OSError as exc:
        raise InstallerStagingError(
            "Installer candidate could not be read."
        ) from exc

    actual_hash = digest.hexdigest()
    if actual_hash != expected_hash:
        raise InstallerHashError(
            "Installer SHA-256 does not match the signed manifest."
        )

    return _verified_artifact(
        candidate,
        payload,
        total,
        actual_hash,
    )


def stage_installer_chunks(
    chunks: Iterable[bytes],
    payload: UpdateManifestPayload,
    destination_directory: str | Path,
    *,
    max_installer_bytes: int,
) -> VerifiedInstallerArtifact:
    """Write, verify, and atomically finalize streamed installer bytes.

    The destination file is never replaced until the complete temporary file
    matches both the signed byte count and signed SHA-256 digest.
    """

    expected_size, expected_hash = _expected_metadata(
        payload,
        max_installer_bytes,
    )

    destination = Path(destination_directory)
    try:
        destination.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise InstallerStagingError(
            "Installer staging directory could not be created."
        ) from exc

    if not destination.is_dir():
        raise InstallerStagingError(
            "Installer staging destination is not a directory."
        )

    final_path = destination / _safe_final_filename(payload)

    try:
        descriptor, temporary_name = tempfile.mkstemp(
            prefix=f".{final_path.stem}-",
            suffix=".part",
            dir=destination,
        )
    except OSError as exc:
        raise InstallerStagingError(
            "Temporary installer file could not be created."
        ) from exc

    os.close(descriptor)
    temporary_path = Path(temporary_name)
    total = 0
    digest = hashlib.sha256()

    try:
        try:
            with temporary_path.open("wb") as handle:
                for chunk in chunks:
                    if not isinstance(chunk, (bytes, bytearray, memoryview)):
                        raise InstallerStreamError(
                            "Installer stream yielded a non-bytes chunk."
                        )

                    data = bytes(chunk)
                    if not data:
                        continue

                    total += len(data)

                    if total > expected_size:
                        raise InstallerSizeError(
                            "Installer stream exceeded the signed size."
                        )
                    if total > max_installer_bytes:
                        raise InstallerSizeError(
                            "Installer stream exceeded the local safety limit."
                        )

                    handle.write(data)
                    digest.update(data)

                handle.flush()
                os.fsync(handle.fileno())
        except InstallerStagingError:
            raise
        except OSError as exc:
            raise InstallerStagingError(
                "Installer staging write failed."
            ) from exc

        if total != expected_size:
            raise InstallerSizeError(
                "Installer size does not match the signed manifest."
            )

        actual_hash = digest.hexdigest()
        if actual_hash != expected_hash:
            raise InstallerHashError(
                "Installer SHA-256 does not match the signed manifest."
            )

        # Re-open the completed temporary file and verify the on-disk bytes
        # before making it the visible final artifact.
        verify_installer_file(
            temporary_path,
            payload,
            max_installer_bytes=max_installer_bytes,
        )

        try:
            os.replace(temporary_path, final_path)
        except OSError as exc:
            raise InstallerStagingError(
                "Verified installer could not be finalized atomically."
            ) from exc

        return _verified_artifact(
            final_path,
            payload,
            total,
            actual_hash,
        )

    finally:
        # On every failure, delete only this run's private .part file. An
        # already finalized installer at final_path is deliberately untouched.
        try:
            temporary_path.unlink(missing_ok=True)
        except OSError:
            pass
