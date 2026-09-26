"""Step 4D1 tests for persistent automatic-update schedule state."""
from __future__ import annotations

import secrets
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from chitlog.data.database import Database
from chitlog.data.update_preferences_repository import (
    UpdatePreferencesRepository,
)
from chitlog.data.update_schedule_repository import (
    LAST_CHECK_ATTEMPT_KEY,
    StoredUpdateScheduleState,
    UpdateScheduleStateRepository,
    UpdateScheduleStorageError,
)
from chitlog.services.update_preferences_service import (
    UpdatePreferencesService,
)
from chitlog.services.update_schedule_service import (
    UpdateScheduleService,
)


UTC = timezone.utc


def make_database(tmp_path: Path) -> Database:
    return Database(
        tmp_path / "schedule.db",
        secrets.token_bytes(32),
        tmp_path / "snapshots",
    ).open()


def make_services(db):
    preferences = UpdatePreferencesService(
        UpdatePreferencesRepository(db)
    )
    schedule = UpdateScheduleService(
        preferences,
        UpdateScheduleStateRepository(db),
    )
    return preferences, schedule


def test_schedule_state_needs_no_new_schema_migration(tmp_path):
    db = make_database(tmp_path)
    try:
        assert db.version == 17
        row = db.connection.execute(
            "SELECT value FROM application_settings WHERE key=?",
            (LAST_CHECK_ATTEMPT_KEY,),
        ).fetchone()
        assert row is None
    finally:
        db.close()


def test_first_automatic_check_is_due_when_enabled(tmp_path):
    db = make_database(tmp_path)
    try:
        _, schedule = make_services(db)
        now = datetime(2026, 9, 26, 0, 0, tzinfo=UTC)
        state = schedule.snapshot(now_utc=now)

        assert state.auto_check_enabled is True
        assert state.channel == "stable"
        assert state.check_interval_seconds == 24 * 60 * 60
        assert state.last_check_attempt_at_utc is None
        assert state.due is True
        assert state.next_check_at_utc == now
    finally:
        db.close()


def test_recorded_attempt_is_not_due_until_interval_passes(tmp_path):
    db = make_database(tmp_path)
    try:
        _, schedule = make_services(db)
        start = datetime(2026, 9, 26, 1, 2, 3, tzinfo=UTC)

        after_record = schedule.record_check_attempt(now_utc=start)
        assert after_record.last_check_attempt_at_utc == start
        assert after_record.due is False
        assert after_record.next_check_at_utc == (
            start + timedelta(hours=24)
        )

        before = schedule.snapshot(
            now_utc=start + timedelta(hours=23, minutes=59)
        )
        assert before.due is False

        exactly_due = schedule.snapshot(
            now_utc=start + timedelta(hours=24)
        )
        assert exactly_due.due is True
    finally:
        db.close()


def test_attempt_timestamp_persists_across_service_restart(tmp_path):
    db = make_database(tmp_path)
    try:
        preferences, schedule = make_services(db)
        attempt = datetime(2026, 9, 26, 3, 4, 5, tzinfo=UTC)
        schedule.record_check_attempt(now_utc=attempt)

        reloaded = UpdateScheduleService(
            preferences,
            UpdateScheduleStateRepository(db),
        ).snapshot(now_utc=attempt + timedelta(hours=1))

        assert reloaded.last_check_attempt_at_utc == attempt
        assert reloaded.due is False

        stored = db.connection.execute(
            "SELECT value FROM application_settings WHERE key=?",
            (LAST_CHECK_ATTEMPT_KEY,),
        ).fetchone()
        assert stored == ("2026-09-26T03:04:05Z",)
    finally:
        db.close()


def test_disabling_automatic_checks_makes_schedule_not_due(tmp_path):
    db = make_database(tmp_path)
    try:
        preferences, schedule = make_services(db)
        preferences.set_auto_check_enabled(False)

        state = schedule.snapshot(
            now_utc=datetime(2026, 9, 26, 5, 0, tzinfo=UTC)
        )
        assert state.auto_check_enabled is False
        assert state.due is False
        assert state.next_check_at_utc is None
    finally:
        db.close()


