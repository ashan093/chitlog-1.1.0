"""Step 11A tests for ChitLog's offline deterministic release signer."""
from __future__ import annotations

import base64
import hashlib
import importlib.util
import json
from pathlib import Path

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
)

from chitlog.core.update_manifest import SignedUpdateManifest
from chitlog.core.update_signature import InvalidUpdateSignatureError
from chitlog.core.version import APP_VERSION


ROOT = Path(__file__).resolve().parents[1]
SIGNER_PATH = ROOT / "packaging/create_signed_update_manifest.py"
WRAPPER_PATH = ROOT / "packaging/sign_release_manifest.ps1"


def load_signer():
    spec = importlib.util.spec_from_file_location(
        "chitlog_step11_release_signer",
        SIGNER_PATH,
    )
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def encrypted_key_file(
    directory: Path,
    private_key: Ed25519PrivateKey,
    password: bytes,
) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / "release-key.pem"
    path.write_bytes(
        private_key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.BestAvailableEncryption(
                password
            ),
        )
    )
    return path


def unencrypted_key_file(
    directory: Path,
    private_key: Ed25519PrivateKey,
) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / "release-key.pem"
    path.write_bytes(
        private_key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption(),
        )
    )
    return path


def make_release_installer(module, project_root: Path) -> tuple[Path, str]:
    release = project_root / "release"
    release.mkdir(parents=True)
    installer = (
        release / f"ChitLog-{APP_VERSION}-Setup.exe"
    )
    installer.write_bytes(b"MZ" + b"test-installer" * 32)

    digest = hashlib.sha256(installer.read_bytes()).hexdigest()
    (
        release / f"ChitLog-{APP_VERSION}-Setup.sha256.txt"
    ).write_text(
        f"{digest}  {installer.name}\n",
        encoding="ascii",
    )
    return installer, digest


def test_signer_is_packaging_only_and_has_no_secret_cli_argument():
    source = SIGNER_PATH.read_text(encoding="utf-8")
    wrapper = WRAPPER_PATH.read_text(encoding="utf-8")

    assert "Ed25519PrivateKey" in source
    assert "--passphrase" not in source
    assert "--passphrase" not in wrapper
    assert "getpass.getpass" in source

    for forbidden in (
        r"C:\Users\\",
        "BEGIN PRIVATE KEY-----\nM",
        "BEGIN ENCRYPTED PRIVATE KEY-----\nM",
    ):
        assert forbidden not in source
        assert forbidden not in wrapper


def test_encrypted_ed25519_private_key_loads_outside_repository(tmp_path):
    signer = load_signer()
    project_root = tmp_path / "project"
    project_root.mkdir()
    key_root = tmp_path / "offline"
    password = b"test-passphrase-only"

    private_key = Ed25519PrivateKey.generate()
    key_path = encrypted_key_file(
        key_root,
        private_key,
        password,
    )

    loaded = signer.load_encrypted_ed25519_private_key(
        key_path,
        project_root=project_root,
        passphrase=password,
    )

    assert signer.raw_ed25519_public_key(loaded) == (
        signer.raw_ed25519_public_key(private_key)
    )


def test_unencrypted_private_key_is_rejected(tmp_path):
    signer = load_signer()
    project_root = tmp_path / "project"
    project_root.mkdir()
    key_path = unencrypted_key_file(
        tmp_path / "offline",
        Ed25519PrivateKey.generate(),
    )

    with pytest.raises(
        signer.ReleaseSigningError,
        match="encrypted PKCS#8",
    ):
        signer.load_encrypted_ed25519_private_key(
            key_path,
            project_root=project_root,
            passphrase=b"irrelevant",
        )


def test_private_key_inside_repository_is_rejected(tmp_path):
    signer = load_signer()
    project_root = tmp_path / "project"
    project_root.mkdir()
    password = b"test-passphrase-only"
    key_path = encrypted_key_file(
        project_root / "secrets",
        Ed25519PrivateKey.generate(),
        password,
    )

    with pytest.raises(
        signer.ReleaseSigningError,
        match="outside the Git repository",
    ):
        signer.load_encrypted_ed25519_private_key(
            key_path,
            project_root=project_root,
            passphrase=password,
        )


