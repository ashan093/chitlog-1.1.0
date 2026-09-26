"""Main-app handoff and launch boundary for the standalone ChitLog updater.

The running ChitLog process must never invoke an arbitrary executable or pass
untrusted command text to a shell. This module locates the packaged
``ChitLogUpdater.exe`` beside the running application, copies that updater into
the update staging directory, verifies the copy byte-for-byte, creates the
signed Step 7A handoff, and starts only that staged updater with one internally
generated ``--handoff`` argument.

The standalone updater then independently verifies the handoff and installer
again before installation.
"""
from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
import ctypes
from ctypes import wintypes
import hashlib
import os
from pathlib import Path
import tempfile
from typing import Callable

from chitlog.core.update_config import DEFAULT_MAX_INSTALLER_BYTES
from chitlog.core.update_handoff import (
    UpdateHandoff,
    create_update_handoff,
    write_update_handoff,
)
from chitlog.core.update_installer_execution import verify_windows_installer_pe
from chitlog.core.update_installer_staging import VerifiedInstallerArtifact
from chitlog.core.update_manifest import SignedUpdateManifest
from chitlog.core.update_signature import TRUSTED_UPDATE_PUBLIC_KEYS
from chitlog.core.version import APP_VERSION, Version


UPDATER_EXECUTABLE_NAME = "ChitLogUpdater.exe"
MAX_UPDATER_EXECUTABLE_BYTES = 200 * 1024 * 1024
_COPY_CHUNK_BYTES = 1024 * 1024


class UpdaterLaunchError(RuntimeError):
    """Base class for standalone-updater preparation/launch failures."""


class UpdaterNotPackagedError(UpdaterLaunchError):
    """Raised when the packaged standalone updater cannot be found safely."""


class UpdaterStagingError(UpdaterLaunchError):
    """Raised when the trusted updater cannot be staged safely."""


class UpdaterProcessLaunchError(UpdaterLaunchError):
    """Raised when Windows refuses or fails to start the updater process."""


@dataclass(frozen=True, slots=True)
class StagedUpdaterExecutable:
    path: Path
    size_bytes: int
    sha256: str


@dataclass(frozen=True, slots=True)
class UpdaterLaunchResult:
    updater_path: Path
    handoff_path: Path
    target_version: str
    process_id: int


UpdaterProcessLauncher = Callable[[StagedUpdaterExecutable, Path], int]


def _regular_absolute_exe(path: str | Path, *, label: str) -> Path:
    candidate = Path(path)
    if not candidate.is_absolute():
        raise UpdaterNotPackagedError(f"{label} must be an absolute path.")
    if candidate.suffix.lower() != ".exe":
        raise UpdaterNotPackagedError(f"{label} must be an .exe file.")

    try:
        if candidate.is_symlink():
            raise UpdaterNotPackagedError(
                f"{label} must not be a symbolic link."
            )
        resolved = candidate.resolve(strict=True)
    except OSError as exc:
        raise UpdaterNotPackagedError(
            f"{label} could not be resolved safely."
        ) from exc

    if not resolved.is_file():
        raise UpdaterNotPackagedError(
            f"{label} must be an existing regular file."
        )
    return resolved


def resolve_packaged_updater(application_path: str | Path) -> Path:
    """Return the trusted installed updater that ships beside ChitLog.exe."""

    application = _regular_absolute_exe(
        application_path,
        label="ChitLog application executable",
    )
    updater = application.with_name(UPDATER_EXECUTABLE_NAME)

    try:
        if updater.is_symlink():
            raise UpdaterNotPackagedError(
                "Packaged ChitLog updater must not be a symbolic link."
            )
        resolved = updater.resolve(strict=True)
    except (FileNotFoundError, OSError) as exc:
        raise UpdaterNotPackagedError(
            "The packaged ChitLogUpdater.exe is not available."
        ) from exc

    if not resolved.is_file() or resolved.name != UPDATER_EXECUTABLE_NAME:
        raise UpdaterNotPackagedError(
            "The packaged ChitLog updater path is invalid."
        )
    if resolved.parent != application.parent:
        raise UpdaterNotPackagedError(
            "The packaged ChitLog updater must live beside ChitLog.exe."
        )

    # Header sanity catches broken packaging before the main app closes.
    verify_windows_installer_pe(resolved)
    return resolved


def packaged_updater_available(application_path: str | Path) -> bool:
    """Return whether a safely located packaged updater is currently present."""

    try:
        resolve_packaged_updater(application_path)
    except (UpdaterLaunchError, OSError, ValueError):
        return False
    return True


def _hash_file(path: Path) -> tuple[int, str]:
    digest = hashlib.sha256()
    total = 0
    try:
        with path.open("rb") as handle:
            while True:
                chunk = handle.read(_COPY_CHUNK_BYTES)
                if not chunk:
                    break
                total += len(chunk)
                digest.update(chunk)
    except OSError as exc:
        raise UpdaterStagingError(
            "The ChitLog updater could not be read safely."
        ) from exc
    return total, digest.hexdigest()


