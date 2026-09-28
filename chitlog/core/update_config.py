"""Updater policy/configuration foundation.

No network calls live in this module. Production update endpoints are fixed
application policy; user preferences select a supported channel but never
supply an arbitrary network destination.
"""
from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import urlsplit

from chitlog.core.version import APP_UPDATE_CHANNEL


STABLE_MANIFEST_URL = (
    "https://chitlog-updates.chitlogapp.workers.dev/"
    "api/updates/windows/stable"
)
BETA_MANIFEST_URL: str | None = None

UPDATE_MANIFEST_URLS = {
    "stable": STABLE_MANIFEST_URL,
    "beta": BETA_MANIFEST_URL,
}

DEFAULT_MANIFEST_URL: str | None = STABLE_MANIFEST_URL
DEFAULT_CHECK_INTERVAL_SECONDS = 24 * 60 * 60
DEFAULT_REQUEST_TIMEOUT_SECONDS = 10
DEFAULT_MAX_MANIFEST_BYTES = 256 * 1024
DEFAULT_MAX_INSTALLER_BYTES = 300 * 1024 * 1024
ALLOWED_UPDATE_CHANNELS = frozenset({"stable", "beta"})


def manifest_url_for_channel(channel: str) -> str | None:
    """Return the fixed endpoint for a supported update channel.

    A supported channel may deliberately have no endpoint yet. In that case
    the updater remains disabled for that channel instead of falling back to
    another channel's release metadata.
    """

    if channel not in ALLOWED_UPDATE_CHANNELS:
        raise ValueError(f"Unsupported update channel: {channel!r}")
    return UPDATE_MANIFEST_URLS[channel]


@dataclass(frozen=True, slots=True)
class UpdatePolicy:
    """Static safety limits and endpoint configuration for update checks."""

    manifest_url: str | None = DEFAULT_MANIFEST_URL
    channel: str = APP_UPDATE_CHANNEL
    check_interval_seconds: int = DEFAULT_CHECK_INTERVAL_SECONDS
    request_timeout_seconds: int = DEFAULT_REQUEST_TIMEOUT_SECONDS
    max_manifest_bytes: int = DEFAULT_MAX_MANIFEST_BYTES
    max_installer_bytes: int = DEFAULT_MAX_INSTALLER_BYTES

    def __post_init__(self) -> None:
        if self.channel not in ALLOWED_UPDATE_CHANNELS:
            raise ValueError(f"Unsupported update channel: {self.channel!r}")

        if self.check_interval_seconds <= 0:
            raise ValueError("Update check interval must be positive.")
        if self.request_timeout_seconds <= 0:
            raise ValueError("Update request timeout must be positive.")
        if self.max_manifest_bytes <= 0:
            raise ValueError("Maximum manifest size must be positive.")
        if self.max_installer_bytes <= 0:
            raise ValueError("Maximum installer size must be positive.")

        if self.manifest_url is not None:
            self._validate_manifest_url(self.manifest_url)

    @property
    def enabled(self) -> bool:
        """Whether a production update endpoint has been configured."""

        return self.manifest_url is not None

    @staticmethod
    def _validate_manifest_url(value: str) -> None:
        if not isinstance(value, str) or not value.strip():
            raise ValueError("Update manifest URL must be a non-empty HTTPS URL.")

        parsed = urlsplit(value.strip())
        if parsed.scheme.lower() != "https":
            raise ValueError("Update manifest URL must use HTTPS.")
        if not parsed.hostname:
            raise ValueError("Update manifest URL must include a host.")
        if parsed.username is not None or parsed.password is not None:
            raise ValueError("Update manifest URL must not contain credentials.")
        if parsed.fragment:
            raise ValueError("Update manifest URL must not contain a fragment.")


DEFAULT_UPDATE_POLICY = UpdatePolicy()
