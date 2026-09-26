"""Standalone ChitLog updater process skeleton.

Step 7B deliberately stops before installer execution. It accepts exactly one
handoff file, independently verifies it, waits for the originating ChitLog
process to exit, and verifies the handoff/installer again.

Later updater stages may execute an installer only after this preparation
function succeeds.
"""
from __future__ import annotations

import argparse
from collections.abc import Callable, Sequence
from pathlib import Path
import sys

from chitlog.core.update_handoff import (
    UpdateHandoffError,
    VerifiedUpdateHandoff,
    load_and_verify_update_handoff,
)
from chitlog.core.update_process_wait import (
    UpdateProcessWaitError,
    wait_for_process_exit,
)


EXIT_READY_NO_EXECUTION = 0
EXIT_HANDOFF_REJECTED = 20
EXIT_PARENT_WAIT_FAILED = 21
EXIT_HANDOFF_CHANGED = 22


class UpdatePreparationError(RuntimeError):
    """Raised when the standalone updater cannot prepare safely."""


class UpdateHandoffChangedError(UpdatePreparationError):
    """Raised when local handoff metadata changes while ChitLog exits."""


HandoffVerifier = Callable[[str | Path], VerifiedUpdateHandoff]
ParentWaiter = Callable[[int], None]


def prepare_standalone_update(
    handoff_path: str | Path,
    *,
    verifier: HandoffVerifier = load_and_verify_update_handoff,
    waiter: ParentWaiter = wait_for_process_exit,
) -> VerifiedUpdateHandoff:
    """Verify, wait for ChitLog to exit, then verify everything again."""

    before = verifier(handoff_path)
    parent_pid = before.handoff.parent_pid

    waiter(parent_pid)

    # Re-read and re-verify after the wait. This catches installer or handoff
    # tampering that occurs while the updater is waiting for ChitLog to exit.
    after = verifier(handoff_path)

    if before.handoff != after.handoff:
        raise UpdateHandoffChangedError(
            "Update handoff changed while waiting for ChitLog to exit."
        )

    if before.payload != after.payload:
        raise UpdateHandoffChangedError(
            "Verified update payload changed while waiting for ChitLog."
        )

    return after


def build_argument_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="ChitLogUpdater",
        description=(
            "Verify a ChitLog update handoff and wait for ChitLog to exit. "
            "Installer execution is not enabled in this build."
        ),
    )
    parser.add_argument(
        "--handoff",
        required=True,
        help="Absolute path to the local ChitLog updater handoff JSON file.",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_argument_parser()
    args = parser.parse_args(argv)

    handoff_path = Path(args.handoff)
    if not handoff_path.is_absolute():
        sys.stderr.write(
            "ChitLog Updater rejected the handoff path: "
            "an absolute path is required.\n"
        )
        return EXIT_HANDOFF_REJECTED

    try:
        verified = prepare_standalone_update(handoff_path)
    except UpdateHandoffError:
        sys.stderr.write(
            "ChitLog Updater rejected the update handoff. "
            "Nothing was installed.\n"
        )
        return EXIT_HANDOFF_REJECTED
    except UpdateProcessWaitError:
        sys.stderr.write(
            "ChitLog Updater could not safely wait for ChitLog to exit. "
            "Nothing was installed.\n"
        )
        return EXIT_PARENT_WAIT_FAILED
    except UpdateHandoffChangedError:
        sys.stderr.write(
            "ChitLog Updater detected a handoff change while waiting. "
            "Nothing was installed.\n"
        )
        return EXIT_HANDOFF_CHANGED

    sys.stdout.write(
        "ChitLog update is verified and the application has exited. "
        f"Version {verified.payload.version} is ready. "
        "Installer execution is not enabled in this build.\n"
    )
    return EXIT_READY_NO_EXECUTION


if __name__ == "__main__":
    raise SystemExit(main())
