"""Safe process-exit waiting for the standalone ChitLog updater.

The updater must not touch the installed application while ChitLog is still
running. This module only observes a process and waits for it to exit. It does
not terminate processes and does not launch anything.
"""
from __future__ import annotations

import ctypes
from ctypes import wintypes
import os
from pathlib import Path
import time


DEFAULT_PARENT_EXIT_TIMEOUT_SECONDS = 300.0
MAX_PARENT_EXIT_TIMEOUT_SECONDS = 3600.0


class UpdateProcessWaitError(RuntimeError):
    """Base class for safe parent-process wait failures."""


class UpdateProcessTimeoutError(UpdateProcessWaitError):
    """Raised when ChitLog does not exit within the allowed time."""


class UpdateProcessIdentityError(UpdateProcessWaitError):
    """Raised when the updater cannot identify the originating process."""


def _validate_pid(parent_pid: int) -> int:
    if (
        isinstance(parent_pid, bool)
        or not isinstance(parent_pid, int)
        or parent_pid <= 0
        or parent_pid > 0xFFFFFFFF
    ):
        raise ValueError(
            "parent_pid must be a positive 32-bit process ID."
        )

    if parent_pid == os.getpid():
        raise UpdateProcessWaitError(
            "Standalone updater cannot wait for its own process."
        )

    return parent_pid


def _validate_timeout(timeout_seconds: float) -> float:
    if isinstance(timeout_seconds, bool) or not isinstance(
        timeout_seconds,
        (int, float),
    ):
        raise TypeError("timeout_seconds must be a number.")

    value = float(timeout_seconds)
    if value <= 0 or value > MAX_PARENT_EXIT_TIMEOUT_SECONDS:
        raise ValueError(
            "timeout_seconds is outside the allowed updater wait range."
        )
    return value


def _resolve_windows_process_image(parent_pid: int) -> Path:
    process_query_limited_information = 0x1000
    error_invalid_parameter = 87
    max_path_chars = 32768

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

    open_process = kernel32.OpenProcess
    open_process.argtypes = [
        wintypes.DWORD,
        wintypes.BOOL,
        wintypes.DWORD,
    ]
    open_process.restype = wintypes.HANDLE

    query_full_process_image_name = kernel32.QueryFullProcessImageNameW
    query_full_process_image_name.argtypes = [
        wintypes.HANDLE,
        wintypes.DWORD,
        wintypes.LPWSTR,
        ctypes.POINTER(wintypes.DWORD),
    ]
    query_full_process_image_name.restype = wintypes.BOOL

    close_handle = kernel32.CloseHandle
    close_handle.argtypes = [wintypes.HANDLE]
    close_handle.restype = wintypes.BOOL

    handle = open_process(
        process_query_limited_information,
        False,
        parent_pid,
    )
    if not handle:
        error = ctypes.get_last_error()
        if error == error_invalid_parameter:
            raise UpdateProcessIdentityError(
                "The originating ChitLog process exited before it could be identified."
            )
        raise UpdateProcessIdentityError(
            "Standalone updater could not identify the originating ChitLog process."
        )

    try:
        buffer = ctypes.create_unicode_buffer(max_path_chars)
        size = wintypes.DWORD(max_path_chars)
        if not query_full_process_image_name(
            handle,
            0,
            buffer,
            ctypes.byref(size),
        ):
            raise UpdateProcessIdentityError(
                "Windows could not read the originating ChitLog executable path."
            )

        value = buffer.value
        if not value:
            raise UpdateProcessIdentityError(
                "Windows returned an empty originating executable path."
            )

        try:
            return Path(value).resolve(strict=True)
        except OSError as exc:
            raise UpdateProcessIdentityError(
                "The originating ChitLog executable path could not be resolved."
            ) from exc
    finally:
        close_handle(handle)


def _resolve_portable_process_image(parent_pid: int) -> Path:
    """Development/test fallback for hosts with /proc."""

    if os.name != "posix" or not Path("/proc").is_dir():
        raise UpdateProcessIdentityError(
            "Process-image lookup is supported only on Windows in packaged ChitLog."
        )

    link = Path(f"/proc/{parent_pid}/exe")
    try:
        return link.resolve(strict=True)
    except OSError as exc:
        raise UpdateProcessIdentityError(
            "The originating process image could not be resolved."
        ) from exc


