"""Verified Windows installer execution boundary for ChitLog.

Only a VerifiedUpdateHandoff produced by the signed standalone-updater
pipeline may reach this module. The installer is re-hashed immediately before
execution, receives no user-controlled command-line parameters, and is started
through Windows with a fixed ``runas`` verb so normal UAC consent is preserved.

Release authenticity is established by the Ed25519-signed manifest plus the
exact installer SHA-256. Mandatory Authenticode is intentionally deferred until
ChitLog has a production code-signing certificate and signing workflow.

This module never terminates the installer process.
"""
from __future__ import annotations

import ctypes
from ctypes import wintypes
from dataclasses import dataclass
import os
from pathlib import Path
import struct
from typing import Callable

from chitlog.core.update_config import DEFAULT_MAX_INSTALLER_BYTES
from chitlog.core.update_handoff import VerifiedUpdateHandoff
from chitlog.core.update_installer_staging import verify_installer_file


DEFAULT_INSTALLER_TIMEOUT_SECONDS = 60 * 60
MAX_INSTALLER_TIMEOUT_SECONDS = 4 * 60 * 60
_IMAGE_FILE_MACHINE_I386 = 0x014C
_IMAGE_FILE_MACHINE_AMD64 = 0x8664
_ALLOWED_INSTALLER_MACHINES = frozenset(
    {
        _IMAGE_FILE_MACHINE_I386,
        _IMAGE_FILE_MACHINE_AMD64,
    }
)


class InstallerExecutionError(RuntimeError):
    """Base class for fail-closed installer execution errors."""


class InstallerPlatformError(InstallerExecutionError):
    """Raised when the signed release is not supported by this updater."""


class InstallerImageError(InstallerExecutionError):
    """Raised when the verified file is not a plausible Windows x64 PE."""


class InstallerLaunchError(InstallerExecutionError):
    """Raised when Windows refuses or fails to launch the installer."""


class InstallerConsentCancelledError(InstallerLaunchError):
    """Raised when the user cancels the Windows elevation prompt."""


class InstallerExecutionTimeoutError(InstallerExecutionError):
    """Raised when the installer remains open beyond the bounded wait."""


class InstallerExitCodeError(InstallerExecutionError):
    """Raised when the installer exits with a non-zero status."""

    def __init__(self, exit_code: int) -> None:
        self.exit_code = int(exit_code)
        super().__init__(
            f"ChitLog installer exited with status {self.exit_code}."
        )


@dataclass(frozen=True, slots=True)
class InstallerExecutionResult:
    installer_path: Path
    exit_code: int


InstallerLauncher = Callable[[Path, float], int]


def _validate_timeout(timeout_seconds: float) -> float:
    if isinstance(timeout_seconds, bool) or not isinstance(
        timeout_seconds,
        (int, float),
    ):
        raise TypeError("timeout_seconds must be numeric.")

    value = float(timeout_seconds)
    if value <= 0 or value > MAX_INSTALLER_TIMEOUT_SECONDS:
        raise ValueError(
            "timeout_seconds is outside the allowed installer range."
        )
    return value


def verify_windows_installer_pe(path: str | Path) -> Path:
    """Apply a small Windows PE sanity check after cryptographic verification.

    NSIS commonly uses a 32-bit bootstrap executable even when the packaged
    application itself is x64, so both i386 and AMD64 PE machine types are
    accepted here. The signed manifest still controls ChitLog's target
    platform/architecture policy.
    """

    candidate = Path(path)
    try:
        if candidate.is_symlink():
            raise InstallerImageError(
                "Verified installer must not be a symbolic link."
            )
        resolved = candidate.resolve(strict=True)
    except OSError as exc:
        raise InstallerImageError(
            "Verified installer path could not be resolved."
        ) from exc

    if not resolved.is_file() or resolved.suffix.lower() != ".exe":
        raise InstallerImageError(
            "Verified installer must be an existing .exe file."
        )

    try:
        size = resolved.stat().st_size
        if size < 70:
            raise InstallerImageError(
                "Verified installer is too small to be a Windows executable."
            )

        with resolved.open("rb") as handle:
            dos_header = handle.read(64)
            if len(dos_header) != 64 or dos_header[:2] != b"MZ":
                raise InstallerImageError(
                    "Verified installer has no valid DOS/PE header."
                )

            pe_offset = struct.unpack_from("<I", dos_header, 0x3C)[0]
            if pe_offset < 64 or pe_offset > size - 6:
                raise InstallerImageError(
                    "Verified installer has an invalid PE header offset."
                )

            handle.seek(pe_offset)
            pe_header = handle.read(6)
    except InstallerImageError:
        raise
    except OSError as exc:
        raise InstallerImageError(
            "Verified installer could not be inspected safely."
        ) from exc

    if len(pe_header) != 6 or pe_header[:4] != b"PE\x00\x00":
        raise InstallerImageError(
            "Verified installer has no valid PE signature."
        )

    machine = struct.unpack_from("<H", pe_header, 4)[0]
    if machine not in _ALLOWED_INSTALLER_MACHINES:
        raise InstallerImageError(
            "Verified installer uses an unsupported Windows PE machine type."
        )

    return resolved