def test_private_key_must_match_expected_public_key():
    signer = load_signer()
    expected_private = Ed25519PrivateKey.generate()
    wrong_private = Ed25519PrivateKey.generate()

    expected_public = signer.raw_ed25519_public_key(expected_private)
    expected_fingerprint = hashlib.sha256(
        expected_public
    ).hexdigest()

    with pytest.raises(
        signer.ReleaseSigningError,
        match="does not match",
    ):
        signer.validate_private_key_matches_expected_public_key(
            wrong_private,
            expected_public_key=expected_public,
            expected_public_key_sha256=expected_fingerprint,
        )


def test_installer_validation_requires_exact_build_hash(tmp_path):
    signer = load_signer()
    project_root = tmp_path / "project"
    project_root.mkdir()
    installer, digest = make_release_installer(
        signer,
        project_root,
    )

    returned_path, returned_digest, returned_size = (
        signer.validate_release_installer(project_root)
    )

    assert returned_path == installer.resolve()
    assert returned_digest == digest
    assert returned_size == installer.stat().st_size

    hash_path = (
        project_root
        / "release"
        / f"ChitLog-{APP_VERSION}-Setup.sha256.txt"
    )
    hash_path.write_text(
        f"{'0' * 64}  {installer.name}\n",
        encoding="ascii",
    )

    with pytest.raises(
        signer.ReleaseSigningError,
        match="does not match",
    ):
        signer.validate_release_installer(project_root)


def test_payload_reuses_strict_runtime_manifest_schema(tmp_path):
    signer = load_signer()
    project_root = tmp_path / "project"
    project_root.mkdir()
    installer, digest = make_release_installer(
        signer,
        project_root,
    )

    payload = signer.build_release_payload(
        installer_name=installer.name,
        installer_sha256=digest,
        installer_size=installer.stat().st_size,
        installer_url=(
            "https://downloads.example.test/"
            f"{installer.name}"
        ),
        release_notes_url=(
            "https://www.example.test/releases/"
            f"{APP_VERSION}"
        ),
        published_at="2026-09-29T00:00:00Z",
        minimum_supported_version="1.0.0",
        mandatory=False,
    )

    assert payload.version == APP_VERSION
    assert payload.channel == "stable"
    assert payload.platform == "windows"
    assert payload.architecture == "x64"


def test_installer_url_filename_must_match_release(tmp_path):
    signer = load_signer()

    with pytest.raises(
        signer.ReleaseSigningError,
        match="filename",
    ):
        signer.build_release_payload(
            installer_name=(
                f"ChitLog-{APP_VERSION}-Setup.exe"
            ),
            installer_sha256="a" * 64,
            installer_size=123,
            installer_url=(
                "https://downloads.example.test/wrong.exe"
            ),
            release_notes_url=(
                "https://www.example.test/releases/"
                f"{APP_VERSION}"
            ),
            published_at="2026-09-29T00:00:00Z",
            minimum_supported_version="1.0.0",
            mandatory=False,
        )


def test_manifest_signing_is_deterministic_and_strictly_verifiable():
    signer = load_signer()
    private_key = Ed25519PrivateKey.generate()
    public_key = signer.raw_ed25519_public_key(private_key)

    payload = signer.build_release_payload(
        installer_name=f"ChitLog-{APP_VERSION}-Setup.exe",
        installer_sha256="a" * 64,
        installer_size=123456,
        installer_url=(
            "https://downloads.example.test/"
            f"ChitLog-{APP_VERSION}-Setup.exe"
        ),
        release_notes_url=(
            "https://www.example.test/releases/"
            f"{APP_VERSION}"
        ),
        published_at="2026-09-29T00:00:00Z",
        minimum_supported_version="1.0.0",
        mandatory=False,
    )

    first = signer.create_signed_manifest_bytes(
        payload,
        private_key,
        key_id="test-release-key",
    )
    second = signer.create_signed_manifest_bytes(
        payload,
        private_key,
        key_id="test-release-key",
    )

    assert first == second
    assert not first.startswith(b"\xef\xbb\xbf")

    verified = signer.verify_generated_manifest(
        first,
        trusted_keys={"test-release-key": public_key},
    )
    assert verified == payload


