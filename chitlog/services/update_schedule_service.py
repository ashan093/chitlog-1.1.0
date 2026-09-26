"""Offline scheduling rules for ChitLog automatic update checks.

The service decides whether a check is due and records when a real check
attempt starts. It does not create timers, perform network access, or touch UI.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from chitlog.data.update_schedule_repository import (
    StoredUpdateScheduleState,
    UpdateScheduleStateRepository,
)
from chitlog.services.update_preferences_service import (
    UpdatePreferencesService,
)


@dataclass(frozen=True, slots=True)
class UpdateScheduleSnapshot:
    auto_check_enabled: bool
    channel: str
    check_interval_seconds: int
    last_check_attempt_at_utc: datetime | None
    due: bool
    next_check_at_utc: datetime | None


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _normalize_now(value: datetime | None) -> datetime:
    if value is None:
        return _utc_now()
    if not isinstance(value, datetime):
        raise TypeError("now_utc must be a datetime or None.")
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("now_utc must be timezone-aware.")
    return value.astimezone(timezone.utc)


class UpdateScheduleService:
    """Calculate and persist the automatic-check cadence."""

    def __init__(
        self,
        preferences: UpdatePreferencesService,
        repository: UpdateScheduleStateRepository,
    ) -> None:
        self.preferences = preferences
        self.repository = repository

    def snapshot(
        self,
        *,
        now_utc: datetime | None = None,
    ) -> UpdateScheduleSnapshot:
        now = _normalize_now(now_utc)
        preferences = self.preferences.snapshot()
        state = self.repository.load()
        last_attempt = state.last_check_attempt_at_utc

        if not preferences.auto_check_enabled:
            return UpdateScheduleSnapshot(
                auto_check_enabled=False,
                channel=preferences.channel,
                check_interval_seconds=(
                    preferences.check_interval_seconds
                ),
                last_check_attempt_at_utc=last_attempt,
                due=False,
                next_check_at_utc=None,
            )

        if last_attempt is None:
            return UpdateScheduleSnapshot(
                auto_check_enabled=True,
                channel=preferences.channel,
                check_interval_seconds=(
                    preferences.check_interval_seconds
                ),
                last_check_attempt_at_utc=None,
                due=True,
                next_check_at_utc=now,
            )

        next_check = last_attempt + timedelta(
            seconds=preferences.check_interval_seconds
        )
        return UpdateScheduleSnapshot(
            auto_check_enabled=True,
            channel=preferences.channel,
            check_interval_seconds=preferences.check_interval_seconds,
            last_check_attempt_at_utc=last_attempt,
            due=now >= next_check,
            next_check_at_utc=next_check,
        )

    def record_check_attempt(
        self,
        *,
        now_utc: datetime | None = None,
    ) -> UpdateScheduleSnapshot:
        """Persist the start of a real update check, even if it later fails.

        Recording the attempt rather than only a successful result prevents
        repeated network retries every time ChitLog is opened during an outage.
        """

        now = _normalize_now(now_utc).replace(microsecond=0)
        self.repository.save(
            StoredUpdateScheduleState(
                last_check_attempt_at_utc=now
            )
        )
        return self.snapshot(now_utc=now)
