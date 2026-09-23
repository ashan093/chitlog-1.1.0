"""Step 17 closed-app reminder settings and scheduler behavior."""
import secrets
from types import SimpleNamespace

from chitlog.data.database import Database
from chitlog.data.notification_repository import NotificationRepository
from chitlog.services.notification_service import NotificationService


class FakeScheduler:
    supported = True

    def __init__(self):
        self.enabled_times = []
        self.disabled = 0

    def enable(self, reminder_time):
        self.enabled_times.append(reminder_time)

    def disable(self):
        self.disabled += 1


def test_closed_app_setting_defaults_off_and_persists(tmp_path):
    db = Database(
        tmp_path / "test.db", secrets.token_bytes(32), tmp_path / "snapshots"
    ).open()
    try:
        scheduler = FakeScheduler()
        service = NotificationService(NotificationRepository(db), scheduler)
        assert service.settings().background_enabled is False

        saved = service.save_settings(
            enabled=True,
            reminder_time="20:30",
            background_enabled=True,
        )
        assert saved.background_enabled is True
        assert scheduler.enabled_times == ["20:30"]

        reopened = NotificationService(NotificationRepository(db), scheduler)
        assert reopened.settings().background_enabled is True

        reopened.save_settings(
            enabled=True,
            reminder_time="20:30",
            background_enabled=False,
        )
        assert reopened.settings().background_enabled is False
        assert scheduler.disabled >= 1
    finally:
        db.close()


def test_background_mode_does_not_arm_in_process_delay(tmp_path):
    db = Database(
        tmp_path / "test.db", secrets.token_bytes(32), tmp_path / "snapshots"
    ).open()
    try:
        scheduler = FakeScheduler()
        service = NotificationService(NotificationRepository(db), scheduler)
        service.save_settings(
            enabled=True,
            reminder_time="20:30",
            background_enabled=True,
        )
        assert service.next_delay_ms() is None
    finally:
        db.close()
