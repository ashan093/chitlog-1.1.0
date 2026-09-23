"""Step 17 closed-app setting appears in Notifications UI."""
from pathlib import Path


def test_notifications_page_has_closed_app_setting():
    project = Path(__file__).resolve().parents[1]
    source = (project / "chitlog/ui/pages/notifications.py").read_text(
        encoding="utf-8"
    )
    assert "Notify even when ChitLog is closed" in source
    assert "background_enabled=self.background_checkbox.isChecked()" in source
    assert "Windows Task Scheduler" in source


def test_application_has_hidden_notification_only_mode():
    project = Path(__file__).resolve().parents[1]
    source = (project / "chitlog/application.py").read_text(encoding="utf-8")
    assert "--notification-only" in source
    assert "run_background_notification" in source
    assert "WindowsReminderTaskScheduler" in source
