"""Offline deterministic release-manifest signer for ChitLog.

This packaging-only tool is intentionally outside the runtime ``chitlog``
package. It may load the encrypted production Ed25519 private key, but the
private key and passphrase must never be committed, bundled, logged, or sent
to Cloudflare.

The tool signs only the exact installer produced by ChitLog's release pipeline:
``release/ChitLog-<APP_VERSION>-Setup.exe``.
"""
from __future__ import annotations

import argparse
import base64
import getpass
import hashlib
import json
import os
from pathlib import Path
from typing import Mapping
from urllib.parse import urlsplit

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
)

from chitlog.core.update_config import DEFAULT_MAX_INSTALLER_BYTES
from chitlog.core.update_manifest import (
    MANIFEST_SCHEMA_VERSION,
    SignedUpdateManifest,
    UpdateManifestPayload,
)
from chitlog.core.update_signature import (
    PRODUCTION_UPDATE_KEY_ID,
    PRODUCTION_UPDATE_PUBLIC_KEY_SHA256,
    TRUSTED_UPDATE_PUBLIC_KEYS,
    verify_manifest_signature,
)
from chitlog.core.version import (
    APP_NAME,
    APP_UPDATE_CHANNEL,
    APP_VERSION,
)


_READ_CHUNK_BYTES = 1024 * 1024
_MAX_PRIVATE_KEY_BYTES = 64 * 1024


class ReleaseSigningError(RuntimeError):
    """Raised when release-signing safety checks fail."""


def _sha256_file(path: Path) -> tuple[str, int]:
    digest = hashlib.sha256()
    size = 0
    with path.open("rb") as handle:
        while True:
            chunk = handle.read(_READ_CHUNK_BYTES)
            if not chunk:
                break
            digest.update(chunk)
            size += len(chunk)
    return digest.hexdigest(), size


