"""Signed standalone-updater handoff foundation for ChitLog.

This module creates and verifies a small local JSON handoff file that carries
the *already signed* release manifest alongside local installer/application
paths.  It performs no network access and launches no process.

The standalone updater must independently verify:
1. the Ed25519 release manifest;
2. that the signed release is newer than the running updater build;
3. the staged installer's exact signed size and SHA-256;
4. that the staged installer lives beside the handoff file.

Only after those checks may a later stage consider launching the installer.
"""
from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timezone
import base64
import json
import os
from pathlib import Path
import tempfile
from typing import Any

from chitlog.core.update_config import (
    DEFAULT_MAX_INSTALLER_BYTES,
    UpdatePolicy,
)
from chitlog.core.update_decision import (
    UpdateDecision,
    UpdateDecisionError,
    decide_update,
)
from chitlog.core.update_installer_staging import (
    VerifiedInstallerArtifact,
    verify_installer_file,
)
from chitlog.core.update_manifest import (
    SignedUpdateManifest,
    UpdateManifestError,
    UpdateManifestPayload,
)
from chitlog.core.update_signature import (
    TRUSTED_UPDATE_PUBLIC_KEYS,
    UpdateSignatureError,
    verify_manifest_signature,
)
from chitlog.core.version import APP_VERSION


HANDOFF_SCHEMA_VERSION = 1
MAX_HANDOFF_BYTES = 64 * 1024

_HANDOFF_FIELDS = frozenset(
    {
        "schema_version",
        "created_at",
        "parent_pid",
        "application_path",
        "installer_path",
        "manifest",
    }
)


class UpdateHandoffError(ValueError):
    """Base class for malformed or unsafe updater handoff data."""


class UpdateHandoffSecurityError(UpdateHandoffError):
    """Raised when handoff trust/integrity validation fails."""


class UpdateHandoffPathError(UpdateHandoffError):
    """Raised when a local handoff path violates updater policy."""


