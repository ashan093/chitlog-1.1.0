"""Startup-only automatic update-check scheduling for ChitLog.

This layer decides whether one automatic check should start after the main
window becomes visible. It performs no network access itself and owns no
financial data.
"""
from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import QObject, Signal, Slot

from chitlog.core.update_config import UpdatePolicy
from chitlog.ui.update_check_runner import (
    UpdateCheckRunner,
    policy_from_preferences,
)


PolicyBuilder = Callable[[object], UpdatePolicy]


class StartupUpdateCheckScheduler(QObject):
    """Start at most one due automatic update check for this app launch."""

    check_started = Signal()
    check_skipped = Signal(str)

    def __init__(
        self,
        preferences_service,
        schedule_service,
        runner: UpdateCheckRunner,
        parent: QObject | None = None,
        *,
        policy_builder: PolicyBuilder = policy_from_preferences,
    ) -> None:
        super().__init__(parent)
        self.preferences_service = preferences_service
        self.schedule_service = schedule_service
        self.runner = runner
        self.policy_builder = policy_builder
        self._evaluated = False

    @property
    def evaluated(self) -> bool:
        return self._evaluated

    @Slot()
    def run_if_due(self) -> bool:
        """Evaluate this launch once and start a due real check if possible."""

        if self._evaluated:
            self.check_skipped.emit("already_evaluated")
            return False
        self._evaluated = True

        schedule = self.schedule_service.snapshot()

        if not schedule.auto_check_enabled:
            self.check_skipped.emit("disabled")
            return False

        if not schedule.due:
            self.check_skipped.emit("not_due")
            return False

        if self.runner.running:
            self.check_skipped.emit("busy")
            return False

        preferences = self.preferences_service.snapshot()
        policy = self.policy_builder(preferences)

        # The development build deliberately has no endpoint yet. Do not
        # record a check attempt or create a worker for a disabled transport.
        if policy.manifest_url is None:
            self.check_skipped.emit("unconfigured")
            return False

        if not self.runner.start(policy):
            self.check_skipped.emit("busy")
            return False

        self.check_started.emit()
        return True