class _ShellExecuteInfoW(ctypes.Structure):
    _fields_ = [
        ("cbSize", wintypes.DWORD),
        ("fMask", wintypes.ULONG),
        ("hwnd", wintypes.HWND),
        ("lpVerb", wintypes.LPCWSTR),
        ("lpFile", wintypes.LPCWSTR),
        ("lpParameters", wintypes.LPCWSTR),
        ("lpDirectory", wintypes.LPCWSTR),
        ("nShow", ctypes.c_int),
        ("hInstApp", wintypes.HINSTANCE),
        ("lpIDList", wintypes.LPVOID),
        ("lpClass", wintypes.LPCWSTR),
        ("hkeyClass", wintypes.HKEY),
        ("dwHotKey", wintypes.DWORD),
        ("hIconOrMonitor", wintypes.HANDLE),
        ("hProcess", wintypes.HANDLE),
    ]


def _launch_windows_installer(
    installer_path: Path,
    timeout_seconds: float,
) -> int:
    """Launch one exact verified installer and wait without terminating it."""

    if os.name != "nt":
        raise InstallerPlatformError(
            "Installer execution is supported only on Windows."
        )

    see_mask_nocloseprocess = 0x00000040
    see_mask_noasync = 0x00000100
    sw_shownormal = 1
    wait_object_0 = 0x00000000
    wait_timeout = 0x00000102
    wait_failed = 0xFFFFFFFF
    error_cancelled = 1223

    shell32 = ctypes.WinDLL("shell32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

    shell_execute_ex = shell32.ShellExecuteExW
    shell_execute_ex.argtypes = [ctypes.POINTER(_ShellExecuteInfoW)]
    shell_execute_ex.restype = wintypes.BOOL

    wait_for_single_object = kernel32.WaitForSingleObject
    wait_for_single_object.argtypes = [wintypes.HANDLE, wintypes.DWORD]
    wait_for_single_object.restype = wintypes.DWORD

    get_exit_code_process = kernel32.GetExitCodeProcess
    get_exit_code_process.argtypes = [
        wintypes.HANDLE,
        ctypes.POINTER(wintypes.DWORD),
    ]
    get_exit_code_process.restype = wintypes.BOOL

    close_handle = kernel32.CloseHandle
    close_handle.argtypes = [wintypes.HANDLE]
    close_handle.restype = wintypes.BOOL

    info = _ShellExecuteInfoW()
    info.cbSize = ctypes.sizeof(_ShellExecuteInfoW)
    info.fMask = see_mask_nocloseprocess | see_mask_noasync
    info.hwnd = None
    info.lpVerb = "runas"
    info.lpFile = str(installer_path)
    info.lpParameters = None
    info.lpDirectory = str(installer_path.parent)
    info.nShow = sw_shownormal

    if not shell_execute_ex(ctypes.byref(info)):
        error = ctypes.get_last_error()
        if error == error_cancelled:
            raise InstallerConsentCancelledError(
                "Windows elevation was cancelled by the user."
            )
        raise InstallerLaunchError(
            "Windows could not start the verified ChitLog installer."
        )

    if not info.hProcess:
        raise InstallerLaunchError(
            "Windows did not return an installer process handle."
        )

    try:
        timeout_ms = int(timeout_seconds * 1000)
        wait_result = wait_for_single_object(info.hProcess, timeout_ms)

        if wait_result == wait_timeout:
            raise InstallerExecutionTimeoutError(
                "The ChitLog installer exceeded the updater wait timeout."
            )
        if wait_result == wait_failed:
            raise InstallerLaunchError(
                "Windows failed while waiting for the ChitLog installer."
            )
        if wait_result != wait_object_0:
            raise InstallerLaunchError(
                "Windows returned an unexpected installer wait result."
            )

        exit_code = wintypes.DWORD()
        if not get_exit_code_process(
            info.hProcess,
            ctypes.byref(exit_code),
        ):
            raise InstallerLaunchError(
                "Windows could not read the installer exit status."
            )
        return int(exit_code.value)
    finally:
        close_handle(info.hProcess)


def execute_verified_installer(
    verified: VerifiedUpdateHandoff,
    *,
    timeout_seconds: float = DEFAULT_INSTALLER_TIMEOUT_SECONDS,
    max_installer_bytes: int = DEFAULT_MAX_INSTALLER_BYTES,
    launcher: InstallerLauncher = _launch_windows_installer,
) -> InstallerExecutionResult:
    """Re-verify and execute exactly one signed/staged ChitLog installer."""

    if not isinstance(verified, VerifiedUpdateHandoff):
        raise TypeError("verified must be a VerifiedUpdateHandoff.")

    timeout = _validate_timeout(timeout_seconds)

    artifact = verify_installer_file(
        verified.installer.path,
        verified.payload,
        max_installer_bytes=max_installer_bytes,
    )

    if artifact.path.resolve(strict=True) != verified.installer.path.resolve(
        strict=True
    ):
        raise InstallerExecutionError(
            "Final installer verification resolved to an unexpected path."
        )

    expected_name = f"ChitLog-{verified.payload.version}-Setup.exe"
    if artifact.path.name != expected_name:
        raise InstallerExecutionError(
            "Verified installer filename does not match the signed release."
        )

    if verified.payload.platform != "windows":
        raise InstallerPlatformError(
            "Signed release is not a Windows installer."
        )
    if verified.payload.architecture != "x64":
        raise InstallerImageError(
            "Signed release is not the supported x64 architecture."
        )

    pe_path = verify_windows_installer_pe(artifact.path)
    exit_code = int(launcher(pe_path, timeout))

    if exit_code != 0:
        raise InstallerExitCodeError(exit_code)

    return InstallerExecutionResult(
        installer_path=pe_path,
        exit_code=exit_code,
    )
