"""Encrypted local persistence for Step 17 notification preferences."""
from __future__ import annotations

from dataclasses import dataclass

from chitlog.data.database import Database


DEFAULT_REMINDER_TIME = "20:00"


@dataclass(frozen=True)
class StoredNotificationSettings:
    enabled: bool
    reminder_time: str
    background_enabled: bool
    last_sent_date: str | None


class NotificationRepository:
    """Store reminder settings inside the existing encrypted application_settings table."""

    ENABLED_KEY = "notification_daily_enabled"
    TIME_KEY = "notification_daily_time"
    BACKGROUND_KEY = "notification_closed_app_enabled"
    LAST_SENT_KEY = "notification_daily_last_sent_date"

    def __init__(self, database: Database):
        self.database = database

    def _get(self, key: str) -> str | None:
        row = self.database.connection.execute(
            "SELECT value FROM application_settings WHERE key=?",
            (key,),
        ).fetchone()
        return str(row[0]) if row else None

    def load(self) -> StoredNotificationSettings:
        enabled_raw = (self._get(self.ENABLED_KEY) or "false").strip().lower()
        reminder_time = (self._get(self.TIME_KEY) or DEFAULT_REMINDER_TIME).strip()
        background_raw = (self._get(self.BACKGROUND_KEY) or "false").strip().lower()
        last_sent = self._get(self.LAST_SENT_KEY)
        return StoredNotificationSettings(
            enabled=enabled_raw == "true",
            reminder_time=reminder_time,
            background_enabled=background_raw == "true",
            last_sent_date=last_sent or None,
        )

    def save_preferences(
        self,
        *,
        enabled: bool,
        reminder_time: str,
        background_enabled: bool = False,
    ) -> None:
        values = (
            (self.ENABLED_KEY, "true" if enabled else "false"),
            (self.TIME_KEY, reminder_time),
            (
                self.BACKGROUND_KEY,
                "true" if enabled and background_enabled else "false",
            ),
        )
        with self.database.transaction() as connection:
            connection.executemany(
                "INSERT INTO application_settings(key,value) VALUES (?,?) "
                "ON CONFLICT(key) DO UPDATE SET "
                "value=excluded.value,updated_at=CURRENT_TIMESTAMP",
                values,
            )

    def mark_sent(self, sent_date: str) -> None:
        with self.database.transaction() as connection:
            connection.execute(
                "INSERT INTO application_settings(key,value) VALUES (?,?) "
                "ON CONFLICT(key) DO UPDATE SET "
                "value=excluded.value,updated_at=CURRENT_TIMESTAMP",
                (self.LAST_SENT_KEY, sent_date),
            )

    def clear_last_sent(self) -> None:
        """Allow a newly changed/enabled schedule to run again today."""
        with self.database.transaction() as connection:
            connection.execute(
                "DELETE FROM application_settings WHERE key=?",
                (self.LAST_SENT_KEY,),
            )
