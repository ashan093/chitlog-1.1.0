"""Windows Task Scheduler integration for closed-app reminders."""
from __future__ import annotations

from datetime import datetime
from pathlib import Path
import subprocess
import sys


class ReminderTaskError(RuntimeError):
    """Raised when Windows cannot create/update the ChitLog reminder task."""


class WindowsReminderTaskScheduler:
    TASK_NAME = "ChitLog Daily Reminder"

    def __init__(
        self,
        app_entry: str | Path | None = None,
        *,
        python_executable: str | Path | None = None,
        runner=None,
        platform: str | None = None,
        frozen: bool | None = None,
    ):
        self.app_entry = Path(app_entry or sys.argv[0]).resolve()
        self.python_executable = Path(python_executable or sys.executable).resolve()
        self.runner = runner or subprocess.run
        self.platform = platform or sys.platform
        self.frozen = bool(getattr(sys, "frozen", False)) if frozen is None else bool(frozen)

    @property
    def supported(self) -> bool:
        return self.platform == "win32"

    @staticmethod
    def _validate_reminder_time(value: str) -> str:
        if not isinstance(value, str) or len(value) != 5:
            raise ReminderTaskError("Reminder time must use 24-hour HH:MM format.")
        try:
            parsed = datetime.strptime(value, "%H:%M")
        except ValueError:
            raise ReminderTaskError(
                "Reminder time must use 24-hour HH:MM format."
            ) from None
        if parsed.strftime("%H:%M") != value:
            raise ReminderTaskError("Reminder time must use 24-hour HH:MM format.")
        return value

    def _action_command(self) -> str:
        if self.frozen:
            parts = [str(self.python_executable), "--notification-only"]
        else:
            pythonw = self.python_executable.with_name("pythonw.exe")
            executable = pythonw if pythonw.exists() else self.python_executable
            parts = [str(executable), str(self.app_entry), "--notification-only"]
        return subprocess.list2cmdline(parts)

    def _run(self, args: list[str], *, check: bool = True):
        return self.runner(
            args,
            capture_output=True,
            text=True,
            check=check,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )

    def enable(self, reminder_time: str) -> None:
        if not self.supported:
            raise ReminderTaskError(
                "Closed-app reminders are available on Windows only."
            )

        reminder_time = self._validate_reminder_time(reminder_time)
        command = self._action_command()
        args = [
            "schtasks.exe",
            "/Create",
            "/TN",
            self.TASK_NAME,
            "/TR",
            command,
            "/SC",
            "DAILY",
            "/ST",
            reminder_time,
            "/IT",
            "/RL",
            "LIMITED",
            "/F",
        ]
        try:
            self._run(args)
        except (OSError, subprocess.CalledProcessError):
            # Do not surface raw schtasks output: it can contain machine/user
            # details or local executable paths.
            raise ReminderTaskError(
                "Windows could not create the closed-app reminder task."
            ) from None

    def disable(self) -> None:
        if not self.supported:
            return
        try:
            # Deleting a task that does not exist is harmless for our purposes.
            self._run(
                [
                    "schtasks.exe",
                    "/Delete",
                    "/TN",
                    self.TASK_NAME,
                    "/F",
                ],
                check=False,
            )
        except OSError:
            pass
