"""Persistence for ChitLog automatic-update preferences.

Updater preferences are ordinary non-sensitive application settings stored
inside ChitLog's encrypted database. No network access belongs here.
"""
from __future__ import annotations

from dataclasses import dataclass

from chitlog.core.update_config import (
    ALLOWED_UPDATE_CHANNELS,
    DEFAULT_CHECK_INTERVAL_SECONDS,
)
from chitlog.core.version import APP_UPDATE_CHANNEL


AUTO_CHECK_KEY = "update_auto_check_enabled"
AUTO_INSTALL_KEY = "update_auto_install_enabled"
CHANNEL_KEY = "update_channel"
CHECK_INTERVAL_KEY = "update_check_interval_seconds"

DEFAULT_AUTO_CHECK_ENABLED = True
DEFAULT_AUTO_INSTALL_ENABLED = False


class UpdatePreferencesStorageError(RuntimeError):
    """Stored update preferences are malformed or inconsistent."""


@dataclass(frozen=True, slots=True)
class StoredUpdatePreferences:
    auto_check_enabled: bool = DEFAULT_AUTO_CHECK_ENABLED
    auto_install_enabled: bool = DEFAULT_AUTO_INSTALL_ENABLED
    channel: str = APP_UPDATE_CHANNEL
    check_interval_seconds: int = DEFAULT_CHECK_INTERVAL_SECONDS


def _parse_bool(key: str, raw: str | None, default: bool) -> bool:
    if raw is None:
        return default
    if raw == "1":
        return True
    if raw == "0":
        return False
    raise UpdatePreferencesStorageError(
        f"Stored update preference {key!r} is invalid."
    )


def _parse_interval(raw: str | None) -> int:
    if raw is None:
        return DEFAULT_CHECK_INTERVAL_SECONDS
    try:
        value = int(raw)
    except (TypeError, ValueError) as exc:
        raise UpdatePreferencesStorageError(
            "Stored update check interval is invalid."
        ) from exc
    if value <= 0:
        raise UpdatePreferencesStorageError(
            "Stored update check interval must be positive."
        )
    return value


class UpdatePreferencesRepository:
    """Read/write update preferences in application_settings."""

    def __init__(self, database):
        self.database = database

    def load(self) -> StoredUpdatePreferences:
        keys = (
            AUTO_CHECK_KEY,
            AUTO_INSTALL_KEY,
            CHANNEL_KEY,
            CHECK_INTERVAL_KEY,
        )
        placeholders = ",".join("?" for _ in keys)
        rows = self.database.connection.execute(
            f"SELECT key,value FROM application_settings "
            f"WHERE key IN ({placeholders})",
            keys,
        ).fetchall()
        values = {str(key): str(value) for key, value in rows}

        channel = values.get(CHANNEL_KEY, APP_UPDATE_CHANNEL)
        if channel not in ALLOWED_UPDATE_CHANNELS:
            raise UpdatePreferencesStorageError(
                "Stored update channel is invalid."
            )

        return StoredUpdatePreferences(
            auto_check_enabled=_parse_bool(
                AUTO_CHECK_KEY,
                values.get(AUTO_CHECK_KEY),
                DEFAULT_AUTO_CHECK_ENABLED,
            ),
            auto_install_enabled=_parse_bool(
                AUTO_INSTALL_KEY,
                values.get(AUTO_INSTALL_KEY),
                DEFAULT_AUTO_INSTALL_ENABLED,
            ),
            channel=channel,
            check_interval_seconds=_parse_interval(
                values.get(CHECK_INTERVAL_KEY)
            ),
        )

    def save(self, preferences: StoredUpdatePreferences) -> None:
        if not isinstance(preferences, StoredUpdatePreferences):
            raise TypeError(
                "preferences must be a StoredUpdatePreferences instance."
            )

        rows = (
            (
                AUTO_CHECK_KEY,
                "1" if preferences.auto_check_enabled else "0",
            ),
            (
                AUTO_INSTALL_KEY,
                "1" if preferences.auto_install_enabled else "0",
            ),
            (CHANNEL_KEY, preferences.channel),
            (
                CHECK_INTERVAL_KEY,
                str(preferences.check_interval_seconds),
            ),
        )

        with self.database.transaction() as connection:
            connection.executemany(
                "INSERT INTO application_settings(key,value) VALUES (?,?) "
                "ON CONFLICT(key) DO UPDATE SET "
                "value=excluded.value,updated_at=CURRENT_TIMESTAMP",
                rows,
            )
