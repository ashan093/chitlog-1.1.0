"""Post-install application relaunch for the standalone ChitLog updater.

This module is intentionally narrow: after the verified installer reports
success, it validates the exact application path that was bound to the
originating ChitLog process and starts that executable directly with
CreateProcessW. No shell, script host, command interpreter, or user-controlled
command-line arguments are used.
"""
from __future__ import annotations

import ctypes
from ctypes import wintypes
from dataclasses import dataclass
import os
from pathlib import Path
from typing import Callable

from chitlog.core.update_handoff import VerifiedUpdateHandoff
from chitlog.core.update_installer_execution import verify_windows_installer_pe


EXPECTED_APPLICATION_NAME = "ChitLog.exe"


class ApplicationRelaunchError(RuntimeError):
    """Base class for safe post-install relaunch failures."""


class ApplicationRelaunchPathError(ApplicationRelaunchError):
    """Raised when the installed ChitLog executable path is unsafe."""


class ApplicationRelaunchLaunchError(ApplicationRelaunchError):
    """Raised when Windows cannot start the updated ChitLog executable."""


@dataclass(frozen=True, slots=True)
class ApplicationRelaunchResult:
    application_path: Path
    process_id: int


ApplicationLauncher = Callable[[Path], int]


def validate_relaunch_application(path: str | Path) -> Path:
    """Validate the exact installed ChitLog executable after installation."""

    candidate = Path(path)
    if not candidate.is_absolute():
        raise ApplicationRelaunchPathError(
            "Updated ChitLog executable path must be absolute."
        )

    try:
        if candidate.is_symlink():
            raise ApplicationRelaunchPathError(
                "Updated ChitLog executable must not be a symbolic link."
            )
        resolved = candidate.resolve(strict=True)
    except OSError as exc:
        raise ApplicationRelaunchPathError(
            "Updated ChitLog executable could not be resolved."
        ) from exc

    if not resolved.is_file():
        raise ApplicationRelaunchPathError(
            "Updated ChitLog executable is not a regular file."
        )
    if resolved.name.casefold() != EXPECTED_APPLICATION_NAME.casefold():
        raise ApplicationRelaunchPathError(
            "Updated application filename is not ChitLog.exe."
        )

    # Structural PE validation catches missing/corrupted replacement output.
    return verify_windows_installer_pe(resolved)


class _StartupInfoW(ctypes.Structure):
    _fields_ = [
        ("cb", wintypes.DWORD),
        ("lpReserved", wintypes.LPWSTR),
        ("lpDesktop", wintypes.LPWSTR),
        ("lpTitle", wintypes.LPWSTR),
        ("dwX", wintypes.DWORD),
        ("dwY", wintypes.DWORD),
        ("dwXSize", wintypes.DWORD),
        ("dwYSize", wintypes.DWORD),
        ("dwXCountChars", wintypes.DWORD),
        ("dwYCountChars", wintypes.DWORD),
        ("dwFillAttribute", wintypes.DWORD),
        ("dwFlags", wintypes.DWORD),
        ("wShowWindow", wintypes.WORD),
        ("cbReserved2", wintypes.WORD),
        ("lpReserved2", ctypes.POINTER(ctypes.c_ubyte)),
        ("hStdInput", wintypes.HANDLE),
        ("hStdOutput", wintypes.HANDLE),
        ("hStdError", wintypes.HANDLE),
    ]


class _ProcessInformation(ctypes.Structure):
    _fields_ = [
        ("hProcess", wintypes.HANDLE),
        ("hThread", wintypes.HANDLE),
        ("dwProcessId", wintypes.DWORD),
        ("dwThreadId", wintypes.DWORD),
    ]


def _launch_windows_application(application_path: Path) -> int:
    if os.name != "nt":
        raise ApplicationRelaunchLaunchError(
            "ChitLog relaunch is supported only on Windows."
        )

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    create_process = kernel32.CreateProcessW
    create_process.argtypes = [
        wintypes.LPCWSTR,
        wintypes.LPWSTR,
        wintypes.LPVOID,
        wintypes.LPVOID,
        wintypes.BOOL,
        wintypes.DWORD,
        wintypes.LPVOID,
        wintypes.LPCWSTR,
        ctypes.POINTER(_StartupInfoW),
        ctypes.POINTER(_ProcessInformation),
    ]
    create_process.restype = wintypes.BOOL

    close_handle = kernel32.CloseHandle
    close_handle.argtypes = [wintypes.HANDLE]
    close_handle.restype = wintypes.BOOL

    startup = _StartupInfoW()
    startup.cb = ctypes.sizeof(_StartupInfoW)
    process = _ProcessInformation()

    # lpApplicationName is the exact verified path. lpCommandLine is NULL, so
    # no handoff/user text can be interpreted as application arguments.
    if not create_process(
        str(application_path),
        None,
        None,
        None,
        False,
        0,
        None,
        str(application_path.parent),
        ctypes.byref(startup),
        ctypes.byref(process),
    ):
        raise ApplicationRelaunchLaunchError(
            "Windows could not restart the updated ChitLog application."
        )

    if not process.hProcess or not process.hThread or process.dwProcessId <= 0:
        if process.hThread:
            close_handle(process.hThread)
        if process.hProcess:
            close_handle(process.hProcess)
        raise ApplicationRelaunchLaunchError(
            "Windows returned an invalid ChitLog relaunch process."
        )

    try:
        return int(process.dwProcessId)
    finally:
        close_handle(process.hThread)
        close_handle(process.hProcess)


def relaunch_updated_application(
    verified: VerifiedUpdateHandoff,
    *,
    launcher: ApplicationLauncher = _launch_windows_application,
) -> ApplicationRelaunchResult:
    """Validate and start the updated ChitLog executable exactly once."""

    if not isinstance(verified, VerifiedUpdateHandoff):
        raise TypeError("verified must be a VerifiedUpdateHandoff.")

    application_path = validate_relaunch_application(
        verified.application_path
    )
    process_id = int(launcher(application_path))
    if process_id <= 0:
        raise ApplicationRelaunchLaunchError(
            "Windows returned an invalid ChitLog process ID."
        )

    return ApplicationRelaunchResult(
        application_path=application_path,
        process_id=process_id,
    )
