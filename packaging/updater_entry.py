"""Windowless entry point for the frozen ChitLog standalone updater.

The main updater core intentionally remains UI-framework independent. This
packaging entry point supplies two production-only concerns:

* safe stdout/stderr sinks for a Windows GUI-subsystem executable; and
* a small native Windows failure dialog if the updater cannot complete.

It also exposes an internal frozen self-test used only by the release build
verification script. The self-test contains a public Ed25519 test vector only;
no ChitLog private signing key is ever packaged.
"""
from __future__ import annotations

import ctypes
import os
import sys
from typing import TextIO


_SELF_TEST_FLAG = "--chitlog-updater-self-test"
_SELF_TEST_FAILURE = 91


def _ensure_output_streams() -> tuple[TextIO | None, TextIO | None]:
    """Give windowed PyInstaller builds harmless writable output streams."""

    opened: list[TextIO] = []

    def ensure(stream):
        if stream is not None:
            return stream
        sink = open(os.devnull, "w", encoding="utf-8")
        opened.append(sink)
        return sink

    sys.stdout = ensure(sys.stdout)
    sys.stderr = ensure(sys.stderr)

    stdout = opened[0] if opened else None
    stderr = opened[1] if len(opened) > 1 else None
    return stdout, stderr


def _frozen_self_test() -> int:
    """Verify the updater's critical imports inside the frozen executable."""

    try:
        from cryptography.hazmat.primitives.asymmetric.ed25519 import (
            Ed25519PublicKey,
        )

        from chitlog.core.update_handoff import load_and_verify_update_handoff
        from chitlog.core.update_installer_execution import (
            execute_verified_installer,
        )
        from chitlog.core.update_process_wait import wait_for_process_exit
        from chitlog.core.update_signature import verify_manifest_signature

        # RFC 8032 Ed25519 test vector 1: empty message. Public material only.
        public_key = bytes.fromhex(
            "d75a980182b10ab7d54bfed3c964073a"
            "0ee172f3daa62325af021a68f707511a"
        )
        signature = bytes.fromhex(
            "e5564300c360ac729086e2cc806e828a"
            "84877f1eb8e5d974d873e06522490155"
            "5fb8821590a33bacc61e39701cf9b46b"
            "d25bf5f0595bbe24655141438e7a100b"
        )
        Ed25519PublicKey.from_public_bytes(public_key).verify(signature, b"")

        # Referencing the imported callables prevents an accidental packaging
        # refactor from making these imports effectively dead.
        required = (
            load_and_verify_update_handoff,
            execute_verified_installer,
            wait_for_process_exit,
            verify_manifest_signature,
        )
        if not all(callable(item) for item in required):
            return _SELF_TEST_FAILURE
    except Exception:
        return _SELF_TEST_FAILURE

    return 0


def _failure_message(exit_code: int) -> str:
    if exit_code == 20:
        return (
            "ChitLog rejected the update handoff. Nothing was installed. "
            "Open ChitLog and check for updates again."
        )
    if exit_code in {21, 22}:
        return (
            "ChitLog could not safely prepare the update. Nothing was "
            "installed. Start ChitLog and try again."
        )
    if exit_code == 23:
        return (
            "The ChitLog installer did not complete successfully. "
            "Your existing ChitLog data was not intentionally removed."
        )
    if exit_code == 24:
        return "The ChitLog update was cancelled."
    if exit_code == 25:
        return (
            "The ChitLog update installed successfully, but ChitLog could not "
            "reopen automatically. Start ChitLog normally from the Start menu "
            "or desktop shortcut."
        )
    return (
        "The ChitLog updater could not complete safely. Start ChitLog "
        "normally and try the update again."
    )


def _show_failure(exit_code: int) -> None:
    """Show a fixed native Windows message without Qt or embedded web UI."""

    if os.name != "nt" or exit_code == 0:
        return

    try:
        user32 = ctypes.WinDLL("user32", use_last_error=True)
        message_box = user32.MessageBoxW
        message_box.argtypes = [
            ctypes.c_void_p,
            ctypes.c_wchar_p,
            ctypes.c_wchar_p,
            ctypes.c_uint,
        ]
        message_box.restype = ctypes.c_int

        mb_ok = 0x00000000
        mb_iconwarning = 0x00000030
        mb_setforeground = 0x00010000

        message_box(
            None,
            _failure_message(exit_code),
            "ChitLog Update",
            mb_ok | mb_iconwarning | mb_setforeground,
        )
    except Exception:
        # Failure reporting must never create a second updater failure.
        return


def main() -> int:
    opened = _ensure_output_streams()

    try:
        if sys.argv[1:] == [_SELF_TEST_FLAG]:
            return _frozen_self_test()

        from chitlog.updater import main as updater_main

        exit_code = int(updater_main())
        if exit_code != 0:
            _show_failure(exit_code)
        return exit_code
    finally:
        for stream in opened:
            if stream is not None:
                try:
                    stream.close()
                except Exception:
                    pass


if __name__ == "__main__":
    raise SystemExit(main())
