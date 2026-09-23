"""Business logic for local daily desktop reminders."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, time, timedelta
import re

from chitlog.data.notification_repository import (
    DEFAULT_REMINDER_TIME,
    NotificationRepository,
)


_TIME_RE = re.compile(r"^(?:[01]\d|2[0-3]):[0-5]\d$")


class NotificationError(ValueError):
    """Safe reminder-settings validation error."""


@dataclass(frozen=True)
class NotificationSettings:
    enabled: bool
    reminder_time: str
    background_enabled: bool
    last_sent_date: str | None


class NotificationService:
    """Local/offline reminder rules independent from the desktop notification API."""

    TITLE = "ChitLog Reminder"
    MESSAGE = "It\'s time to open ChitLog and enter today\'s records."

    def __init__(self, repository: NotificationRepository, scheduler=None):
        self.repository = repository
        self.scheduler = scheduler

    @property
    def background_supported(self) -> bool:
        return bool(self.scheduler is not None and self.scheduler.supported)

    @staticmethod
    def _validate_time(value: str) -> str:
        normalized = (value or "").strip()
        if not _TIME_RE.fullmatch(normalized):
            raise NotificationError("Choose a valid reminder time.")
        return normalized

    @staticmethod
    def _time_from_text(value: str) -> time:
        hour, minute = (int(part) for part in value.split(":"))
        return time(hour=hour, minute=minute)

    def settings(self) -> NotificationSettings:
        stored = self.repository.load()
        reminder_time = stored.reminder_time
        if not _TIME_RE.fullmatch(reminder_time):
            reminder_time = DEFAULT_REMINDER_TIME
        return NotificationSettings(
            enabled=stored.enabled,
            reminder_time=reminder_time,
            background_enabled=stored.background_enabled,
            last_sent_date=stored.last_sent_date,
        )

    def save_settings(
        self,
        *,
        enabled: bool,
        reminder_time: str,
        background_enabled: bool = False,
    ) -> NotificationSettings:
        reminder_time = self._validate_time(reminder_time)
        previous = self.settings()
        enabled = bool(enabled)
        background_enabled = bool(enabled and background_enabled)

        if background_enabled and not self.background_supported:
            raise NotificationError(
                "Closed-app reminders are not available in this environment."
            )

        self.repository.save_preferences(
            enabled=enabled,
            reminder_time=reminder_time,
            background_enabled=background_enabled,
        )

        # "Once per day" applies to one saved schedule. If the user changes the
        # reminder time after today's reminder has already fired, or enables the
        # reminder again, today's old sent marker must not block the new schedule.
        if enabled and (
            reminder_time != previous.reminder_time
            or not previous.enabled
        ):
            self.repository.clear_last_sent()

        try:
            if self.scheduler is not None:
                if background_enabled:
                    self.scheduler.enable(reminder_time)
                else:
                    self.scheduler.disable()
        except Exception as error:
            # Keep normal in-app reminders enabled, but roll back the background
            # option so the saved UI state never claims a Windows task exists.
            self.repository.save_preferences(
                enabled=enabled,
                reminder_time=reminder_time,
                background_enabled=False,
            )
            raise NotificationError(str(error)) from None

        return self.settings()

    def sync_background_task(self) -> None:
        """Reconcile the Windows task with saved settings at application startup."""
        if self.scheduler is None:
            return
        settings = self.settings()
        try:
            if settings.enabled and settings.background_enabled:
                self.scheduler.enable(settings.reminder_time)
            else:
                self.scheduler.disable()
        except Exception as error:
            raise NotificationError(str(error)) from None

    def is_due(self, now: datetime | None = None) -> bool:
        now = now or datetime.now()
        settings = self.settings()
        if not settings.enabled:
            return False
        if settings.last_sent_date == now.date().isoformat():
            return False
        scheduled = datetime.combine(
            now.date(),
            self._time_from_text(settings.reminder_time),
        )
        return now >= scheduled

    def mark_sent(self, now: datetime | None = None) -> None:
        now = now or datetime.now()
        self.repository.mark_sent(now.date().isoformat())

    def next_delay_ms(self, now: datetime | None = None) -> int | None:
        """Milliseconds until the next reminder check.

        If today's configured time has already passed and no reminder has been
        delivered today, return a short delay so the user receives one soon
        after ChitLog starts. Otherwise schedule the next configured local time.
        """
        now = now or datetime.now()
        settings = self.settings()
        if not settings.enabled:
            return None
        if settings.background_enabled:
            return None
        if self.is_due(now):
            return 250

        reminder_time = self._time_from_text(settings.reminder_time)
        target = datetime.combine(now.date(), reminder_time)
        if target <= now or settings.last_sent_date == now.date().isoformat():
            target = datetime.combine(now.date() + timedelta(days=1), reminder_time)

        milliseconds = int(max(1.0, (target - now).total_seconds()) * 1000)
        # QTimer supports large intervals, but daily reminders never need more
        # than just over 24 hours. Keep a defensive upper bound.
        return min(milliseconds, 25 * 60 * 60 * 1000)
