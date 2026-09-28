"""Step 10B tests for the live ChitLog update-endpoint configuration."""
from __future__ import annotations

from types import SimpleNamespace
from urllib.parse import urlsplit

import pytest

from chitlog.core.update_config import (
    BETA_MANIFEST_URL,
    DEFAULT_MANIFEST_URL,
    DEFAULT_UPDATE_POLICY,
    STABLE_MANIFEST_URL,
    manifest_url_for_channel,
)
from chitlog.ui.update_check_runner import policy_from_preferences


EXPECTED_STABLE_URL = (
    "https://chitlog-updates.chitlogapp.workers.dev/"
    "api/updates/windows/stable"
)


def test_stable_endpoint_is_exact_https_cloudflare_route():
    assert STABLE_MANIFEST_URL == EXPECTED_STABLE_URL
    assert DEFAULT_MANIFEST_URL == EXPECTED_STABLE_URL
    assert DEFAULT_UPDATE_POLICY.manifest_url == EXPECTED_STABLE_URL
    assert DEFAULT_UPDATE_POLICY.enabled is True

    parsed = urlsplit(STABLE_MANIFEST_URL)
    assert parsed.scheme == "https"
    assert parsed.hostname == "chitlog-updates.chitlogapp.workers.dev"
    assert parsed.path == "/api/updates/windows/stable"
    assert parsed.query == ""
    assert parsed.fragment == ""
    assert parsed.username is None
    assert parsed.password is None


def test_beta_does_not_fall_back_to_stable_metadata():
    assert BETA_MANIFEST_URL is None
    assert manifest_url_for_channel("beta") is None

    policy = policy_from_preferences(
        SimpleNamespace(
            channel="beta",
            check_interval_seconds=86400,
        )
    )
    assert policy.channel == "beta"
    assert policy.manifest_url is None
    assert policy.enabled is False


def test_stable_preferences_receive_only_fixed_application_endpoint():
    policy = policy_from_preferences(
        SimpleNamespace(
            channel="stable",
            check_interval_seconds=43200,
        )
    )
    assert policy.manifest_url == EXPECTED_STABLE_URL
    assert policy.channel == "stable"
    assert policy.enabled is True
    assert policy.check_interval_seconds == 43200


@pytest.mark.parametrize("channel", ["", "nightly", "dev", "Stable"])
def test_unsupported_channel_has_no_endpoint(channel):
    with pytest.raises(ValueError, match="Unsupported update channel"):
        manifest_url_for_channel(channel)


def test_endpoint_contains_no_user_financial_or_credential_values():
    parsed = urlsplit(STABLE_MANIFEST_URL)

    # Cloudflare's infrastructure hostname legitimately contains
    # "workers.dev". Privacy assertions therefore inspect only request
    # components that ChitLog controls and could use to transmit user data.
    controlled_request_text = (
        f"{parsed.path}?{parsed.query}".lower()
    )

    for forbidden in (
        "transaction",
        "income",
        "expense",
        "worker",
        "payroll",
        "liability",
        "budget",
        "password",
        "pin",
        "token",
        "email",
        "user=",
    ):
        assert forbidden not in controlled_request_text

    assert parsed.query == ""
    assert parsed.username is None
    assert parsed.password is None
