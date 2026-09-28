"""Release-time verification for the frozen ChitLogUpdater.exe."""
from __future__ import annotations

import argparse
import hashlib
from pathlib import Path
import struct
import subprocess
import sys


MAX_UPDATER_BYTES = 200 * 1024 * 1024
EXPECTED_MACHINE_AMD64 = 0x8664
SELF_TEST_FLAG = "--chitlog-updater-self-test"


class VerificationError(RuntimeError):
    pass


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while True:
            chunk = handle.read(1024 * 1024)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def verify_pe(path: Path) -> None:
    size = path.stat().st_size
    if size <= 0:
        raise VerificationError("ChitLogUpdater.exe is empty.")
    if size > MAX_UPDATER_BYTES:
        raise VerificationError("ChitLogUpdater.exe exceeds the safety limit.")

    with path.open("rb") as handle:
        dos = handle.read(64)
        if len(dos) != 64 or dos[:2] != b"MZ":
            raise VerificationError("ChitLogUpdater.exe has no MZ header.")

        pe_offset = struct.unpack_from("<I", dos, 0x3C)[0]
        if pe_offset < 64 or pe_offset > size - 6:
            raise VerificationError("ChitLogUpdater.exe has an invalid PE offset.")

        handle.seek(pe_offset)
        header = handle.read(6)

    if len(header) != 6 or header[:4] != b"PE\x00\x00":
        raise VerificationError("ChitLogUpdater.exe has no PE signature.")

    machine = struct.unpack_from("<H", header, 4)[0]
    if machine != EXPECTED_MACHINE_AMD64:
        raise VerificationError(
            f"ChitLogUpdater.exe is not x64 (machine=0x{machine:04X})."
        )


def run_frozen_self_test(path: Path) -> None:
    try:
        completed = subprocess.run(
            [str(path), SELF_TEST_FLAG],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
            timeout=45,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise VerificationError(
            "Frozen updater self-test could not be completed."
        ) from exc

    if completed.returncode != 0:
        raise VerificationError(
            "Frozen updater self-test failed "
            f"(exit code {completed.returncode})."
        )


def verify_frozen_updater(value: str | Path) -> tuple[int, str]:
    path = Path(value)
    if not path.is_absolute():
        raise VerificationError("Updater verification path must be absolute.")

    if path.is_symlink():
        raise VerificationError("ChitLogUpdater.exe must not be a symlink.")

    try:
        path = path.resolve(strict=True)
    except OSError as exc:
        raise VerificationError(
            "ChitLogUpdater.exe could not be resolved."
        ) from exc

    if not path.is_file() or path.name != "ChitLogUpdater.exe":
        raise VerificationError(
            "Expected an existing file named ChitLogUpdater.exe."
        )

    verify_pe(path)
    run_frozen_self_test(path)
    return path.stat().st_size, _sha256(path)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("updater", help="Absolute path to ChitLogUpdater.exe")
    args = parser.parse_args(argv)

    try:
        size, digest = verify_frozen_updater(args.updater)
    except VerificationError as exc:
        print(f"FROZEN CHITLOG UPDATER VERIFICATION: FAIL: {exc}")
        return 1

    print("FROZEN CHITLOG UPDATER VERIFICATION: PASS")
    print(f"Size:   {size} bytes")
    print(f"SHA256: {digest}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
