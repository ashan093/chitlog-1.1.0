"""Step 17 notification wording and identity regression checks."""
from pathlib import Path

from chitlog.services.notification_service import NotificationService


def test_daily_message_tells_user_to_enter_records():
    assert NotificationService.TITLE == "ChitLog Reminder"
    assert NotificationService.MESSAGE == (
        "It's time to open ChitLog and enter today's records."
    )


def test_test_notification_uses_real_reminder_message():
    project = Path(__file__).resolve().parents[1]
    source = (project / "chitlog/ui/notification_controller.py").read_text(
        encoding="utf-8"
    )
    assert "self.service.TITLE" in source
    assert "self.service.MESSAGE" in source
    assert "Desktop reminders are ready. No financial data is included." not in source


def test_windows_identity_uses_chitlog_name():
    project = Path(__file__).resolve().parents[1]
    source = (project / "chitlog/application.py").read_text(encoding="utf-8")
    assert "SetCurrentProcessExplicitAppUserModelID" in source
    assert '"ChitLog"' in source
    assert "ChitLog.Desktop" not in source
