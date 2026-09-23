"""One-shot notification entry used by Windows Task Scheduler."""
from __future__ import annotations

from PySide6.QtCore import QTimer
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication, QSystemTrayIcon


def run_background_notification(
    app: QApplication,
    service,
    icon_path=None,
) -> int:
    settings = service.settings()
    if not (
        settings.enabled
        and settings.background_enabled
        and service.is_due()
    ):
        return 0

    if not QSystemTrayIcon.isSystemTrayAvailable():
        return 0

    tray = QSystemTrayIcon(
        QIcon(str(icon_path)) if icon_path else QIcon(),
        app,
    )
    tray.setToolTip("ChitLog")
    tray.show()

    # Mark before displaying so opening ChitLog immediately afterwards cannot
    # trigger the same daily reminder a second time.
    service.mark_sent()

    def show_and_wait():
        tray.showMessage(
            service.TITLE,
            service.MESSAGE,
            QSystemTrayIcon.MessageIcon.Information,
            7000,
        )

    QTimer.singleShot(150, show_and_wait)
    QTimer.singleShot(8000, app.quit)
    return app.exec()
