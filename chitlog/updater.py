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
    resolve_process_image_path,
    wait_for_process_exit,
)
from chitlog.core.update_application_relaunch import (
    ApplicationRelaunchError,
    relaunch_updated_application,
)
from chitlog.core.update_installer_execution import (
    InstallerConsentCancelledError,
    InstallerExecutionError,
    InstallerExitCodeError,
    execute_verified_installer,
)


EXIT_INSTALL_SUCCEEDED = 0
EXIT_HANDOFF_REJECTED = 20
EXIT_PARENT_WAIT_FAILED = 21
EXIT_HANDOFF_CHANGED = 22
EXIT_INSTALLER_FAILED = 23
EXIT_INSTALLER_CANCELLED = 24
EXIT_RELAUNCH_FAILED = 25


class UpdatePreparationError(RuntimeError):
    """Raised when the standalone updater cannot prepare safely."""


class UpdateHandoffChangedError(UpdatePreparationError):
    """Raised when local handoff metadata changes while ChitLog exits."""


HandoffVerifier = Callable[[str | Path], VerifiedUpdateHandoff]
ParentWaiter = Callable[[int], None]
ProcessImageResolver = Callable[[int], Path]


def prepare_standalone_update(
    handoff_path: str | Path,
    *,
    verifier: HandoffVerifier = load_and_verify_update_handoff,
    waiter: ParentWaiter = wait_for_process_exit,
    process_image_resolver: ProcessImageResolver = resolve_process_image_path,
) -> VerifiedUpdateHandoff:
    """Verify, wait for ChitLog to exit, then verify everything again."""

    before = verifier(handoff_path)
    parent_pid = before.handoff.parent_pid

    # The outer handoff contains a local application path and is not itself
    # signed. Bind that path to the OS-reported executable of the still-running
    # ChitLog parent process before allowing the updater to continue.
    parent_image = process_image_resolver(parent_pid)
    expected_application = before.application_path.resolve(strict=False)
    if parent_image.resolve(strict=False) != expected_application:
        raise UpdateHandoffChangedError(
            "Update handoff application path does not match the originating ChitLog process."
        )

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
            "Verify a ChitLog update handoff, wait for ChitLog to exit, "
            "and run only the re-verified signed installer."
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

    try:
        result = execute_verified_installer(verified)
    except InstallerConsentCancelledError:
        sys.stderr.write(
            "ChitLog update installation was cancelled. "
            "No installer was forced to continue.\n"
        )
        return EXIT_INSTALLER_CANCELLED
    except InstallerExitCodeError:
        sys.stderr.write(
            "The ChitLog installer returned a failure status. "
            "The updater will not report success.\n"
        )
        return EXIT_INSTALLER_FAILED
    except InstallerExecutionError:
        sys.stderr.write(
            "ChitLog Updater refused or failed to run the verified installer. "
            "The updater will not report success.\n"
        )
        return EXIT_INSTALLER_FAILED

    try:
        relaunch = relaunch_updated_application(verified)
    except ApplicationRelaunchError:
        sys.stderr.write(
            f"ChitLog {verified.payload.version} was installed successfully, "
            "but the updated application could not be restarted automatically. "
            "Start ChitLog manually.\n"
        )
        return EXIT_RELAUNCH_FAILED

    sys.stdout.write(
        f"ChitLog {verified.payload.version} installer completed successfully "
        f"with exit code {result.exit_code}; ChitLog restarted as process "
        f"{relaunch.process_id}.\n"
    )
    return EXIT_INSTALL_SUCCEEDED


if __name__ == "__main__":
    raise SystemExit(main())