def _verify_staged_updater(
    staged: StagedUpdaterExecutable,
) -> StagedUpdaterExecutable:
    if not isinstance(staged, StagedUpdaterExecutable):
        raise TypeError("staged must be a StagedUpdaterExecutable.")

    path = staged.path
    try:
        if path.is_symlink():
            raise UpdaterStagingError(
                "Staged updater must not be a symbolic link."
            )
        resolved = path.resolve(strict=True)
    except OSError as exc:
        raise UpdaterStagingError(
            "Staged updater could not be resolved safely."
        ) from exc

    if not resolved.is_file():
        raise UpdaterStagingError(
            "Staged updater is not a regular file."
        )

    size, digest = _hash_file(resolved)
    if size != staged.size_bytes or digest != staged.sha256:
        raise UpdaterStagingError(
            "Staged updater changed after it was copied."
        )

    verify_windows_installer_pe(resolved)
    return StagedUpdaterExecutable(
        path=resolved,
        size_bytes=size,
        sha256=digest,
    )


def stage_packaged_updater(
    source_updater: str | Path,
    destination_directory: str | Path,
    *,
    target_version: str,
) -> StagedUpdaterExecutable:
    """Atomically copy the installed updater outside the install directory.

    Running the copied updater from the cache lets NSIS replace the installed
    ``ChitLogUpdater.exe`` during an application upgrade without fighting a
    Windows file lock held by the updater process itself.
    """

    source = _regular_absolute_exe(
        source_updater,
        label="Packaged ChitLog updater",
    )
    if source.name != UPDATER_EXECUTABLE_NAME:
        raise UpdaterStagingError(
            "Packaged updater has an unexpected filename."
        )

    verify_windows_installer_pe(source)

    version = str(Version.parse(target_version))

    try:
        initial_stat = source.stat()
    except OSError as exc:
        raise UpdaterStagingError(
            "Packaged updater metadata could not be read."
        ) from exc

    if initial_stat.st_size <= 0:
        raise UpdaterStagingError("Packaged updater is empty.")
    if initial_stat.st_size > MAX_UPDATER_EXECUTABLE_BYTES:
        raise UpdaterStagingError(
            "Packaged updater exceeds the local safety limit."
        )

    destination = Path(destination_directory)
    try:
        destination.mkdir(parents=True, exist_ok=True)
        resolved_destination = destination.resolve(strict=True)
    except OSError as exc:
        raise UpdaterStagingError(
            "Updater staging directory could not be prepared."
        ) from exc

    if not resolved_destination.is_dir():
        raise UpdaterStagingError(
            "Updater staging destination is not a directory."
        )

    final_path = resolved_destination / f"ChitLogUpdater-{version}.exe"

    try:
        descriptor, temporary_name = tempfile.mkstemp(
            prefix=f".{final_path.stem}-",
            suffix=".part",
            dir=resolved_destination,
        )
    except OSError as exc:
        raise UpdaterStagingError(
            "Temporary updater staging file could not be created."
        ) from exc

    temporary_path = Path(temporary_name)
    digest = hashlib.sha256()
    total = 0

    try:
        with os.fdopen(descriptor, "wb") as target, source.open("rb") as src:
            while True:
                chunk = src.read(_COPY_CHUNK_BYTES)
                if not chunk:
                    break
                total += len(chunk)
                if total > MAX_UPDATER_EXECUTABLE_BYTES:
                    raise UpdaterStagingError(
                        "Packaged updater exceeded the local safety limit."
                    )
                digest.update(chunk)
                target.write(chunk)

            target.flush()
            os.fsync(target.fileno())

        try:
            final_source_stat = source.stat()
        except OSError as exc:
            raise UpdaterStagingError(
                "Packaged updater metadata changed unexpectedly."
            ) from exc

        if (
            final_source_stat.st_size != initial_stat.st_size
            or final_source_stat.st_mtime_ns != initial_stat.st_mtime_ns
        ):
            raise UpdaterStagingError(
                "Packaged updater changed while it was being staged."
            )

        if total != initial_stat.st_size:
            raise UpdaterStagingError(
                "Staged updater size does not match the packaged updater."
            )

        expected_digest = digest.hexdigest()
        temp_size, temp_digest = _hash_file(temporary_path)
        if temp_size != total or temp_digest != expected_digest:
            raise UpdaterStagingError(
                "Staged updater failed the post-copy integrity check."
            )

        os.replace(temporary_path, final_path)

        staged = StagedUpdaterExecutable(
            path=final_path.resolve(strict=True),
            size_bytes=total,
            sha256=expected_digest,
        )
        return _verify_staged_updater(staged)
    except UpdaterStagingError:
        raise
    except OSError as exc:
        raise UpdaterStagingError(
            "Packaged updater could not be staged safely."
        ) from exc
    finally:
        try:
            temporary_path.unlink(missing_ok=True)
        except OSError:
            pass


def _safe_handoff_parameter(handoff_path: Path) -> str:
    text = str(handoff_path)
    if not handoff_path.is_absolute():
        raise UpdaterProcessLaunchError(
            "Updater handoff path must be absolute."
        )
    if "\x00" in text or '"' in text:
        raise UpdaterProcessLaunchError(
            "Updater handoff path contains invalid characters."
        )
    return f'--handoff "{text}"'


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


