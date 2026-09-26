"""Persistence for ChitLog update-check scheduling state.

This module stores only updater timing metadata in the existing encrypted
application_settings table. It performs no networking and has no UI imports.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone


LAST_CHECK_ATTEMPT_KEY = "update_last_check_attempt_utc"
_UTC_TIMESTAMP_FORMAT = "%Y-%m-%dT%H:%M:%SZ"


class UpdateScheduleStorageError(RuntimeError):
    """Stored updater schedule state is malformed."""


@dataclass(frozen=True, slots=True)
class StoredUpdateScheduleState:
    last_check_attempt_at_utc: datetime | None = None


def _format_utc_timestamp(value: datetime) -> str:
    if not isinstance(value, datetime):
        raise TypeError("Update check timestamp must be a datetime.")
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("Update check timestamp must be timezone-aware.")

    normalized = value.astimezone(timezone.utc).replace(microsecond=0)
    return normalized.strftime(_UTC_TIMESTAMP_FORMAT)


def _parse_utc_timestamp(raw: str | None) -> datetime | None:
    if raw is None or raw == "":
        return None
    if not isinstance(raw, str):
        raise UpdateScheduleStorageError(
            "Stored update check timestamp is invalid."
        )

    try:
        parsed = datetime.strptime(
            raw,
            _UTC_TIMESTAMP_FORMAT,
        ).replace(tzinfo=timezone.utc)
    except ValueError as exc:
        raise UpdateScheduleStorageError(
            "Stored update check timestamp is invalid."
        ) from exc

    if parsed.strftime(_UTC_TIMESTAMP_FORMAT) != raw:
        raise UpdateScheduleStorageError(
            "Stored update check timestamp is invalid."
        )
    return parsed


class UpdateScheduleStateRepository:
    """Read/write the last real update-check attempt timestamp."""

    def __init__(self, database):
        self.database = database

    def load(self) -> StoredUpdateScheduleState:
        row = self.database.connection.execute(
            "SELECT value FROM application_settings WHERE key=?",
            (LAST_CHECK_ATTEMPT_KEY,),
        ).fetchone()

        raw = None if row is None else row[0]
        return StoredUpdateScheduleState(
            last_check_attempt_at_utc=_parse_utc_timestamp(raw)
        )

    def save(self, state: StoredUpdateScheduleState) -> None:
        if not isinstance(state, StoredUpdateScheduleState):
            raise TypeError(
                "state must be a StoredUpdateScheduleState instance."
            )

        value = (
            ""
            if state.last_check_attempt_at_utc is None
            else _format_utc_timestamp(
                state.last_check_attempt_at_utc
            )
        )

        with self.database.transaction() as connection:
            connection.execute(
                "INSERT INTO application_settings(key,value) VALUES (?,?) "
                "ON CONFLICT(key) DO UPDATE SET "
                "value=excluded.value,updated_at=CURRENT_TIMESTAMP",
                (LAST_CHECK_ATTEMPT_KEY, value),
            )
