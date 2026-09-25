"""Pure update-decision logic for ChitLog.

This module performs no network access and no cryptographic work.  It accepts
only an already parsed/verified update payload and decides what the running app
should do with it.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from chitlog.core.update_config import DEFAULT_UPDATE_POLICY, UpdatePolicy
from chitlog.core.update_manifest import UpdateManifestPayload
from chitlog.core.version import APP_VERSION, Version, VersionFormatError


class UpdateDecisionError(ValueError):
    """Raised when verified update metadata conflicts with local policy."""


class UpdateDisposition(str, Enum):
    """High-level result of comparing a verified release to this app."""

    UP_TO_DATE = "up_to_date"
    OPTIONAL_UPDATE = "optional_update"
    REQUIRED_UPDATE = "required_update"


@dataclass(frozen=True, slots=True)
class UpdateDecision:
    disposition: UpdateDisposition
    current_version: str
    available_version: str
    mandatory: bool
    below_minimum_supported: bool
    payload: UpdateManifestPayload

    @property
    def update_available(self) -> bool:
        return self.disposition is not UpdateDisposition.UP_TO_DATE

    @property
    def update_required(self) -> bool:
        return self.disposition is UpdateDisposition.REQUIRED_UPDATE


def decide_update(
    payload: UpdateManifestPayload,
    *,
    current_version: str = APP_VERSION,
    policy: UpdatePolicy = DEFAULT_UPDATE_POLICY,
) -> UpdateDecision:
    """Evaluate verified manifest payload against local update policy.

    The caller must verify the manifest signature before calling this function.
    """

    if not isinstance(payload, UpdateManifestPayload):
        raise TypeError("payload must be an UpdateManifestPayload.")
    if not isinstance(policy, UpdatePolicy):
        raise TypeError("policy must be an UpdatePolicy.")

    if payload.channel != policy.channel:
        raise UpdateDecisionError(
            f"Verified manifest channel {payload.channel!r} does not match "
            f"configured channel {policy.channel!r}."
        )

    if payload.installer_size > policy.max_installer_bytes:
        raise UpdateDecisionError(
            "Verified installer size exceeds the configured safety limit."
        )

    try:
        running = Version.parse(current_version)
    except VersionFormatError as exc:
        raise UpdateDecisionError("Running application version is invalid.") from exc

    available = Version.parse(payload.version)
    minimum = Version.parse(payload.minimum_supported_version)

    below_minimum = running < minimum

    if available <= running:
        disposition = UpdateDisposition.UP_TO_DATE
    elif payload.mandatory or below_minimum:
        disposition = UpdateDisposition.REQUIRED_UPDATE
    else:
        disposition = UpdateDisposition.OPTIONAL_UPDATE

    return UpdateDecision(
        disposition=disposition,
        current_version=str(running),
        available_version=str(available),
        mandatory=payload.mandatory,
        below_minimum_supported=below_minimum,
        payload=payload,
    )