def _is_within(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
    except ValueError:
        return False
    return True


def expected_installer_path(project_root: Path) -> Path:
    return (
        project_root
        / "release"
        / f"ChitLog-{APP_VERSION}-Setup.exe"
    )


def expected_installer_hash_path(project_root: Path) -> Path:
    return (
        project_root
        / "release"
        / f"ChitLog-{APP_VERSION}-Setup.sha256.txt"
    )


def expected_manifest_path(project_root: Path) -> Path:
    return (
        project_root
        / "release"
        / f"ChitLog-{APP_VERSION}-update-manifest.json"
    )


def expected_manifest_hash_path(project_root: Path) -> Path:
    return (
        project_root
        / "release"
        / f"ChitLog-{APP_VERSION}-update-manifest.sha256.txt"
    )


def expected_release_metadata_path(project_root: Path) -> Path:
    return (
        project_root
        / "release"
        / f"ChitLog-{APP_VERSION}-release-metadata.json"
    )


def validate_release_installer(
    project_root: Path,
) -> tuple[Path, str, int]:
    """Validate and hash the exact installer produced by build_installer.ps1."""

    root = project_root.resolve()
    installer = expected_installer_path(root).resolve()
    expected_installer = expected_installer_path(root).resolve()
    hash_path = expected_installer_hash_path(root).resolve()

    if installer != expected_installer:
        raise ReleaseSigningError(
            "Installer path does not match the expected ChitLog release path."
        )
    if not installer.is_file():
        raise ReleaseSigningError(
            f"Expected release installer was not found: {installer}"
        )
    if installer.is_symlink():
        raise ReleaseSigningError(
            "Refusing to sign metadata for a symbolic-link installer."
        )

    try:
        with installer.open("rb") as handle:
            if handle.read(2) != b"MZ":
                raise ReleaseSigningError(
                    "Release installer is not a Windows PE/NSIS executable."
                )
    except OSError as exc:
        raise ReleaseSigningError(
            "Release installer could not be read safely."
        ) from exc

    digest, size = _sha256_file(installer)
    if size <= 0:
        raise ReleaseSigningError("Release installer is empty.")
    if size > DEFAULT_MAX_INSTALLER_BYTES:
        raise ReleaseSigningError(
            "Release installer exceeds ChitLog's configured download limit."
        )

    if not hash_path.is_file():
        raise ReleaseSigningError(
            "Installer SHA-256 file is missing. "
            "Run packaging/build_installer.ps1 first."
        )

    try:
        recorded = hash_path.read_text(encoding="ascii").strip()
    except (OSError, UnicodeError) as exc:
        raise ReleaseSigningError(
            "Installer SHA-256 file could not be read safely."
        ) from exc

    expected_record = f"{digest}  {installer.name}"
    if recorded != expected_record:
        raise ReleaseSigningError(
            "Installer SHA-256 file does not match the current installer."
        )

    return installer, digest, size


def load_encrypted_ed25519_private_key(
    private_key_path: Path,
    *,
    project_root: Path,
    passphrase: bytes,
) -> Ed25519PrivateKey:
    """Load an encrypted PKCS#8 Ed25519 key kept outside the repository."""

    if not isinstance(passphrase, bytes) or not passphrase:
        raise ReleaseSigningError(
            "A non-empty private-key passphrase is required."
        )

    root = project_root.resolve()
    try:
        key_path = private_key_path.expanduser().resolve(strict=True)
    except OSError as exc:
        raise ReleaseSigningError(
            "Production private-key file was not found."
        ) from exc

    if not key_path.is_file():
        raise ReleaseSigningError(
            "Production private-key path is not a file."
        )
    if private_key_path.is_symlink():
        raise ReleaseSigningError(
            "Refusing to load the production private key through a symlink."
        )
    if _is_within(key_path, root):
        raise ReleaseSigningError(
            "Production private key must remain outside the Git repository."
        )

    try:
        size = key_path.stat().st_size
    except OSError as exc:
        raise ReleaseSigningError(
            "Production private-key file metadata could not be read."
        ) from exc

    if size <= 0 or size > _MAX_PRIVATE_KEY_BYTES:
        raise ReleaseSigningError(
            "Production private-key file has an unexpected size."
        )

    try:
        pem = key_path.read_bytes()
    except OSError as exc:
        raise ReleaseSigningError(
            "Production private-key file could not be read."
        ) from exc

    if b"-----BEGIN ENCRYPTED PRIVATE KEY-----" not in pem:
        raise ReleaseSigningError(
            "Production private key must be encrypted PKCS#8 PEM."
        )

    try:
        key = serialization.load_pem_private_key(
            pem,
            password=passphrase,
        )
    except (TypeError, ValueError) as exc:
        raise ReleaseSigningError(
            "Production private key could not be decrypted or parsed."
        ) from exc

    if not isinstance(key, Ed25519PrivateKey):
        raise ReleaseSigningError(
            "Production private key is not an Ed25519 key."
        )

    return key


def raw_ed25519_public_key(private_key: Ed25519PrivateKey) -> bytes:
    return private_key.public_key().public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )


def validate_private_key_matches_expected_public_key(
    private_key: Ed25519PrivateKey,
    *,
    expected_public_key: bytes,
    expected_public_key_sha256: str,
) -> bytes:
    """Prove the loaded private key belongs to the expected trust anchor."""

    public_key = raw_ed25519_public_key(private_key)
    if public_key != expected_public_key:
        raise ReleaseSigningError(
            "Private key does not match the trusted ChitLog update public key."
        )

    fingerprint = hashlib.sha256(public_key).hexdigest()
    if fingerprint != expected_public_key_sha256:
        raise ReleaseSigningError(
            "Derived update public-key fingerprint does not match ChitLog."
        )

    return public_key


