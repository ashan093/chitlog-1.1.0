"""Strict signed-update manifest model for ChitLog.

Step 2A defines the exact data that will be signed and verified later.  This
module performs no network access and no cryptographic verification.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import base64
import binascii
import json
import re
from typing import Any
from urllib.parse import urlsplit

from chitlog.core.version import APP_NAME, Version, VersionFormatError


MANIFEST_SCHEMA_VERSION = 1
SUPPORTED_PLATFORM = "windows"
SUPPORTED_ARCHITECTURE = "x64"
SUPPORTED_CHANNELS = frozenset({"stable", "beta"})

_PAYLOAD_FIELDS = frozenset(
    {
        "app",
        "version",
        "channel",
        "platform",
        "architecture",
        "published_at",
        "minimum_supported_version",
        "installer_url",
        "installer_sha256",
        "installer_size",
        "release_notes_url",
        "mandatory",
    }
)
_ENVELOPE_FIELDS = frozenset(
    {
        "schema_version",
        "key_id",
        "payload",
        "signature",
    }
)

_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_KEY_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")


class UpdateManifestError(ValueError):
    """Raised when an update manifest is malformed or unsafe."""


def _require_exact_fields(
    value: dict[str, Any],
    expected: frozenset[str],
    *,
    label: str,
) -> None:
    actual = frozenset(value)
    missing = sorted(expected - actual)
    unknown = sorted(actual - expected)
    if missing or unknown:
        details: list[str] = []
        if missing:
            details.append(f"missing: {', '.join(missing)}")
        if unknown:
            details.append(f"unknown: {', '.join(unknown)}")
        raise UpdateManifestError(f"{label} fields are invalid ({'; '.join(details)}).")


def _require_https_url(value: Any, *, field: str) -> str:
    if not isinstance(value, str) or not value:
        raise UpdateManifestError(f"{field} must be a non-empty HTTPS URL.")

    parsed = urlsplit(value)
    if parsed.scheme.lower() != "https":
        raise UpdateManifestError(f"{field} must use HTTPS.")
    if not parsed.hostname:
        raise UpdateManifestError(f"{field} must include a host.")
    if parsed.username is not None or parsed.password is not None:
        raise UpdateManifestError(f"{field} must not contain credentials.")
    if parsed.fragment:
        raise UpdateManifestError(f"{field} must not contain a fragment.")
    return value


def _require_utc_timestamp(value: Any) -> str:
    if not isinstance(value, str) or not value.endswith("Z"):
        raise UpdateManifestError("published_at must be an ISO-8601 UTC timestamp ending in Z.")

    try:
        parsed = datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError as exc:
        raise UpdateManifestError("published_at is not a valid ISO-8601 timestamp.") from exc

    if parsed.tzinfo is None or parsed.utcoffset() != timezone.utc.utcoffset(parsed):
        raise UpdateManifestError("published_at must be UTC.")
    return value


def _parse_version(value: Any, *, field: str) -> Version:
    if not isinstance(value, str):
        raise UpdateManifestError(f"{field} must be a version string.")
    try:
        return Version.parse(value)
    except VersionFormatError as exc:
        raise UpdateManifestError(f"{field} is invalid.") from exc


def canonical_payload_bytes(payload: dict[str, Any]) -> bytes:
    """Return deterministic UTF-8 JSON bytes used for Ed25519 signing.

    The payload must already be validated with ``UpdateManifestPayload.from_dict``.
    Sorting keys and using compact separators avoids whitespace/order ambiguity.
    """

    if not isinstance(payload, dict):
        raise UpdateManifestError("payload must be an object.")

    _require_exact_fields(payload, _PAYLOAD_FIELDS, label="payload")

    try:
        return json.dumps(
            payload,
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise UpdateManifestError("payload cannot be canonicalized safely.") from exc


@dataclass(frozen=True, slots=True)
class UpdateManifestPayload:
    app: str
    version: str
    channel: str
    platform: str
    architecture: str
    published_at: str
    minimum_supported_version: str
    installer_url: str
    installer_sha256: str
    installer_size: int
    release_notes_url: str
    mandatory: bool

    @classmethod
    def from_dict(cls, value: Any) -> "UpdateManifestPayload":
        if not isinstance(value, dict):
            raise UpdateManifestError("payload must be an object.")

        _require_exact_fields(value, _PAYLOAD_FIELDS, label="payload")

        app = value["app"]
        if app != APP_NAME:
            raise UpdateManifestError(f"payload app must be {APP_NAME!r}.")

        version = _parse_version(value["version"], field="version")
        minimum = _parse_version(
            value["minimum_supported_version"],
            field="minimum_supported_version",
        )
        if minimum > version:
            raise UpdateManifestError(
                "minimum_supported_version cannot be newer than version."
            )

        channel = value["channel"]
        if channel not in SUPPORTED_CHANNELS:
            raise UpdateManifestError("channel is not supported.")

        platform = value["platform"]
        if platform != SUPPORTED_PLATFORM:
            raise UpdateManifestError("platform is not supported.")

        architecture = value["architecture"]
        if architecture != SUPPORTED_ARCHITECTURE:
            raise UpdateManifestError("architecture is not supported.")

        published_at = _require_utc_timestamp(value["published_at"])

        installer_url = _require_https_url(
            value["installer_url"],
            field="installer_url",
        )
        release_notes_url = _require_https_url(
            value["release_notes_url"],
            field="release_notes_url",
        )

        sha256 = value["installer_sha256"]
        if not isinstance(sha256, str) or _SHA256_RE.fullmatch(sha256) is None:
            raise UpdateManifestError(
                "installer_sha256 must be exactly 64 lowercase hexadecimal characters."
            )

        size = value["installer_size"]
        if isinstance(size, bool) or not isinstance(size, int) or size <= 0:
            raise UpdateManifestError("installer_size must be a positive integer.")

        mandatory = value["mandatory"]
        if not isinstance(mandatory, bool):
            raise UpdateManifestError("mandatory must be a boolean.")

        return cls(
            app=app,
            version=str(version),
            channel=channel,
            platform=platform,
            architecture=architecture,
            published_at=published_at,
            minimum_supported_version=str(minimum),
            installer_url=installer_url,
            installer_sha256=sha256,
            installer_size=size,
            release_notes_url=release_notes_url,
            mandatory=mandatory,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "app": self.app,
            "version": self.version,
            "channel": self.channel,
            "platform": self.platform,
            "architecture": self.architecture,
            "published_at": self.published_at,
            "minimum_supported_version": self.minimum_supported_version,
            "installer_url": self.installer_url,
            "installer_sha256": self.installer_sha256,
            "installer_size": self.installer_size,
            "release_notes_url": self.release_notes_url,
            "mandatory": self.mandatory,
        }

    def canonical_bytes(self) -> bytes:
        return canonical_payload_bytes(self.to_dict())


@dataclass(frozen=True, slots=True)
class SignedUpdateManifest:
    schema_version: int
    key_id: str
    payload: UpdateManifestPayload
    signature: bytes

    @classmethod
    def from_dict(cls, value: Any) -> "SignedUpdateManifest":
        if not isinstance(value, dict):
            raise UpdateManifestError("manifest must be an object.")

        _require_exact_fields(value, _ENVELOPE_FIELDS, label="manifest")

        schema_version = value["schema_version"]
        if (
            isinstance(schema_version, bool)
            or not isinstance(schema_version, int)
            or schema_version != MANIFEST_SCHEMA_VERSION
        ):
            raise UpdateManifestError(
                f"schema_version must be {MANIFEST_SCHEMA_VERSION}."
            )

        key_id = value["key_id"]
        if not isinstance(key_id, str) or _KEY_ID_RE.fullmatch(key_id) is None:
            raise UpdateManifestError("key_id has an invalid format.")

        payload = UpdateManifestPayload.from_dict(value["payload"])

        signature_text = value["signature"]
        if not isinstance(signature_text, str) or not signature_text:
            raise UpdateManifestError("signature must be base64 text.")

        try:
            signature = base64.b64decode(signature_text, validate=True)
        except (binascii.Error, ValueError) as exc:
            raise UpdateManifestError("signature is not valid base64.") from exc

        # Ed25519 signatures are exactly 64 bytes.
        if len(signature) != 64:
            raise UpdateManifestError("signature must decode to exactly 64 bytes.")

        return cls(
            schema_version=schema_version,
            key_id=key_id,
            payload=payload,
            signature=signature,
        )

    @classmethod
    def from_json_bytes(cls, raw: bytes) -> "SignedUpdateManifest":
        if not isinstance(raw, bytes):
            raise UpdateManifestError("manifest input must be bytes.")

        if raw.startswith(b"\xef\xbb\xbf"):
            raise UpdateManifestError("manifest must not contain a UTF-8 BOM.")

        try:
            text = raw.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise UpdateManifestError("manifest must be valid UTF-8.") from exc

        try:
            value = json.loads(text)
        except json.JSONDecodeError as exc:
            raise UpdateManifestError("manifest is not valid JSON.") from exc

        return cls.from_dict(value)

    def signed_bytes(self) -> bytes:
        """Return the exact payload bytes that Step 2B will verify."""

        return self.payload.canonical_bytes()
