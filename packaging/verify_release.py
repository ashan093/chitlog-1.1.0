"""Fail closed on common ChitLog release-packaging mistakes."""
from __future__ import annotations

import argparse
from pathlib import Path
import hashlib
import sys

REQUIRED_ROOT_FILES = (
    "ChitLog.exe",
    "EULA.txt",
    "THIRD_PARTY_NOTICES.txt",
    "QT_LGPL_COMPLIANCE.txt",
)
FORBIDDEN_SUFFIXES = {
    ".db",
    ".sqlite",
    ".sqlite3",
    ".chitlogbak",
    ".log",
    ".pem",
    ".key",
    ".pfx",
    ".p12",
}
FORBIDDEN_NAME_FRAGMENTS = (
    "oauth_token",
    "refresh_token",
    "client_secret",
    "credentials.json",
)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def verify(release_dir: Path, project_root: Path) -> None:
    release_dir = release_dir.resolve()
    project_root = project_root.resolve()

    if not release_dir.is_dir():
        raise RuntimeError(f"Release directory does not exist: {release_dir}")

    for filename in REQUIRED_ROOT_FILES:
        if not (release_dir / filename).is_file():
            raise RuntimeError(f"Missing required release file: {filename}")

    license_dir = release_dir / "LICENSES"
    if not (license_dir / "RUNTIME_DEPENDENCIES.txt").is_file():
        raise RuntimeError("LICENSES/RUNTIME_DEPENDENCIES.txt is missing.")

    bad_files = []
    for path in release_dir.rglob("*"):
        if not path.is_file():
            continue
        lowered = path.name.lower()
        if path.suffix.lower() in FORBIDDEN_SUFFIXES:
            bad_files.append(path.relative_to(release_dir))
        elif any(fragment in lowered for fragment in FORBIDDEN_NAME_FRAGMENTS):
            bad_files.append(path.relative_to(release_dir))
    if bad_files:
        joined = ", ".join(str(item) for item in bad_files[:10])
        raise RuntimeError(f"Sensitive/user-data-like files found in release: {joined}")

    # Step 24 requires that developer workstation paths do not leak into release files.
    probes = {
        str(project_root),
        str(project_root).replace("\\", "/"),
    }
    encoded_probes = []
    for probe in probes:
        encoded_probes.append(probe.encode("utf-8", errors="ignore"))
        encoded_probes.append(probe.encode("utf-16-le", errors="ignore"))

    leaked = []
    for path in release_dir.rglob("*"):
        if not path.is_file():
            continue
        try:
            data = path.read_bytes()
        except OSError:
            continue
        if any(probe and probe in data for probe in encoded_probes):
            leaked.append(path.relative_to(release_dir))
    if leaked:
        joined = ", ".join(str(item) for item in leaked[:10])
        raise RuntimeError(f"Developer project path leaked into release files: {joined}")

    exe_hash = _sha256(release_dir / "ChitLog.exe")
    (release_dir / "SHA256SUMS.txt").write_text(
        f"{exe_hash}  ChitLog.exe\n",
        encoding="ascii",
    )
    print("Release verification: PASS")
    print(f"ChitLog.exe SHA256: {exe_hash}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--release-dir", required=True, type=Path)
    parser.add_argument("--project-root", required=True, type=Path)
    args = parser.parse_args()
    try:
        verify(args.release_dir, args.project_root)
    except RuntimeError as error:
        print(f"Release verification failed: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