def build_release_payload(
    *,
    installer_name: str,
    installer_sha256: str,
    installer_size: int,
    installer_url: str,
    release_notes_url: str,
    published_at: str,
    minimum_supported_version: str,
    mandatory: bool,
) -> UpdateManifestPayload:
    """Construct the exact strict payload already understood by ChitLog."""

    installer_parsed = urlsplit(installer_url)
    if installer_parsed.query:
        raise ReleaseSigningError(
            "Production installer URL must not contain a query string."
        )
    if Path(installer_parsed.path).name != installer_name:
        raise ReleaseSigningError(
            "Installer URL filename does not match the release installer."
        )

    payload = {
        "app": APP_NAME,
        "version": APP_VERSION,
        "channel": APP_UPDATE_CHANNEL,
        "platform": "windows",
        "architecture": "x64",
        "published_at": published_at,
        "minimum_supported_version": minimum_supported_version,
        "installer_url": installer_url,
        "installer_sha256": installer_sha256,
        "installer_size": installer_size,
        "release_notes_url": release_notes_url,
        "mandatory": mandatory,
    }

    try:
        return UpdateManifestPayload.from_dict(payload)
    except ValueError as exc:
        raise ReleaseSigningError(
            f"Release manifest payload is invalid: {exc}"
        ) from exc