def _launch_windows_updater(
    staged_updater: StagedUpdaterExecutable,
    handoff_path: Path,
) -> int:
    """Start the exact staged updater directly, without a command shell."""

    if os.name != "nt":
        raise UpdaterProcessLaunchError(
            "Standalone updater launch is supported only on Windows."
        )

    staged = _verify_staged_updater(staged_updater)

    handoff = Path(handoff_path)
    try:
        if handoff.is_symlink():
            raise UpdaterProcessLaunchError(
                "Updater handoff must not be a symbolic link."
            )
        handoff = handoff.resolve(strict=True)
    except OSError as exc:
        raise UpdaterProcessLaunchError(
            "Updater handoff could not be resolved safely."
        ) from exc

    if not handoff.is_file() or handoff.suffix.lower() != ".json":
        raise UpdaterProcessLaunchError(
            "Updater handoff must be an existing JSON file."
        )

    parameters = _safe_handoff_parameter(handoff)

    see_mask_nocloseprocess = 0x00000040
    see_mask_noasync = 0x00000100
    sw_shownormal = 1

    shell32 = ctypes.WinDLL("shell32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

    shell_execute_ex = shell32.ShellExecuteExW
    shell_execute_ex.argtypes = [ctypes.POINTER(_ShellExecuteInfoW)]
    shell_execute_ex.restype = wintypes.BOOL

    get_process_id = kernel32.GetProcessId
    get_process_id.argtypes = [wintypes.HANDLE]
    get_process_id.restype = wintypes.DWORD

    close_handle = kernel32.CloseHandle
    close_handle.argtypes = [wintypes.HANDLE]
    close_handle.restype = wintypes.BOOL

    info = _ShellExecuteInfoW()
    info.cbSize = ctypes.sizeof(_ShellExecuteInfoW)
    info.fMask = see_mask_nocloseprocess | see_mask_noasync
    info.hwnd = None
    info.lpVerb = "open"
    info.lpFile = str(staged.path)
    info.lpParameters = parameters
    info.lpDirectory = str(staged.path.parent)
    info.nShow = sw_shownormal

    if not shell_execute_ex(ctypes.byref(info)):
        raise UpdaterProcessLaunchError(
            "Windows could not start the standalone ChitLog updater."
        )

    if not info.hProcess:
        raise UpdaterProcessLaunchError(
            "Windows did not return an updater process handle."
        )

    try:
        process_id = int(get_process_id(info.hProcess))
        if process_id <= 0:
            raise UpdaterProcessLaunchError(
                "Windows did not return a valid updater process ID."
            )
        return process_id
    finally:
        close_handle(info.hProcess)


def prepare_and_launch_updater(
    manifest: SignedUpdateManifest,
    installer: VerifiedInstallerArtifact,
    application_path: str | Path,
    destination_directory: str | Path,
    *,
    parent_pid: int,
    trusted_keys: Mapping[str, bytes] = TRUSTED_UPDATE_PUBLIC_KEYS,
    current_version: str = APP_VERSION,
    max_installer_bytes: int = DEFAULT_MAX_INSTALLER_BYTES,
    launcher: UpdaterProcessLauncher = _launch_windows_updater,
) -> UpdaterLaunchResult:
    """Create the signed handoff, stage the updater, and start it safely."""

    if not isinstance(manifest, SignedUpdateManifest):
        raise TypeError("manifest must be a SignedUpdateManifest.")
    if not isinstance(installer, VerifiedInstallerArtifact):
        raise TypeError("installer must be a VerifiedInstallerArtifact.")

    application = _regular_absolute_exe(
        application_path,
        label="ChitLog application executable",
    )
    packaged_updater = resolve_packaged_updater(application)

    staged_updater: StagedUpdaterExecutable | None = None
    handoff_path: Path | None = None
    launched = False

    try:
        staged_updater = stage_packaged_updater(
            packaged_updater,
            destination_directory,
            target_version=manifest.payload.version,
        )

        handoff: UpdateHandoff = create_update_handoff(
            manifest,
            installer,
            application,
            parent_pid=parent_pid,
            trusted_keys=trusted_keys,
            current_version=current_version,
            max_installer_bytes=max_installer_bytes,
        )
        handoff_path = write_update_handoff(
            destination_directory,
            handoff,
        )

        # Re-check the staged updater immediately before creating the process.
        staged_updater = _verify_staged_updater(staged_updater)
        process_id = int(launcher(staged_updater, handoff_path))
        if process_id <= 0:
            raise UpdaterProcessLaunchError(
                "Standalone updater returned an invalid process ID."
            )

        launched = True
        return UpdaterLaunchResult(
            updater_path=staged_updater.path,
            handoff_path=handoff_path,
            target_version=manifest.payload.version,
            process_id=process_id,
        )
    finally:
        if not launched:
            if handoff_path is not None:
                try:
                    handoff_path.unlink(missing_ok=True)
                except OSError:
                    pass
            if staged_updater is not None:
                try:
                    staged_updater.path.unlink(missing_ok=True)
                except OSError:
                    pass
