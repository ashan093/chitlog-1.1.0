"""Secure end-to-end update check pipeline for ChitLog.

Pipeline:
restricted HTTPS fetch
    -> strict manifest parse
    -> Ed25519 signature verification
    -> local update decision

No UI, scheduling, download, installer execution, or production signing key
management lives in this module.
"""
from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from enum import Enum

from chitlog.core.update_config import DEFAULT_UPDATE_POLICY, UpdatePolicy
from chitlog.core.update_decision import (
    UpdateDecision,
    UpdateDecisionError,
    decide_update,
)
from chitlog.core.update_manifest import (
    SignedUpdateManifest,
    UpdateManifestError,
)
from chitlog.core.update_signature import (
    TRUSTED_UPDATE_PUBLIC_KEYS,
    UpdateSignatureError,
    verify_manifest_signature,
)
from chitlog.core.update_transport import (
    UpdateCheckDisabledError,
    UpdateTransportError,
    fetch_manifest_bytes,
)
from chitlog.core.version import APP_VERSION


ManifestFetcher = Callable[[UpdatePolicy], bytes]


class UpdateCheckFailureKind(str, Enum):
    """Stable categories that later UI/scheduling code can handle safely."""

    DISABLED = "disabled"
    NETWORK = "network"
    SECURITY = "security"
    POLICY = "policy"


class UpdateCheckError(RuntimeError):
    """Normalized failure from the secure update-check pipeline."""

    def __init__(
        self,
        kind: UpdateCheckFailureKind,
        message: str,
    ) -> None:
        super().__init__(message)
        self.kind = kind


@dataclass(frozen=True, slots=True)
class UpdateCheckOutcome:
    """Successful secure update check result.

    ``manifest`` preserves the exact signed envelope that was verified.  Later
    updater stages can hand this evidence to the standalone updater so it can
    independently re-verify the release before installation.
    """

    decision: UpdateDecision
    manifest: SignedUpdateManifest | None = None

    def __post_init__(self) -> None:
        if self.manifest is not None and self.manifest.payload != self.decision.payload:
            raise ValueError(
                "Verified manifest payload does not match the update decision."
            )

    @property
    def update_available(self) -> bool:
        return self.decision.update_available

    @property
    def update_required(self) -> bool:
        return self.decision.update_required


def check_for_updates(
    policy: UpdatePolicy = DEFAULT_UPDATE_POLICY,
    *,
    current_version: str = APP_VERSION,
    trusted_keys: Mapping[str, bytes] = TRUSTED_UPDATE_PUBLIC_KEYS,
    fetcher: ManifestFetcher = fetch_manifest_bytes,
) -> UpdateCheckOutcome:
    """Perform one complete secure update check.

    The manifest payload is never used for version/update decisions until its
    Ed25519 signature has been verified successfully.
    """

    if not isinstance(policy, UpdatePolicy):
        raise TypeError("policy must be an UpdatePolicy.")

    try:
        raw_manifest = fetcher(policy)
    except UpdateCheckDisabledError as exc:
        raise UpdateCheckError(
            UpdateCheckFailureKind.DISABLED,
            "Automatic update checking is not configured.",
        ) from exc
    except UpdateTransportError as exc:
        raise UpdateCheckError(
            UpdateCheckFailureKind.NETWORK,
            "The update server could not be checked safely.",
        ) from exc

    try:
        manifest = SignedUpdateManifest.from_json_bytes(raw_manifest)
        verified_payload = verify_manifest_signature(
            manifest,
            trusted_keys=trusted_keys,
        )
    except (UpdateManifestError, UpdateSignatureError) as exc:
        raise UpdateCheckError(
            UpdateCheckFailureKind.SECURITY,
            "The update information could not be verified.",
        ) from exc

    try:
        decision = decide_update(
            verified_payload,
            current_version=current_version,
            policy=policy,
        )
    except UpdateDecisionError as exc:
        raise UpdateCheckError(
            UpdateCheckFailureKind.POLICY,
            "The verified update information conflicts with local policy.",
        ) from exc

    return UpdateCheckOutcome(
        decision=decision,
        manifest=manifest,
    )
