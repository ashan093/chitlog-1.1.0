"""Step 22 scheduled-task input/error hardening."""
import subprocess

import pytest

from chitlog.services.windows_reminder_task import (
    ReminderTaskError,
    WindowsReminderTaskScheduler,
)


def test_reminder_scheduler_rejects_malformed_time_before_process_launch(tmp_path):
    calls = []

    def runner(*args, **kwargs):
        calls.append((args, kwargs))

    scheduler = WindowsReminderTaskScheduler(
        tmp_path / "app.py",
        python_executable=tmp_path / "python.exe",
        runner=runner,
        platform="win32",
    )

    for value in ("7:00", "25:00", "12:99", "--bad", ""):
        with pytest.raises(ReminderTaskError, match="HH:MM"):
            scheduler.enable(value)

    assert calls == []


def test_reminder_scheduler_does_not_surface_raw_schtasks_output(tmp_path):
    def runner(*_args, **_kwargs):
        raise subprocess.CalledProcessError(
            1,
            ["schtasks.exe"],
            output="C:\\Users\\PrivateName\\secret-path",
            stderr="private scheduler details",
        )

    scheduler = WindowsReminderTaskScheduler(
        tmp_path / "app.py",
        python_executable=tmp_path / "python.exe",
        runner=runner,
        platform="win32",
    )

    with pytest.raises(ReminderTaskError) as error:
        scheduler.enable("19:45")

    message = str(error.value)
    assert "PrivateName" not in message
    assert "secret-path" not in message
    assert "private scheduler details" not in message