def test_generated_manifest_tampering_is_rejected():
    signer = load_signer()
    private_key = Ed25519PrivateKey.generate()
    public_key = signer.raw_ed25519_public_key(private_key)

    payload = signer.build_release_payload(
        installer_name=f"ChitLog-{APP_VERSION}-Setup.exe",
        installer_sha256="a" * 64,
        installer_size=123456,
        installer_url=(
            "https://downloads.example.test/"
            f"ChitLog-{APP_VERSION}-Setup.exe"
        ),
        release_notes_url=(
            "https://www.example.test/releases/"
            f"{APP_VERSION}"
        ),
        published_at="2026-09-29T00:00:00Z",
        minimum_supported_version="1.0.0",
        mandatory=False,
    )

    raw = signer.create_signed_manifest_bytes(
        payload,
        private_key,
        key_id="test-release-key",
    )
    document = json.loads(raw.decode("utf-8"))
    document["payload"]["installer_size"] += 1
    tampered = (
        json.dumps(
            document,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        + b"\n"
    )

    parsed = SignedUpdateManifest.from_json_bytes(tampered)
    with pytest.raises(InvalidUpdateSignatureError):
        signer.verify_manifest_signature(
            parsed,
            trusted_keys={"test-release-key": public_key},
        )


def test_public_release_artifacts_contain_no_private_material(tmp_path):
    signer = load_signer()
    project_root = tmp_path / "project"
    project_root.mkdir()
    private_key = Ed25519PrivateKey.generate()

    payload = signer.build_release_payload(
        installer_name=f"ChitLog-{APP_VERSION}-Setup.exe",
        installer_sha256="b" * 64,
        installer_size=987654,
        installer_url=(
            "https://downloads.example.test/"
            f"ChitLog-{APP_VERSION}-Setup.exe"
        ),
        release_notes_url=(
            "https://www.example.test/releases/"
            f"{APP_VERSION}"
        ),
        published_at="2026-09-29T00:00:00Z",
        minimum_supported_version="1.0.0",
        mandatory=False,
    )
    raw = signer.create_signed_manifest_bytes(
        payload,
        private_key,
        key_id=signer.PRODUCTION_UPDATE_KEY_ID,
    )

    outputs = signer.write_public_release_artifacts(
        project_root,
        raw_manifest=raw,
        payload=payload,
        installer_name=f"ChitLog-{APP_VERSION}-Setup.exe",
        installer_sha256="b" * 64,
        installer_size=987654,
    )

    for path in outputs[:3]:
        content = path.read_bytes()
        assert b"PRIVATE KEY" not in content
        assert b"passphrase" not in content.lower()

class _SymlinkProbe:
    """Fake lexical path proving symlink rejection happens before resolve()."""

    def __init__(self):
        self.resolve_called = False

    def is_symlink(self):
        return True

    def resolve(self, *args, **kwargs):
        self.resolve_called = True
        raise AssertionError("resolve() must not be called for a symlink")


class _KeySymlinkProbe(_SymlinkProbe):
    def expanduser(self):
        return self


def test_installer_symlink_is_rejected_before_resolution(
    tmp_path,
    monkeypatch,
):
    signer = load_signer()
    project_root = tmp_path / "project"
    project_root.mkdir()
    probe = _SymlinkProbe()

    monkeypatch.setattr(
        signer,
        "expected_installer_path",
        lambda _root: probe,
    )

    with pytest.raises(
        signer.ReleaseSigningError,
        match="symbolic-link installer",
    ):
        signer.validate_release_installer(project_root)

    assert probe.resolve_called is False


def test_private_key_symlink_is_rejected_before_resolution(tmp_path):
    signer = load_signer()
    project_root = tmp_path / "project"
    project_root.mkdir()
    probe = _KeySymlinkProbe()

    with pytest.raises(
        signer.ReleaseSigningError,
        match="private key through a symlink",
    ):
        signer.load_encrypted_ed25519_private_key(
            probe,
            project_root=project_root,
            passphrase=b"test-passphrase-only",
        )

    assert probe.resolve_called is False