@dataclass(frozen=True, slots=True)
class UpdateHandoff:
    schema_version: int
    created_at: str
    parent_pid: int
    application_path: str
    installer_path: str
    manifest: SignedUpdateManifest

    @classmethod
    def from_dict(cls, value: Any) -> "UpdateHandoff":
        if not isinstance(value, dict):
            raise UpdateHandoffError("Update handoff must be a JSON object.")

        actual = frozenset(value)
        missing = sorted(_HANDOFF_FIELDS - actual)
        unknown = sorted(actual - _HANDOFF_FIELDS)
        if missing or unknown:
            details: list[str] = []
            if missing:
                details.append(f"missing: {', '.join(missing)}")
            if unknown:
                details.append(f"unknown: {', '.join(unknown)}")
            raise UpdateHandoffError(
                "Update handoff fields are invalid "
                f"({'; '.join(details)})."
            )

        schema_version = value["schema_version"]
        if (
            isinstance(schema_version, bool)
            or not isinstance(schema_version, int)
            or schema_version != HANDOFF_SCHEMA_VERSION
        ):
            raise UpdateHandoffError(
                f"schema_version must be {HANDOFF_SCHEMA_VERSION}."
            )

        created_at = _require_utc_timestamp(value["created_at"])

        parent_pid = value["parent_pid"]
        if (
            isinstance(parent_pid, bool)
            or not isinstance(parent_pid, int)
            or parent_pid <= 0
            or parent_pid > 0xFFFFFFFF
        ):
            raise UpdateHandoffError(
                "parent_pid must be a positive 32-bit process ID."
            )

        application_path = _require_absolute_exe_path(
            value["application_path"],
            field="application_path",
        )
        installer_path = _require_absolute_exe_path(
            value["installer_path"],
            field="installer_path",
        )

        try:
            manifest = SignedUpdateManifest.from_dict(value["manifest"])
        except UpdateManifestError as exc:
            raise UpdateHandoffError(
                "Embedded signed update manifest is invalid."
            ) from exc

        return cls(
            schema_version=schema_version,
            created_at=created_at,
            parent_pid=parent_pid,
            application_path=application_path,
            installer_path=installer_path,
            manifest=manifest,
        )

    @classmethod
    def from_json_bytes(cls, raw: bytes) -> "UpdateHandoff":
        if not isinstance(raw, bytes):
            raise UpdateHandoffError("Update handoff input must be bytes.")
        if len(raw) > MAX_HANDOFF_BYTES:
            raise UpdateHandoffError("Update handoff file is too large.")
        if raw.startswith(b"\xef\xbb\xbf"):
            raise UpdateHandoffError(
                "Update handoff must not contain a UTF-8 BOM."
            )

        try:
            text = raw.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise UpdateHandoffError(
                "Update handoff must be valid UTF-8."
            ) from exc

        try:
            value = json.loads(text)
        except json.JSONDecodeError as exc:
            raise UpdateHandoffError(
                "Update handoff is not valid JSON."
            ) from exc

        return cls.from_dict(value)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "created_at": self.created_at,
            "parent_pid": self.parent_pid,
            "application_path": self.application_path,
            "installer_path": self.installer_path,
            "manifest": _manifest_to_dict(self.manifest),
        }

    def to_json_bytes(self) -> bytes:
        try:
            raw = json.dumps(
                self.to_dict(),
                ensure_ascii=False,
                allow_nan=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        except (TypeError, ValueError) as exc:
            raise UpdateHandoffError(
                "Update handoff could not be serialized safely."
            ) from exc

        if len(raw) > MAX_HANDOFF_BYTES:
            raise UpdateHandoffError("Update handoff file is too large.")
        return raw


@dataclass(frozen=True, slots=True)
class VerifiedUpdateHandoff:
    """Fully re-verified evidence safe for the future updater executor."""

    handoff: UpdateHandoff
    payload: UpdateManifestPayload
    decision: UpdateDecision
    installer: VerifiedInstallerArtifact
    application_path: Path
    handoff_path: Path


def _manifest_to_dict(manifest: SignedUpdateManifest) -> dict[str, Any]:
    if not isinstance(manifest, SignedUpdateManifest):
        raise TypeError("manifest must be a SignedUpdateManifest.")

    return {
        "schema_version": manifest.schema_version,
        "key_id": manifest.key_id,
        "payload": manifest.payload.to_dict(),
        "signature": base64.b64encode(manifest.signature).decode("ascii"),
    }


def _require_utc_timestamp(value: Any) -> str:
    if not isinstance(value, str) or not value.endswith("Z"):
        raise UpdateHandoffError(
            "created_at must be an ISO-8601 UTC timestamp ending in Z."
        )

    try:
        parsed = datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError as exc:
        raise UpdateHandoffError(
            "created_at is not a valid ISO-8601 timestamp."
        ) from exc

    if parsed.tzinfo is None or parsed.utcoffset() != timezone.utc.utcoffset(parsed):
        raise UpdateHandoffError("created_at must be UTC.")

    return value


def _utc_now_text() -> str:
    return (
        datetime.now(timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )


def _require_absolute_exe_path(value: Any, *, field: str) -> str:
    if not isinstance(value, str) or not value:
        raise UpdateHandoffPathError(
            f"{field} must be a non-empty absolute path."
        )
    if "\x00" in value:
        raise UpdateHandoffPathError(f"{field} contains an invalid NUL byte.")

    path = Path(value)
    if not path.is_absolute():
        raise UpdateHandoffPathError(f"{field} must be an absolute path.")
    if path.suffix.lower() != ".exe":
        raise UpdateHandoffPathError(f"{field} must point to an .exe file.")
    return str(path)


def _require_regular_local_file(path: Path, *, label: str) -> Path:
    try:
        if path.is_symlink():
            raise UpdateHandoffPathError(
                f"{label} must not be a symbolic link."
            )
        resolved = path.resolve(strict=True)
    except OSError as exc:
        raise UpdateHandoffPathError(
            f"{label} could not be resolved safely."
        ) from exc

    if not resolved.is_file():
        raise UpdateHandoffPathError(
            f"{label} must be an existing regular file."
        )

    return resolved


def _verified_release(
    manifest: SignedUpdateManifest,
    *,
    trusted_keys: Mapping[str, bytes],
    current_version: str,
    max_installer_bytes: int,
) -> tuple[UpdateManifestPayload, UpdateDecision]:
    try:
        payload = verify_manifest_signature(
            manifest,
            trusted_keys=trusted_keys,
        )
    except UpdateSignatureError as exc:
        raise UpdateHandoffSecurityError(
            "Embedded update manifest signature could not be verified."
        ) from exc

    try:
        decision = decide_update(
            payload,
            current_version=current_version,
            policy=UpdatePolicy(
                manifest_url=None,
                channel=payload.channel,
                max_installer_bytes=max_installer_bytes,
            ),
        )
    except UpdateDecisionError as exc:
        raise UpdateHandoffSecurityError(
            "Signed update manifest conflicts with local updater policy."
        ) from exc

    if not decision.update_available:
        raise UpdateHandoffSecurityError(
            "Signed release is not newer than this ChitLog build."
        )

    return payload, decision


def create_update_handoff(
    manifest: SignedUpdateManifest,
    installer: VerifiedInstallerArtifact,
    application_path: str | Path,
    *,
    parent_pid: int,
    trusted_keys: Mapping[str, bytes] = TRUSTED_UPDATE_PUBLIC_KEYS,
    current_version: str = APP_VERSION,
    max_installer_bytes: int = DEFAULT_MAX_INSTALLER_BYTES,
    created_at: str | None = None,
) -> UpdateHandoff:
    """Create handoff data only after independently re-verifying release evidence."""

    if not isinstance(manifest, SignedUpdateManifest):
        raise TypeError("manifest must be a SignedUpdateManifest.")
    if not isinstance(installer, VerifiedInstallerArtifact):
        raise TypeError("installer must be a VerifiedInstallerArtifact.")

    payload, _ = _verified_release(
        manifest,
        trusted_keys=trusted_keys,
        current_version=current_version,
        max_installer_bytes=max_installer_bytes,
    )

    if installer.version != payload.version:
        raise UpdateHandoffSecurityError(
            "Verified installer version does not match the signed manifest."
        )
    if installer.size_bytes != payload.installer_size:
        raise UpdateHandoffSecurityError(
            "Verified installer size does not match the signed manifest."
        )
    if installer.sha256 != payload.installer_sha256:
        raise UpdateHandoffSecurityError(
            "Verified installer SHA-256 does not match the signed manifest."
        )

    verified_installer = verify_installer_file(
        installer.path,
        payload,
        max_installer_bytes=max_installer_bytes,
    )

    app_text = _require_absolute_exe_path(
        str(Path(application_path)),
        field="application_path",
    )
    app_path = _require_regular_local_file(
        Path(app_text),
        label="Application executable",
    )

    if (
        isinstance(parent_pid, bool)
        or not isinstance(parent_pid, int)
        or parent_pid <= 0
        or parent_pid > 0xFFFFFFFF
    ):
        raise UpdateHandoffError(
            "parent_pid must be a positive 32-bit process ID."
        )

    timestamp = _require_utc_timestamp(
        created_at if created_at is not None else _utc_now_text()
    )

    return UpdateHandoff(
        schema_version=HANDOFF_SCHEMA_VERSION,
        created_at=timestamp,
        parent_pid=parent_pid,
        application_path=str(app_path),
        installer_path=str(verified_installer.path.resolve(strict=True)),
        manifest=manifest,
    )


def write_update_handoff(
    destination_directory: str | Path,
    handoff: UpdateHandoff,
) -> Path:
    """Atomically write a deterministic handoff beside the staged installer."""

    if not isinstance(handoff, UpdateHandoff):
        raise TypeError("handoff must be an UpdateHandoff.")

    destination = Path(destination_directory)
    try:
        destination.mkdir(parents=True, exist_ok=True)
        resolved_destination = destination.resolve(strict=True)
    except OSError as exc:
        raise UpdateHandoffPathError(
            "Update handoff directory could not be prepared safely."
        ) from exc

    if not resolved_destination.is_dir():
        raise UpdateHandoffPathError(
            "Update handoff destination is not a directory."
        )

    installer_path = _require_regular_local_file(
        Path(handoff.installer_path),
        label="Staged installer",
    )

    if installer_path.parent != resolved_destination:
        raise UpdateHandoffPathError(
            "Staged installer must be in the same directory as the handoff."
        )

    expected_name = (
        f"ChitLog-{handoff.manifest.payload.version}-Setup.exe"
    )
    if installer_path.name != expected_name:
        raise UpdateHandoffPathError(
            "Staged installer filename does not match the signed version."
        )

    raw = handoff.to_json_bytes()
    final_path = (
        resolved_destination
        / f"ChitLog-{handoff.manifest.payload.version}-handoff.json"
    )

    try:
        descriptor, temporary_name = tempfile.mkstemp(
            prefix=f".{final_path.stem}-",
            suffix=".part",
            dir=resolved_destination,
        )
    except OSError as exc:
        raise UpdateHandoffPathError(
            "Temporary update handoff could not be created."
        ) from exc

    os.close(descriptor)
    temporary_path = Path(temporary_name)

    try:
        with temporary_path.open("wb") as handle:
            handle.write(raw)
            handle.flush()
            os.fsync(handle.fileno())

        os.replace(temporary_path, final_path)
    except OSError as exc:
        raise UpdateHandoffPathError(
            "Update handoff could not be finalized atomically."
        ) from exc
    finally:
        try:
            temporary_path.unlink(missing_ok=True)
        except OSError:
            pass

    return final_path


def load_and_verify_update_handoff(
    handoff_path: str | Path,
    *,
    trusted_keys: Mapping[str, bytes] = TRUSTED_UPDATE_PUBLIC_KEYS,
    current_version: str = APP_VERSION,
    max_installer_bytes: int = DEFAULT_MAX_INSTALLER_BYTES,
) -> VerifiedUpdateHandoff:
    """Load a handoff and independently re-verify every installation input."""

    source = Path(handoff_path)
    source_resolved = _require_regular_local_file(
        source,
        label="Update handoff",
    )

    try:
        size = source_resolved.stat().st_size
    except OSError as exc:
        raise UpdateHandoffPathError(
            "Update handoff could not be inspected."
        ) from exc

    if size <= 0 or size > MAX_HANDOFF_BYTES:
        raise UpdateHandoffError(
            "Update handoff file size is invalid."
        )

    try:
        raw = source_resolved.read_bytes()
    except OSError as exc:
        raise UpdateHandoffPathError(
            "Update handoff could not be read."
        ) from exc

    handoff = UpdateHandoff.from_json_bytes(raw)

    payload, decision = _verified_release(
        handoff.manifest,
        trusted_keys=trusted_keys,
        current_version=current_version,
        max_installer_bytes=max_installer_bytes,
    )

    installer_path = _require_regular_local_file(
        Path(handoff.installer_path),
        label="Staged installer",
    )
    application_path = _require_regular_local_file(
        Path(handoff.application_path),
        label="Application executable",
    )

    if installer_path.parent != source_resolved.parent:
        raise UpdateHandoffPathError(
            "Staged installer is outside the handoff directory."
        )

    expected_installer_name = f"ChitLog-{payload.version}-Setup.exe"
    if installer_path.name != expected_installer_name:
        raise UpdateHandoffPathError(
            "Staged installer filename does not match the signed version."
        )

    installer = verify_installer_file(
        installer_path,
        payload,
        max_installer_bytes=max_installer_bytes,
    )

    return VerifiedUpdateHandoff(
        handoff=handoff,
        payload=payload,
        decision=decision,
        installer=installer,
        application_path=application_path,
        handoff_path=source_resolved,
    )