def test_saved_interval_controls_due_time(tmp_path):
    db = make_database(tmp_path)
    try:
        preferences, schedule = make_services(db)
        preferences.set_check_interval_seconds(12 * 60 * 60)

        start = datetime(2026, 9, 26, 6, 0, tzinfo=UTC)
        schedule.record_check_attempt(now_utc=start)

        assert schedule.snapshot(
            now_utc=start + timedelta(hours=11, minutes=59)
        ).due is False
        assert schedule.snapshot(
            now_utc=start + timedelta(hours=12)
        ).due is True
    finally:
        db.close()


def test_channel_is_reflected_in_schedule_snapshot(tmp_path):
    db = make_database(tmp_path)
    try:
        preferences, schedule = make_services(db)
        preferences.set_channel("beta")

        state = schedule.snapshot(
            now_utc=datetime(2026, 9, 26, 7, 0, tzinfo=UTC)
        )
        assert state.channel == "beta"
    finally:
        db.close()


def test_future_last_attempt_does_not_trigger_immediate_retry(tmp_path):
    db = make_database(tmp_path)
    try:
        _, schedule = make_services(db)
        now = datetime(2026, 9, 26, 8, 0, tzinfo=UTC)
        future = now + timedelta(hours=2)

        schedule.repository.save(
            StoredUpdateScheduleState(
                last_check_attempt_at_utc=future
            )
        )
        state = schedule.snapshot(now_utc=now)

        assert state.due is False
        assert state.next_check_at_utc == (
            future + timedelta(hours=24)
        )
    finally:
        db.close()


def test_offset_timestamp_is_normalized_to_utc_on_save(tmp_path):
    db = make_database(tmp_path)
    try:
        repository = UpdateScheduleStateRepository(db)
        offset = timezone(timedelta(hours=5, minutes=30))
        value = datetime(2026, 9, 26, 12, 30, tzinfo=offset)

        repository.save(
            StoredUpdateScheduleState(
                last_check_attempt_at_utc=value
            )
        )
        loaded = repository.load()

        assert loaded.last_check_attempt_at_utc == datetime(
            2026, 9, 26, 7, 0, tzinfo=UTC
        )
    finally:
        db.close()


@pytest.mark.parametrize(
    "stored",
    [
        "not-a-date",
        "2026-09-26 07:00:00",
        "2026-09-26T07:00:00+00:00",
        "2026-09-26T07:00:00z",
        "2026-13-26T07:00:00Z",
    ],
)
def test_corrupt_schedule_timestamp_is_rejected(tmp_path, stored):
    db = make_database(tmp_path)
    try:
        with db.transaction() as connection:
            connection.execute(
                "INSERT INTO application_settings(key,value) VALUES (?,?) "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                (LAST_CHECK_ATTEMPT_KEY, stored),
            )

        with pytest.raises(UpdateScheduleStorageError):
            UpdateScheduleStateRepository(db).load()
    finally:
        db.close()


def test_naive_timestamp_is_rejected_on_save(tmp_path):
    db = make_database(tmp_path)
    try:
        repository = UpdateScheduleStateRepository(db)
        with pytest.raises(ValueError, match="timezone-aware"):
            repository.save(
                StoredUpdateScheduleState(
                    last_check_attempt_at_utc=datetime(
                        2026, 9, 26, 7, 0
                    )
                )
            )
    finally:
        db.close()


@pytest.mark.parametrize(
    "now_value",
    [
        "2026-09-26T07:00:00Z",
        datetime(2026, 9, 26, 7, 0),
    ],
)
def test_invalid_now_value_is_rejected(tmp_path, now_value):
    db = make_database(tmp_path)
    try:
        _, schedule = make_services(db)
        expected = TypeError if isinstance(now_value, str) else ValueError
        with pytest.raises(expected):
            schedule.snapshot(now_utc=now_value)
    finally:
        db.close()


def test_step4d1_sources_have_no_network_or_qt_imports():
    project = Path(__file__).resolve().parents[1]
    sources = [
        (
            project
            / "chitlog/data/update_schedule_repository.py"
        ).read_text(encoding="utf-8"),
        (
            project
            / "chitlog/services/update_schedule_service.py"
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
        "QTimer",
        "QThread",
    ):
        assert forbidden not in combined