def create_signed_manifest_bytes(
    payload: UpdateManifestPayload,
    private_key: Ed25519PrivateKey,
    *,
    key_id: str,
) -> bytes:
    """Create deterministic compact JSON around a deterministic Ed25519 signature."""

    signature = private_key.sign(payload.canonical_bytes())
    document = {
        "schema_version": MANIFEST_SCHEMA_VERSION,
        "key_id": key_id,
        "payload": payload.to_dict(),
        "signature": base64.b64encode(signature).decode("ascii"),
    }
    return (
        json.dumps(
            document,
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        + b"\n"
    )


def verify_generated_manifest(
    raw_manifest: bytes,
    *,
    trusted_keys: Mapping[str, bytes],
) -> UpdateManifestPayload:
    """Strictly parse and cryptographically verify generated public output."""

    manifest = SignedUpdateManifest.from_json_bytes(raw_manifest)
    return verify_manifest_signature(
        manifest,
        trusted_keys=trusted_keys,
    )


def _atomic_write(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".part")

    try:
        with temporary.open("wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass


def write_public_release_artifacts(
    project_root: Path,
    *,
    raw_manifest: bytes,
    payload: UpdateManifestPayload,
    installer_name: str,
    installer_sha256: str,
    installer_size: int,
) -> tuple[Path, Path, Path, str]:
    """Atomically write public release metadata only under ignored release/."""

    root = project_root.resolve()
    release_dir = (root / "release").resolve()

    manifest_path = expected_manifest_path(root).resolve()
    manifest_hash_path = expected_manifest_hash_path(root).resolve()
    metadata_path = expected_release_metadata_path(root).resolve()

    for output in (manifest_path, manifest_hash_path, metadata_path):
        if output.parent != release_dir:
            raise ReleaseSigningError(
                "Release-signing output escaped the release directory."
            )

    manifest_sha256 = hashlib.sha256(raw_manifest).hexdigest()

    manifest_hash_text = (
        f"{manifest_sha256}  {manifest_path.name}\n"
    ).encode("ascii")

    metadata = {
        "app": APP_NAME,
        "version": APP_VERSION,
        "channel": APP_UPDATE_CHANNEL,
        "key_id": PRODUCTION_UPDATE_KEY_ID,
        "public_key_sha256": PRODUCTION_UPDATE_PUBLIC_KEY_SHA256,
        "published_at": payload.published_at,
        "minimum_supported_version": payload.minimum_supported_version,
        "mandatory": payload.mandatory,
        "installer_name": installer_name,
        "installer_url": payload.installer_url,
        "installer_sha256": installer_sha256,
        "installer_size": installer_size,
        "manifest_name": manifest_path.name,
        "manifest_sha256": manifest_sha256,
        "release_notes_url": payload.release_notes_url,
    }
    metadata_bytes = (
        json.dumps(
            metadata,
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        + b"\n"
    )

    _atomic_write(manifest_path, raw_manifest)
    _atomic_write(manifest_hash_path, manifest_hash_text)
    _atomic_write(metadata_path, metadata_bytes)

    return (
        manifest_path,
        manifest_hash_path,
        metadata_path,
        manifest_sha256,
    )


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Create ChitLog's deterministic production update manifest "
            "using the offline encrypted Ed25519 release key."
        )
    )
    parser.add_argument(
        "--private-key",
        required=True,
        type=Path,
        help=(
            "Path to encrypted PKCS#8 Ed25519 private key kept outside "
            "the ChitLog repository."
        ),
    )
    parser.add_argument(
        "--installer-url",
        required=True,
        help="Final direct HTTPS URL for ChitLog-<version>-Setup.exe.",
    )
    parser.add_argument(
        "--release-notes-url",
        required=True,
        help="Final HTTPS release-notes URL.",
    )
    parser.add_argument(
        "--published-at",
        required=True,
        help="Explicit UTC ISO-8601 timestamp ending in Z.",
    )
    parser.add_argument(
        "--minimum-supported-version",
        required=True,
        help="Oldest ChitLog version still supported by this release.",
    )
    parser.add_argument(
        "--mandatory",
        action="store_true",
        help="Mark this release as mandatory.",
    )
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    project_root = Path(__file__).resolve().parents[1]

    try:
        installer, installer_sha256, installer_size = (
            validate_release_installer(project_root)
        )

        passphrase_text = getpass.getpass(
            "Production update private-key passphrase: "
        )
        if not passphrase_text:
            raise ReleaseSigningError(
                "Private-key passphrase cannot be empty."
            )

        private_key = load_encrypted_ed25519_private_key(
            args.private_key,
            project_root=project_root,
            passphrase=passphrase_text.encode("utf-8"),
        )

        expected_public_key = TRUSTED_UPDATE_PUBLIC_KEYS.get(
            PRODUCTION_UPDATE_KEY_ID
        )
        if expected_public_key is None:
            raise ReleaseSigningError(
                "Production update key ID is not trusted by this source tree."
            )

        validate_private_key_matches_expected_public_key(
            private_key,
            expected_public_key=expected_public_key,
            expected_public_key_sha256=(
                PRODUCTION_UPDATE_PUBLIC_KEY_SHA256
            ),
        )

        payload = build_release_payload(
            installer_name=installer.name,
            installer_sha256=installer_sha256,
            installer_size=installer_size,
            installer_url=args.installer_url,
            release_notes_url=args.release_notes_url,
            published_at=args.published_at,
            minimum_supported_version=args.minimum_supported_version,
            mandatory=bool(args.mandatory),
        )

        raw_manifest = create_signed_manifest_bytes(
            payload,
            private_key,
            key_id=PRODUCTION_UPDATE_KEY_ID,
        )

        verified_payload = verify_generated_manifest(
            raw_manifest,
            trusted_keys=TRUSTED_UPDATE_PUBLIC_KEYS,
        )
        if verified_payload != payload:
            raise ReleaseSigningError(
                "Generated manifest did not verify back to the exact payload."
            )

        (
            manifest_path,
            manifest_hash_path,
            metadata_path,
            manifest_sha256,
        ) = write_public_release_artifacts(
            project_root,
            raw_manifest=raw_manifest,
            payload=payload,
            installer_name=installer.name,
            installer_sha256=installer_sha256,
            installer_size=installer_size,
        )

    except (OSError, ValueError, ReleaseSigningError) as exc:
        print(f"CHITLOG RELEASE SIGNING: FAIL: {exc}")
        return 1

    print()
    print("CHITLOG STEP 11A RELEASE MANIFEST SIGNING: PASS")
    print(f"Version:              {APP_VERSION}")
    print(f"Channel:              {APP_UPDATE_CHANNEL}")
    print(f"Key ID:               {PRODUCTION_UPDATE_KEY_ID}")
    print(
        "Public key SHA256:    "
        f"{PRODUCTION_UPDATE_PUBLIC_KEY_SHA256}"
    )
    print(f"Installer:            {installer}")
    print(f"Installer size:       {installer_size} bytes")
    print(f"Installer SHA256:     {installer_sha256}")
    print(f"Manifest:             {manifest_path}")
    print(f"Manifest SHA256:      {manifest_sha256}")
    print(f"Manifest hash file:   {manifest_hash_path}")
    print(f"Release metadata:     {metadata_path}")
    print()
    print("The private key and passphrase were not written to release output.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