def resolve_process_image_path(parent_pid: int) -> Path:
    """Return the OS-reported executable path for the originating process."""

    pid = _validate_pid(parent_pid)
    if os.name == "nt":
        return _resolve_windows_process_image(pid)
    return _resolve_portable_process_image(pid)


def _wait_windows(parent_pid: int, timeout_seconds: float) -> None:
    synchronize = 0x00100000
    wait_object_0 = 0x00000000
    wait_timeout = 0x00000102
    wait_failed = 0xFFFFFFFF
    error_invalid_parameter = 87

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

    open_process = kernel32.OpenProcess
    open_process.argtypes = [
        wintypes.DWORD,
        wintypes.BOOL,
        wintypes.DWORD,
    ]
    open_process.restype = wintypes.HANDLE

    wait_for_single_object = kernel32.WaitForSingleObject
    wait_for_single_object.argtypes = [
        wintypes.HANDLE,
        wintypes.DWORD,
    ]
    wait_for_single_object.restype = wintypes.DWORD

    close_handle = kernel32.CloseHandle
    close_handle.argtypes = [wintypes.HANDLE]
    close_handle.restype = wintypes.BOOL

    handle = open_process(synchronize, False, parent_pid)
    if not handle:
        error = ctypes.get_last_error()
        if error == error_invalid_parameter:
            # The process already exited before the updater opened its handle.
            return
        raise UpdateProcessWaitError(
            "Standalone updater could not safely observe the ChitLog process."
        )

    try:
        timeout_ms = int(timeout_seconds * 1000)
        result = wait_for_single_object(handle, timeout_ms)

        if result == wait_object_0:
            return
        if result == wait_timeout:
            raise UpdateProcessTimeoutError(
                "ChitLog did not exit before the updater wait timeout."
            )
        if result == wait_failed:
            raise UpdateProcessWaitError(
                "Windows failed while waiting for the ChitLog process."
            )

        raise UpdateProcessWaitError(
            "Windows returned an unexpected process-wait result."
        )
    finally:
        close_handle(handle)


def _linux_process_is_zombie(parent_pid: int) -> bool:
    """Return True for a Linux zombie so test/dev waiting can finish."""

    stat_path = Path(f"/proc/{parent_pid}/stat")
    try:
        text = stat_path.read_text(encoding="utf-8")
    except (FileNotFoundError, OSError):
        return False

    try:
        state = text.rsplit(")", 1)[1].strip().split()[0]
    except (IndexError, ValueError):
        return False

    return state == "Z"


def _portable_process_exists(parent_pid: int) -> bool:
    if os.name == "posix" and Path("/proc").is_dir():
        if _linux_process_is_zombie(parent_pid):
            return False

    try:
        os.kill(parent_pid, 0)
    except (ProcessLookupError, OverflowError):
        return False
    except PermissionError:
        return True
    except OSError as exc:
        raise UpdateProcessWaitError(
            "Could not safely observe the ChitLog process."
        ) from exc
    else:
        return True


def _wait_portable(parent_pid: int, timeout_seconds: float) -> None:
    """Test/development fallback; packaged ChitLog targets Windows."""

    deadline = time.monotonic() + timeout_seconds
    while _portable_process_exists(parent_pid):
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise UpdateProcessTimeoutError(
                "ChitLog did not exit before the updater wait timeout."
            )
        time.sleep(min(0.05, remaining))


def wait_for_process_exit(
    parent_pid: int,
    *,
    timeout_seconds: float = DEFAULT_PARENT_EXIT_TIMEOUT_SECONDS,
) -> None:
    """Wait for ChitLog to exit without terminating or modifying it."""

    pid = _validate_pid(parent_pid)
    timeout = _validate_timeout(timeout_seconds)

    if os.name == "nt":
        _wait_windows(pid, timeout)
    else:
        _wait_portable(pid, timeout)
