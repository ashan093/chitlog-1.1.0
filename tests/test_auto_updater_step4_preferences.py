"""Step 4A tests for persisted ChitLog update preferences."""
from __future__ import annotations

import secrets
from pathlib import Path

import pytest

from chitlog.core.update_config import DEFAULT_CHECK_INTERVAL_SECONDS
from chitlog.data.database import Database
from chitlog.data.migrations import MIGRATIONS
from chitlog.data.update_preferences_repository import (
    AUTO_CHECK_KEY,
    AUTO_INSTALL_KEY,
    CHANNEL_KEY,
    CHECK_INTERVAL_KEY,
    DEFAULT_AUTO_CHECK_ENABLED,
    DEFAULT_AUTO_INSTALL_ENABLED,
    UpdatePreferencesRepository,
    UpdatePreferencesStorageError,
)
from chitlog.services.update_preferences_service import (
    DEFAULT_UPDATE_PREFERENCES,
    UpdatePreferencesError,
    UpdatePreferencesService,
)


def make_database(tmp_path: Path) -> Database:
    return Database(
        tmp_path / "preferences.db",
        secrets.token_bytes(32),
        tmp_path / "snapshots",
    ).open()


def test_migration_17_is_update_preferences_foundation():
    version, name, statements = MIGRATIONS[-1]
    assert version == 17
    assert name == "automatic_update_preferences"
    joined = "\n".join(statements)
    assert AUTO_CHECK_KEY in joined
    assert AUTO_INSTALL_KEY in joined
    assert CHANNEL_KEY in joined
    assert CHECK_INTERVAL_KEY in joined


def test_fresh_database_contains_secure_conservative_defaults(tmp_path):
    db = make_database(tmp_path)
    try:
        assert db.version == 17
        rows = dict(
            db.connection.execute(
                "SELECT key,value FROM application_settings "
                "WHERE key LIKE 'update_%'"
            ).fetchall()
        )
        assert rows[AUTO_CHECK_KEY] == "1"
        assert rows[AUTO_INSTALL_KEY] == "0"
        assert rows[CHANNEL_KEY] == "stable"
        assert rows[CHECK_INTERVAL_KEY] == str(
            DEFAULT_CHECK_INTERVAL_SECONDS
        )
    finally:
        db.close()


def test_service_defaults_match_product_policy(tmp_path):
    db = make_database(tmp_path)
    try:
        service = UpdatePreferencesService(
            UpdatePreferencesRepository(db)
        )
        snapshot = service.snapshot()

        assert snapshot.auto_check_enabled is True
        assert snapshot.auto_install_enabled is False
        assert snapshot.channel == "stable"
        assert snapshot.check_interval_seconds == 24 * 60 * 60
        assert snapshot == DEFAULT_UPDATE_PREFERENCES
        assert DEFAULT_AUTO_CHECK_ENABLED is True
        assert DEFAULT_AUTO_INSTALL_ENABLED is False
    finally:
        db.close()


def test_automatic_check_toggle_persists(tmp_path):
    db = make_database(tmp_path)
    try:
        service = UpdatePreferencesService(
            UpdatePreferencesRepository(db)
        )
        saved = service.set_auto_check_enabled(False)
        assert saved.auto_check_enabled is False

        reloaded = UpdatePreferencesService(
            UpdatePreferencesRepository(db)
        ).snapshot()
        assert reloaded.auto_check_enabled is False
        assert reloaded.auto_install_enabled is False
    finally:
        db.close()


def test_auto_install_stays_separate_and_defaults_off(tmp_path):
    db = make_database(tmp_path)
    try:
        service = UpdatePreferencesService(
            UpdatePreferencesRepository(db)
        )
        assert service.snapshot().auto_install_enabled is False

        changed = service.set_auto_install_enabled(True)
        assert changed.auto_install_enabled is True
        assert changed.auto_check_enabled is True

        changed = service.set_auto_install_enabled(False)
        assert changed.auto_install_enabled is False
    finally:
        db.close()


@pytest.mark.parametrize("channel", ["stable", "beta"])
def test_supported_channel_persists(tmp_path, channel):
    db = make_database(tmp_path)
    try:
        service = UpdatePreferencesService(
            UpdatePreferencesRepository(db)
        )
        saved = service.set_channel(channel)
        assert saved.channel == channel
        assert service.snapshot().channel == channel
    finally:
        db.close()


@pytest.mark.parametrize("channel", ["", "nightly", "dev"])
def test_unsupported_channel_is_rejected(tmp_path, channel):
    db = make_database(tmp_path)
    try:
        service = UpdatePreferencesService(
            UpdatePreferencesRepository(db)
        )
        with pytest.raises(UpdatePreferencesError, match="Unsupported"):
            service.set_channel(channel)
    finally:
        db.close()


def test_channel_is_normalized_before_validation(tmp_path):
    db = make_database(tmp_path)
    try:
        service = UpdatePreferencesService(
            UpdatePreferencesRepository(db)
        )
        assert service.set_channel(" Stable ").channel == "stable"
    finally:
        db.close()


def test_check_interval_persists(tmp_path):
    db = make_database(tmp_path)
    try:
        service = UpdatePreferencesService(
            UpdatePreferencesRepository(db)
        )
        saved = service.set_check_interval_seconds(12 * 60 * 60)
        assert saved.check_interval_seconds == 12 * 60 * 60

        reloaded = UpdatePreferencesService(
            UpdatePreferencesRepository(db)
        ).snapshot()
        assert reloaded.check_interval_seconds == 12 * 60 * 60
    finally:
        db.close()


@pytest.mark.parametrize("value", [0, -1, True, 1.5, "86400"])
def test_invalid_check_interval_is_rejected(tmp_path, value):
    db = make_database(tmp_path)
    try:
        service = UpdatePreferencesService(
            UpdatePreferencesRepository(db)
        )
        with pytest.raises(
            UpdatePreferencesError,
            match="positive integer",
        ):
            service.set_check_interval_seconds(value)
    finally:
        db.close()


@pytest.mark.parametrize(
    ("key", "value"),
    [
        (AUTO_CHECK_KEY, "yes"),
        (AUTO_INSTALL_KEY, "false"),
        (CHANNEL_KEY, "nightly"),
        (CHECK_INTERVAL_KEY, "not-a-number"),
        (CHECK_INTERVAL_KEY, "0"),
    ],
)
def test_corrupt_stored_preference_is_rejected_safely(
    tmp_path,
    key,
    value,
):
    db = make_database(tmp_path)
    try:
        with db.transaction() as connection:
            connection.execute(
                "UPDATE application_settings SET value=? WHERE key=?",
                (value, key),
            )

        repository = UpdatePreferencesRepository(db)
        with pytest.raises(UpdatePreferencesStorageError):
            repository.load()
    finally:
        db.close()


def test_step4a_sources_have_no_network_or_ui_imports():
    project = Path(__file__).resolve().parents[1]
    sources = [
        (
            project
            / "chitlog/data/update_preferences_repository.py"
        ).read_text(encoding="utf-8"),
        (
            project
            / "chitlog/services/update_preferences_service.py"
        ).read_text(encoding="utf-8"),
    ]
    combined = "\n".join(sources)

    for forbidden in (
        "update_transport",
        "update_checker",
        "http.client",
        "urllib.request",
        "requests",
        "httpx",
        "PySide6",
    ):
        assert forbidden not in combined
