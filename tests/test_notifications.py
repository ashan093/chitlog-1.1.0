"""Step 17 reminder persistence and scheduling tests."""
from datetime import datetime
import secrets

import pytest

from chitlog.data.database import Database
from chitlog.data.notification_repository import NotificationRepository
from chitlog.services.notification_service import NotificationError, NotificationService


def test_notification_defaults_and_persistence(tmp_path):
    db = Database(
        tmp_path / "test.db",
        secrets.token_bytes(32),
        tmp_path / "snapshots",
    ).open()
    try:
        service = NotificationService(NotificationRepository(db))
        defaults = service.settings()
        assert defaults.enabled is False
        assert defaults.reminder_time == "20:00"
        assert defaults.last_sent_date is None

        saved = service.save_settings(enabled=True, reminder_time="19:35")
        assert saved.enabled is True
        assert saved.reminder_time == "19:35"

        reopened = NotificationService(NotificationRepository(db)).settings()
        assert reopened.enabled is True
        assert reopened.reminder_time == "19:35"
    finally:
        db.close()


def test_daily_reminder_due_once_per_day_and_after_startup(tmp_path):
    db = Database(
        tmp_path / "test.db",
        secrets.token_bytes(32),
        tmp_path / "snapshots",
    ).open()
    try:
        service = NotificationService(NotificationRepository(db))
        service.save_settings(enabled=True, reminder_time="19:30")

        before = datetime(2026, 9, 17, 19, 29, 59)
        at_time = datetime(2026, 9, 17, 19, 30, 0)
        later = datetime(2026, 9, 17, 22, 0, 0)
        tomorrow = datetime(2026, 9, 18, 19, 30, 0)

        assert service.is_due(before) is False
        assert service.is_due(at_time) is True
        # Starting ChitLog after the configured time should still make today's
        # not-yet-delivered reminder immediately due.
        assert service.next_delay_ms(later) == 250

        service.mark_sent(at_time)
        assert service.is_due(later) is False
        assert service.is_due(tomorrow) is True
    finally:
        db.close()


def test_disabled_and_invalid_reminder_settings(tmp_path):
    db = Database(
        tmp_path / "test.db",
        secrets.token_bytes(32),
        tmp_path / "snapshots",
    ).open()
    try:
        service = NotificationService(NotificationRepository(db))
        service.save_settings(enabled=False, reminder_time="08:15")
        assert service.is_due(datetime(2026, 9, 17, 23, 0)) is False
        assert service.next_delay_ms(datetime(2026, 9, 17, 23, 0)) is None

        for invalid in ("", "7:30", "24:00", "12:60", "abc"):
            with pytest.raises(NotificationError):
                service.save_settings(enabled=True, reminder_time=invalid)
    finally:
        db.close()


def test_changing_time_after_today_was_sent_rearms_today(tmp_path):
    db = Database(
        tmp_path / "test.db",
        secrets.token_bytes(32),
        tmp_path / "snapshots",
    ).open()
    try:
        service = NotificationService(NotificationRepository(db))
        service.save_settings(enabled=True, reminder_time="19:01")
        fired = datetime(2026, 9, 17, 19, 1, 0)
        service.mark_sent(fired)
        assert service.is_due(datetime(2026, 9, 17, 19, 1, 30)) is False

        # Rescheduling to a later time on the same day must clear the old
        # sent marker so the newly selected schedule can fire.
        service.save_settings(enabled=True, reminder_time="19:02")
        settings = service.settings()
        assert settings.last_sent_date is None
        assert service.is_due(datetime(2026, 9, 17, 19, 1, 59)) is False
        assert service.is_due(datetime(2026, 9, 17, 19, 2, 0)) is True
    finally:
        db.close()


def test_enabling_again_rearms_current_day(tmp_path):
    db = Database(
        tmp_path / "test.db",
        secrets.token_bytes(32),
        tmp_path / "snapshots",
    ).open()
    try:
        service = NotificationService(NotificationRepository(db))
        service.save_settings(enabled=True, reminder_time="08:00")
        service.mark_sent(datetime(2026, 9, 17, 8, 0))
        service.save_settings(enabled=False, reminder_time="08:00")
        service.save_settings(enabled=True, reminder_time="08:00")
        assert service.settings().last_sent_date is None
    finally:
        db.close()
