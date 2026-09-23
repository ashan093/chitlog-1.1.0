"""Pure command-construction checks for Windows Task Scheduler integration."""
from pathlib import Path
from types import SimpleNamespace

from chitlog.services.windows_reminder_task import WindowsReminderTaskScheduler


class Runner:
    def __init__(self):
        self.calls = []

    def __call__(self, args, **kwargs):
        self.calls.append((args, kwargs))
        return SimpleNamespace(returncode=0, stdout="", stderr="")


def test_windows_task_uses_daily_interactive_current_user_schedule(tmp_path):
    runner = Runner()
    python = tmp_path / "python.exe"
    python.write_text("", encoding="utf-8")
    pythonw = tmp_path / "pythonw.exe"
    pythonw.write_text("", encoding="utf-8")
    app = tmp_path / "app.py"
    app.write_text("", encoding="utf-8")

    scheduler = WindowsReminderTaskScheduler(
        app,
        python_executable=python,
        runner=runner,
        platform="win32",
        frozen=False,
    )
    scheduler.enable("19:45")

    args = runner.calls[0][0]
    assert args[0] == "schtasks.exe"
    assert "/Create" in args
    assert "/SC" in args and "DAILY" in args
    assert "/ST" in args and "19:45" in args
    assert "/IT" in args
    assert "--notification-only" in args[args.index("/TR") + 1]
    assert str(pythonw) in args[args.index("/TR") + 1]
    assert str(app) in args[args.index("/TR") + 1]
