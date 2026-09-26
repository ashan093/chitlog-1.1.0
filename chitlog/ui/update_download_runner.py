"""Qt-threaded secure installer download runner for ChitLog.

The worker invokes only the restricted installer transport and Step 6A staging
pipeline. It never touches widgets, financial data, or installer execution.
"""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from PySide6.QtCore import (
    QCoreApplication,
    QObject,
    QThread,
    Signal,
    Slot,
)

from chitlog.core.update_config import DEFAULT_UPDATE_POLICY, UpdatePolicy
from chitlog.core.update_decision import UpdateDecision
from chitlog.core.update_installer_staging import (
    InstallerHashError,
    InstallerSizeError,
    InstallerStagingError,
    InstallerStreamError,
    VerifiedInstallerArtifact,
)
from chitlog.core.update_transport import (
    InstallerDownloadError,
    InstallerHTTPStatusError,
    InstallerResponseError,
    download_installer_to_staging,
)


InstallerDownloader = Callable[
    [object, str | Path, UpdatePolicy],
    VerifiedInstallerArtifact,
]


@dataclass(frozen=True, slots=True)
class UpdateDownloadFailure:
    """Safe user-facing failure information returned to the GUI thread."""

    kind: str
    message: str


def _safe_download_failure(exc: Exception) -> UpdateDownloadFailure:
    if isinstance(exc, (InstallerHTTPStatusError, InstallerResponseError)):
        return UpdateDownloadFailure(
            kind="security",
            message=(
                "The installer download was rejected because the server "
                "response did not meet ChitLog's update safety requirements."
            ),
        )

    if isinstance(
        exc,
        (
            InstallerHashError,
            InstallerSizeError,
            InstallerStreamError,
        ),
    ):
        return UpdateDownloadFailure(
            kind="verification",
            message=(
                "The downloaded installer failed verification and was "
                "discarded. ChitLog was not changed."
            ),
        )

    if isinstance(exc, InstallerStagingError):
        return UpdateDownloadFailure(
            kind="storage",
            message=(
                "ChitLog could not safely store the verified installer. "
                "Check available disk space and try again."
            ),
        )

    if isinstance(exc, InstallerDownloadError):
        return UpdateDownloadFailure(
            kind="network",
            message=(
                "The installer download could not be completed. "
                "Check your connection and try again."
            ),
        )

    return UpdateDownloadFailure(
        kind="internal",
        message=(
            "The installer download could not be completed safely. "
            "ChitLog was not changed."
        ),
    )


class _UpdateDownloadThread(QThread):
    """One short-lived worker thread for one verified update decision."""

    succeeded = Signal(object)
    failed = Signal(object)

    def __init__(
        self,
        decision: UpdateDecision,
        destination_directory: Path,
        policy: UpdatePolicy,
        downloader,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._decision = decision
        self._destination_directory = destination_directory
        self._policy = policy
        self._downloader = downloader

    def run(self) -> None:
        try:
            artifact = self._downloader(
                self._decision.payload,
                self._destination_directory,
                self._policy,
            )
        except Exception as exc:
            self.failed.emit(_safe_download_failure(exc))
        else:
            self.succeeded.emit(artifact)


class UpdateDownloadRunner(QObject):
    """Own at most one secure installer-download worker thread."""

    succeeded = Signal(object)
    failed = Signal(object)
    finished = Signal()

    def __init__(
        self,
        destination_directory: str | Path,
        parent: QObject | None = None,
        *,
        policy: UpdatePolicy = DEFAULT_UPDATE_POLICY,
        downloader=download_installer_to_staging,
    ) -> None:
        super().__init__(parent)

        if not isinstance(policy, UpdatePolicy):
            raise TypeError("policy must be an UpdatePolicy.")

        self._destination_directory = Path(destination_directory)
        self._policy = policy
        self._downloader = downloader
        self._thread: _UpdateDownloadThread | None = None

        application = QCoreApplication.instance()
        if application is not None:
            application.aboutToQuit.connect(self.wait_for_finish)

    @property
    def running(self) -> bool:
        return self._thread is not None

    @property
    def destination_directory(self) -> Path:
        return self._destination_directory

    def start(self, decision: UpdateDecision) -> bool:
        """Start one verified update download, or False if one is active."""

        if not isinstance(decision, UpdateDecision):
            raise TypeError("decision must be an UpdateDecision.")
        if not decision.update_available:
            raise ValueError("Cannot download an up-to-date decision.")
        if self.running:
            return False

        thread = _UpdateDownloadThread(
            decision,
            self._destination_directory,
            self._policy,
            self._downloader,
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
        """Do not destroy a worker while it may still be inside TLS/file I/O."""

        thread = self._thread
        if thread is not None and thread.isRunning():
            thread.wait()
