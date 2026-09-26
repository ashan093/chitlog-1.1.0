"""Qt-threaded main-app handoff to the standalone ChitLog updater.

This runner performs only the local Step 7D preparation path: it stages the
packaged updater, creates the signed handoff, and starts the standalone updater
process. It never installs software itself and never manipulates Qt widgets
from the worker thread.
"""
from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path

from PySide6.QtCore import QCoreApplication, QObject, QThread, Signal, Slot

from chitlog.core.update_checker import UpdateCheckOutcome
from chitlog.core.update_handoff import (
    UpdateHandoffError,
    UpdateHandoffPathError,
    UpdateHandoffSecurityError,
)
from chitlog.core.update_installer_staging import VerifiedInstallerArtifact
from chitlog.core.update_updater_launch import (
    UpdaterLaunchError,
    UpdaterNotPackagedError,
    UpdaterProcessLaunchError,
    UpdaterStagingError,
    packaged_updater_available,
    prepare_and_launch_updater,
)


@dataclass(frozen=True, slots=True)
class UpdateInstallFailure:
    kind: str
    message: str


def _safe_install_failure(exc: Exception) -> UpdateInstallFailure:
    if isinstance(exc, UpdaterNotPackagedError):
        return UpdateInstallFailure(
            kind="unavailable",
            message=(
                "The standalone ChitLog updater is not available in this "
                "build. ChitLog was not closed."
            ),
        )

    if isinstance(exc, UpdateHandoffSecurityError):
        return UpdateInstallFailure(
            kind="verification",
            message=(
                "The update could not be handed to the installer because its "
                "signed release evidence did not verify again. Nothing was "
                "started."
            ),
        )

    if isinstance(exc, (UpdateHandoffPathError, UpdaterStagingError)):
        return UpdateInstallFailure(
            kind="storage",
            message=(
                "ChitLog could not safely prepare the standalone updater in "
                "the local update cache. ChitLog was not closed."
            ),
        )

    if isinstance(exc, (UpdaterProcessLaunchError, UpdaterLaunchError)):
        return UpdateInstallFailure(
            kind="launch",
            message=(
                "Windows could not start the standalone ChitLog updater. "
                "ChitLog was not closed."
            ),
        )

    if isinstance(exc, UpdateHandoffError):
        return UpdateInstallFailure(
            kind="verification",
            message=(
                "The update handoff could not be validated safely. Nothing "
                "was started."
            ),
        )

    return UpdateInstallFailure(
        kind="internal",
        message=(
            "The update could not be handed to the standalone updater safely. "
            "ChitLog was not closed."
        ),
    )


class _UpdateInstallThread(QThread):
    succeeded = Signal(object)
    failed = Signal(object)

    def __init__(
        self,
        outcome: UpdateCheckOutcome,
        artifact: VerifiedInstallerArtifact,
        application_path: Path,
        destination_directory: Path,
        coordinator,
        parent_pid: int,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._outcome = outcome
        self._artifact = artifact
        self._application_path = application_path
        self._destination_directory = destination_directory
        self._coordinator = coordinator
        self._parent_pid = parent_pid

    def run(self) -> None:
        manifest = self._outcome.manifest
        if manifest is None:
            self.failed.emit(
                UpdateInstallFailure(
                    kind="verification",
                    message=(
                        "The verified signed manifest is no longer available. "
                        "Run Check for Updates again."
                    ),
                )
            )
            return

        try:
            result = self._coordinator(
                manifest,
                self._artifact,
                self._application_path,
                self._destination_directory,
                parent_pid=self._parent_pid,
            )
        except Exception as exc:
            self.failed.emit(_safe_install_failure(exc))
        else:
            self.succeeded.emit(result)


class UpdateInstallRunner(QObject):
    """Own at most one updater-handoff worker thread."""

    succeeded = Signal(object)
    failed = Signal(object)
    finished = Signal()

    def __init__(
        self,
        destination_directory: str | Path,
        application_path: str | Path,
        parent: QObject | None = None,
        *,
        coordinator=prepare_and_launch_updater,
        parent_pid: int | None = None,
    ) -> None:
        super().__init__(parent)
        self._destination_directory = Path(destination_directory)
        self._application_path = Path(application_path)
        self._coordinator = coordinator
        self._parent_pid = os.getpid() if parent_pid is None else parent_pid
        self._thread: _UpdateInstallThread | None = None

        application = QCoreApplication.instance()
        if application is not None:
            application.aboutToQuit.connect(self.wait_for_finish)

    @property
    def running(self) -> bool:
        return self._thread is not None

    @property
    def available(self) -> bool:
        return packaged_updater_available(self._application_path)

    @property
    def application_path(self) -> Path:
        return self._application_path

    @property
    def destination_directory(self) -> Path:
        return self._destination_directory

    def start(
        self,
        outcome: UpdateCheckOutcome,
        artifact: VerifiedInstallerArtifact,
    ) -> bool:
        if not isinstance(outcome, UpdateCheckOutcome):
            raise TypeError("outcome must be an UpdateCheckOutcome.")
        if outcome.manifest is None:
            raise ValueError(
                "A verified signed manifest is required for installation."
            )
        if not outcome.update_available:
            raise ValueError("Cannot install an up-to-date decision.")
        if not isinstance(artifact, VerifiedInstallerArtifact):
            raise TypeError("artifact must be a VerifiedInstallerArtifact.")
        if artifact.version != outcome.decision.available_version:
            raise ValueError(
                "Verified installer version does not match the update result."
            )
        if self.running:
            return False

        thread = _UpdateInstallThread(
            outcome,
            artifact,
            self._application_path,
            self._destination_directory,
            self._coordinator,
            self._parent_pid,
            parent=self,
        )
        thread.succeeded.connect(self.succeeded.emit)
        thread.failed.connect(self.failed.emit)
        thread.finished.connect(self._thread_finished)

        self._thread = thread
        thread.start()
        return True

    @Slot()
    def _thread_finished(self) -> None:
        thread = self._thread
        self._thread = None
        if thread is not None:
            thread.deleteLater()
        self.finished.emit()

    @Slot()
    def wait_for_finish(self) -> None:
        thread = self._thread
        if thread is not None and thread.isRunning():
            thread.wait()
