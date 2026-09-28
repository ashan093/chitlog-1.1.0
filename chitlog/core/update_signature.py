"""Ed25519 verification boundary for ChitLog update manifests.

Only PUBLIC verification keys belong in this module.  Production private
signing keys must never be bundled with ChitLog or committed to source control.
"""
from __future__ import annotations

from collections.abc import Mapping
from types import MappingProxyType
import re

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

from chitlog.core.update_manifest import (
    SignedUpdateManifest,
    UpdateManifestPayload,
)


_PUBLIC_KEY_BYTES = 32
_KEY_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")


class UpdateSignatureError(ValueError):
    """Base class for update signature trust failures."""


class UnknownUpdateKeyError(UpdateSignatureError):
    """Raised when a manifest references an untrusted key ID."""


class InvalidTrustedKeyError(UpdateSignatureError):
    """Raised when a configured trusted public key is malformed."""


class InvalidUpdateSignatureError(UpdateSignatureError):
    """Raised when Ed25519 verification fails."""


# Production release trust anchor.
#
# SECURITY RULE:
# - Only PUBLIC Ed25519 verification material belongs in this source file.
# - The encrypted production private signing key must remain outside the
#   repository and must never be bundled with ChitLog.
# - Revocation is performed by removing a compromised key ID from this registry
#   in a newly shipped trusted ChitLog build.
# - Rotation is performed by temporarily trusting both the retiring and new
#   public key IDs, then removing the retiring key after the migration window.
PRODUCTION_UPDATE_KEY_ID = "chitlog-update-2026-01"
PRODUCTION_UPDATE_PUBLIC_KEY_SHA256 = (
    "eeb2edd191b0074c318db350001491fd"
    "89e94801a087685a4223052ec2d0151b"
)
_PRODUCTION_UPDATE_PUBLIC_KEY = bytes.fromhex(
    "d6a28064cc1352c6fcb64fdc2c9e275c"
    "a0e4ff15dfc0a33757d69057633501d2"
)

TRUSTED_UPDATE_PUBLIC_KEYS: Mapping[str, bytes] = MappingProxyType(
    {
        PRODUCTION_UPDATE_KEY_ID: _PRODUCTION_UPDATE_PUBLIC_KEY,
    }
)


def validate_trusted_key_registry(
    trusted_keys: Mapping[str, bytes],
) -> None:
    """Validate key IDs and raw Ed25519 public-key bytes.

    Public keys use the standard 32-byte Ed25519 raw representation.
    """

    if not isinstance(trusted_keys, Mapping):
        raise InvalidTrustedKeyError("Trusted update keys must be a mapping.")

    for key_id, public_key in trusted_keys.items():
        if not isinstance(key_id, str) or _KEY_ID_RE.fullmatch(key_id) is None:
            raise InvalidTrustedKeyError(
                f"Trusted update key ID has an invalid format: {key_id!r}."
            )

        if not isinstance(public_key, bytes):
            raise InvalidTrustedKeyError(
                f"Trusted update public key {key_id!r} must be raw bytes."
            )

        if len(public_key) != _PUBLIC_KEY_BYTES:
            raise InvalidTrustedKeyError(
                f"Trusted update public key {key_id!r} must be exactly "
                f"{_PUBLIC_KEY_BYTES} bytes."
            )

        try:
            Ed25519PublicKey.from_public_bytes(public_key)
        except ValueError as exc:
            raise InvalidTrustedKeyError(
                f"Trusted update public key {key_id!r} is malformed."
            ) from exc


def verify_manifest_signature(
    manifest: SignedUpdateManifest,
    *,
    trusted_keys: Mapping[str, bytes] = TRUSTED_UPDATE_PUBLIC_KEYS,
) -> UpdateManifestPayload:
    """Verify a parsed manifest and return its payload only if trusted.

    Callers should treat manifest payload fields as untrusted until this
    function succeeds.
    """

    if not isinstance(manifest, SignedUpdateManifest):
        raise TypeError("manifest must be a SignedUpdateManifest.")

    validate_trusted_key_registry(trusted_keys)

    public_key_bytes = trusted_keys.get(manifest.key_id)
    if public_key_bytes is None:
        raise UnknownUpdateKeyError(
            f"Update manifest key ID {manifest.key_id!r} is not trusted."
        )

    try:
        public_key = Ed25519PublicKey.from_public_bytes(public_key_bytes)
    except ValueError as exc:
        # This should already have been caught by registry validation, but keep
        # the verification boundary defensive if the implementation changes.
        raise InvalidTrustedKeyError(
            f"Trusted update public key {manifest.key_id!r} is malformed."
        ) from exc

    try:
        public_key.verify(
            manifest.signature,
            manifest.signed_bytes(),
        )
    except InvalidSignature as exc:
        raise InvalidUpdateSignatureError(
            "Update manifest signature verification failed."
        ) from exc

    return manifest.payload


def parse_and_verify_manifest(
    raw: bytes,
    *,
    trusted_keys: Mapping[str, bytes] = TRUSTED_UPDATE_PUBLIC_KEYS,
) -> UpdateManifestPayload:
    """Parse strict manifest JSON, verify Ed25519, then expose the payload."""

    manifest = SignedUpdateManifest.from_json_bytes(raw)
    return verify_manifest_signature(manifest, trusted_keys=trusted_keys)
