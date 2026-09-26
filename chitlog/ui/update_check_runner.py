"""Qt-threaded runner for one secure ChitLog update check.

The dedicated QThread subclass executes the existing secure core update-check
pipeline away from the GUI thread. It never touches widgets, the database, or
financial records.
"""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from PySide6.QtCore import (
    QCoreApplication,
    QObject,
    QThread,
    Signal,
    Slot,
)

from chitlog.core.update_checker import (
    UpdateCheckError,
    UpdateCheckOutcome,
    check_for_updates,
)
from chitlog.core.update_config import (
    DEFAULT_MANIFEST_URL,
    DEFAULT_MAX_INSTALLER_BYTES,
    DEFAULT_MAX_MANIFEST_BYTES,
    DEFAULT_REQUEST_TIMEOUT_SECONDS,
    UpdatePolicy,
)


UpdateChecker = Callable[[UpdatePolicy], UpdateCheckOutcome]
RealCheckStartedHook = Callable[[UpdatePolicy], None]


@dataclass(frozen=True, slots=True)
class UpdateCheckFailure:
    """Safe failure information returned to the GUI thread."""

    kind: str
    message: str


def policy_from_preferences(preferences) -> UpdatePolicy:
    """Build immutable runtime policy from persisted user preferences."""

    return UpdatePolicy(
        manifest_url=DEFAULT_MANIFEST_URL,
        channel=str(preferences.channel),
        check_interval_seconds=int(
            preferences.check_interval_seconds
        ),
        request_timeout_seconds=DEFAULT_REQUEST_TIMEOUT_SECONDS,
        max_manifest_bytes=DEFAULT_MAX_MANIFEST_BYTES,
        max_installer_bytes=DEFAULT_MAX_INSTALLER_BYTES,
    )


class _UpdateCheckThread(QThread):
    """One short-lived worker thread for one immutable update policy."""

    succeeded = Signal(object)
    failed = Signal(object)

    def __init__(
        self,
        policy: UpdatePolicy,
        checker: UpdateChecker,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._policy = policy
        self._checker = checker

    def run(self) -> None:
        """Execute the core checker entirely on this worker thread."""

        try:
            outcome = self._checker(self._policy)
        except UpdateCheckError as exc:
            self.failed.emit(
                UpdateCheckFailure(
                    kind=exc.kind.value,
                    message=str(exc),
                )
            )
        except Exception:
            # Do not expose internal exception details to Settings.
            self.failed.emit(
                UpdateCheckFailure(
                    kind="internal",
                    message="The update check could not be completed.",
                )
            )
        else:
            self.succeeded.emit(outcome)


class UpdateCheckRunner(QObject):
    """Own at most one background update-check thread."""

    succeeded = Signal(object)
    failed = Signal(object)
    finished = Signal()

    def __init__(
        self,
        parent: QObject | None = None,
        *,
        checker: UpdateChecker = check_for_updates,
        on_real_check_start: RealCheckStartedHook | None = None,
    ) -> None:
        super().__init__(parent)
        self._checker = checker
        self._on_real_check_start = on_real_check_start
        self._thread: _UpdateCheckThread | None = None

        application = QCoreApplication.instance()
        if application is not None:
            application.aboutToQuit.connect(self.wait_for_finish)

    @property
    def running(self) -> bool:
        return self._thread is not None

    def start(self, policy: UpdatePolicy) -> bool:
        """Start one check, or return False while another is still active."""

        if not isinstance(policy, UpdatePolicy):
            raise TypeError("policy must be an UpdatePolicy.")
        if self.running:
            return False

        thread = _UpdateCheckThread(
            policy,
            self._checker,
            parent=self,
        )
        thread.succeeded.connect(self.succeeded.emit)
        thread.failed.connect(self.failed.emit)
        thread.finished.connect(self._thread_finished)

        self._thread = thread
        thread.start()

        if (
            policy.manifest_url is not None
            and self._on_real_check_start is not None
        ):
            try:
                self._on_real_check_start(policy)
            except Exception:
                # Scheduling metadata must never break an otherwise valid
                # manual or automatic update check.
                pass

        return True

    @Slot()
    def _thread_finished(self) -> None:
        """Release a worker only after QThread confirms it has stopped."""

        thread = self._thread
        self._thread = None

        if thread is not None:
            thread.deleteLater()

        self.finished.emit()

    @Slot()
    def wait_for_finish(self) -> None:
        """Never destroy a running QThread during application shutdown."""

        thread = self._thread
        if thread is not None and thread.isRunning():
            # The network layer already has its own request timeout. Waiting
            # here is safer than terminating a QThread that may be inside TLS.
            thread.wait()
