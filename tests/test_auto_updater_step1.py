"""Step 1 tests for the ChitLog automatic-updater foundation."""
import pytest

from chitlog.core.update_config import (
    DEFAULT_CHECK_INTERVAL_SECONDS,
    DEFAULT_UPDATE_POLICY,
    UpdatePolicy,
)
from chitlog.core.version import (
    APP_NAME,
    APP_UPDATE_CHANNEL,
    APP_VERSION,
    Version,
    VersionFormatError,
    current_version,
    is_newer_version,
)


def test_application_identity_is_centralized():
    assert APP_NAME == "ChitLog"
    assert APP_VERSION == "1.1.0"
    assert APP_UPDATE_CHANNEL == "stable"
    assert str(current_version()) == APP_VERSION


def test_version_comparison_is_numeric_not_lexical():
    assert Version.parse("1.10.0") > Version.parse("1.9.9")
    assert Version.parse("2.0.0") > Version.parse("1.99.99")
    assert Version.parse("1.1.1") > Version.parse("1.1.0")
    assert is_newer_version("1.1.1", "1.1.0") is True
    assert is_newer_version("1.1.0", "1.1.0") is False
    assert is_newer_version("1.0.9", "1.1.0") is False


@pytest.mark.parametrize(
    "value",
    [
        "",
        "1",
        "1.1",
        "v1.1.0",
        "1.1.0.0",
        "01.1.0",
        "1.01.0",
        "1.1.00",
        "1.1.-1",
        "1.1.x",
        "1.1.0-beta",
    ],
)
def test_invalid_versions_are_rejected(value):
    with pytest.raises(VersionFormatError):
        Version.parse(value)


def test_updates_are_disabled_until_real_endpoint_is_configured():
    assert DEFAULT_UPDATE_POLICY.enabled is False
    assert DEFAULT_UPDATE_POLICY.manifest_url is None
    assert DEFAULT_UPDATE_POLICY.channel == "stable"
    assert DEFAULT_UPDATE_POLICY.check_interval_seconds == 24 * 60 * 60
    assert DEFAULT_UPDATE_POLICY.check_interval_seconds == DEFAULT_CHECK_INTERVAL_SECONDS


def test_https_manifest_url_is_accepted():
    policy = UpdatePolicy(
        manifest_url="https://chitlog.example/api/updates/windows/stable"
    )
    assert policy.enabled is True


@pytest.mark.parametrize(
    "url",
    [
        "",
        "http://chitlog.example/update.json",
        "ftp://chitlog.example/update.json",
        "https:///update.json",
        "https://user:password@chitlog.example/update.json",
        "https://chitlog.example/update.json#fragment",
    ],
)
def test_unsafe_manifest_urls_are_rejected(url):
    with pytest.raises(ValueError):
        UpdatePolicy(manifest_url=url)


@pytest.mark.parametrize(
    "kwargs",
    [
        {"channel": "nightly"},
        {"check_interval_seconds": 0},
        {"request_timeout_seconds": 0},
        {"max_installer_bytes": 0},
    ],
)
def test_invalid_update_policy_values_are_rejected(kwargs):
    with pytest.raises(ValueError):
        UpdatePolicy(**kwargs)
