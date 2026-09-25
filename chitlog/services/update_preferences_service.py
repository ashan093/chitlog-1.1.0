"""Business rules for ChitLog automatic-update preferences.

This service controls preference values only. It never performs an update
check, network request, download, or installer launch.
"""
from __future__ import annotations

from dataclasses import dataclass

from chitlog.core.update_config import (
    ALLOWED_UPDATE_CHANNELS,
    DEFAULT_CHECK_INTERVAL_SECONDS,
)
from chitlog.core.version import APP_UPDATE_CHANNEL
from chitlog.data.update_preferences_repository import (
    DEFAULT_AUTO_CHECK_ENABLED,
    DEFAULT_AUTO_INSTALL_ENABLED,
    StoredUpdatePreferences,
    UpdatePreferencesRepository,
)


class UpdatePreferencesError(ValueError):
    """Safe validation error for update preference changes."""

@dataclass(frozen=True, slots=True)
class UpdatePreferencesSnapshot:
    auto_check_enabled: bool
    auto_install_enabled: bool
    channel: str
    check_interval_seconds: int


class UpdatePreferencesService:
    """Validated preference state, independent from updater networking."""

    def __init__(self, repository: UpdatePreferencesRepository):
        self.repository = repository

    def snapshot(self) -> UpdatePreferencesSnapshot:
        stored = self.repository.load()
        return UpdatePreferencesSnapshot(
            auto_check_enabled=stored.auto_check_enabled,
            auto_install_enabled=stored.auto_install_enabled,
            channel=stored.channel,
            check_interval_seconds=stored.check_interval_seconds,
        )

    def _save(
        self,
        *,
        auto_check_enabled: bool,
        auto_install_enabled: bool,
        channel: str,
        check_interval_seconds: int,
    ) -> UpdatePreferencesSnapshot:
        if channel not in ALLOWED_UPDATE_CHANNELS:
            raise UpdatePreferencesError(
                f"Unsupported update channel: {channel!r}"
            )
        if (
            not isinstance(check_interval_seconds, int)
            or isinstance(check_interval_seconds, bool)
            or check_interval_seconds <= 0
        ):
            raise UpdatePreferencesError(
                "Update check interval must be a positive integer."
            )

        self.repository.save(
            StoredUpdatePreferences(
                auto_check_enabled=bool(auto_check_enabled),
                auto_install_enabled=bool(auto_install_enabled),
                channel=channel,
                check_interval_seconds=check_interval_seconds,
            )
        )
        return self.snapshot()

    def configure(
        self,
        *,
        auto_check_enabled: bool,
        channel: str,
    ) -> UpdatePreferencesSnapshot:
        """Save the user-facing update preferences in one transaction."""

        cleaned = (channel or "").strip().lower()
        current = self.snapshot()
        return self._save(
            auto_check_enabled=bool(auto_check_enabled),
            auto_install_enabled=current.auto_install_enabled,
            channel=cleaned,
            check_interval_seconds=current.check_interval_seconds,
        )

    def set_auto_check_enabled(
        self,
        enabled: bool,
    ) -> UpdatePreferencesSnapshot:
        current = self.snapshot()
        return self._save(
            auto_check_enabled=bool(enabled),
            auto_install_enabled=current.auto_install_enabled,
            channel=current.channel,
            check_interval_seconds=current.check_interval_seconds,
        )

    def set_auto_install_enabled(
        self,
        enabled: bool,
    ) -> UpdatePreferencesSnapshot:
        current = self.snapshot()
        return self._save(
            auto_check_enabled=current.auto_check_enabled,
            auto_install_enabled=bool(enabled),
            channel=current.channel,
            check_interval_seconds=current.check_interval_seconds,
        )

    def set_channel(
        self,
        channel: str,
    ) -> UpdatePreferencesSnapshot:
        cleaned = (channel or "").strip().lower()
        current = self.snapshot()
        return self._save(
            auto_check_enabled=current.auto_check_enabled,
            auto_install_enabled=current.auto_install_enabled,
            channel=cleaned,
            check_interval_seconds=current.check_interval_seconds,
        )

    def set_check_interval_seconds(
        self,
        seconds: int,
    ) -> UpdatePreferencesSnapshot:
        current = self.snapshot()
        return self._save(
            auto_check_enabled=current.auto_check_enabled,
            auto_install_enabled=current.auto_install_enabled,
            channel=current.channel,
            check_interval_seconds=seconds,
        )


DEFAULT_UPDATE_PREFERENCES = UpdatePreferencesSnapshot(
    auto_check_enabled=DEFAULT_AUTO_CHECK_ENABLED,
    auto_install_enabled=DEFAULT_AUTO_INSTALL_ENABLED,
    channel=APP_UPDATE_CHANNEL,
    check_interval_seconds=DEFAULT_CHECK_INTERVAL_SECONDS,
)
