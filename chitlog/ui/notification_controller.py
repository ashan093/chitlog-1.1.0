"""Qt bridge that delivers local ChitLog reminders through the system tray."""
from __future__ import annotations

from PySide6.QtCore import QObject, QTimer, Signal
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QSystemTrayIcon

from chitlog.services.notification_service import NotificationService


class DesktopNotificationController(QObject):
    """Schedule and display a generic privacy-safe desktop reminder."""

    message = Signal(str)

    def __init__(
        self,
        service: NotificationService,
        icon: QIcon | None = None,
        parent=None,
    ):
        super().__init__(parent)
        self.service = service
        self.icon = icon or QIcon()
        self.timer = QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.timeout.connect(self._timer_fired)
        self.tray: QSystemTrayIcon | None = None

    def _ensure_tray(self) -> bool:
        if not QSystemTrayIcon.isSystemTrayAvailable():
            return False
        if self.tray is None:
            self.tray = QSystemTrayIcon(self.icon, self)
            self.tray.setToolTip("ChitLog")
        if not self.tray.isVisible():
            self.tray.show()
        return True

    def _hide_tray_if_disabled(self) -> None:
        if not self.service.settings().enabled and self.tray is not None:
            self.tray.hide()

    def start(self) -> None:
        self.reschedule()

    def stop(self) -> None:
        self.timer.stop()
        if self.tray is not None:
            self.tray.hide()

    def reschedule(self) -> None:
        self.timer.stop()
        settings = self.service.settings()
        if not settings.enabled:
            self._hide_tray_if_disabled()
            return
        if settings.background_enabled:
            # Windows Task Scheduler owns the actual daily trigger in this mode.
            # Do not arm a second in-process timer or the user could get duplicates.
            if self.tray is not None:
                self.tray.hide()
            return

        self._ensure_tray()
        delay = self.service.next_delay_ms()
        if delay is not None:
            self.timer.start(delay)

    def _show_message(self, title: str, message: str, *, test: bool = False) -> bool:
        if self._ensure_tray():
            self.tray.showMessage(
                title,
                message,
                QSystemTrayIcon.MessageIcon.Information,
                7000,
            )
            if test and not self.service.settings().enabled:
                QTimer.singleShot(8000, self._hide_tray_if_disabled)
            return True

        # Unsupported/headless environments still receive an in-app message.
        self.message.emit(message)
        return False

    def _timer_fired(self) -> None:
        if self.service.is_due():
            shown_as_desktop = self._show_message(
                self.service.TITLE,
                self.service.MESSAGE,
            )
            # When a system tray is unavailable, the in-app fallback still
            # counts as today's local reminder while ChitLog is running.
            self.service.mark_sent()
            self.message.emit(
                "Daily reminder delivered."
                if shown_as_desktop
                else "Daily reminder shown inside ChitLog."
            )
        self.reschedule()

    def show_test(self) -> None:
        # A test notification previews the same wording the user will receive
        # at the scheduled time.
        shown = self._show_message(
            self.service.TITLE,
            self.service.MESSAGE,
            test=True,
        )
        self.message.emit(
            "Test desktop reminder sent."
            if shown
            else "Desktop notifications are unavailable here; the test was shown inside ChitLog."
        )
