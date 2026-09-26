"""Step 7C tests for the verified installer execution boundary."""
from __future__ import annotations

from pathlib import Path
import struct
from types import SimpleNamespace

import pytest

from chitlog.core.update_handoff import VerifiedUpdateHandoff
from chitlog.core.update_installer_execution import (
    InstallerConsentCancelledError,
    InstallerExecutionError,
    InstallerExecutionResult,
    InstallerExitCodeError,
    InstallerImageError,
    InstallerPlatformError,
    execute_verified_installer,
    verify_windows_installer_pe,
)
from chitlog.core.update_installer_staging import VerifiedInstallerArtifact
from chitlog.updater import (
    EXIT_INSTALLER_CANCELLED,
    EXIT_INSTALLER_FAILED,
    EXIT_INSTALL_SUCCEEDED,
    main,
)


def write_minimal_pe(path: Path, *, machine: int = 0x8664) -> None:
    data = bytearray(512)
    data[0:2] = b"MZ"
    pe_offset = 0x80
    struct.pack_into("<I", data, 0x3C, pe_offset)
    data[pe_offset : pe_offset + 4] = b"PE\x00\x00"
    struct.pack_into("<H", data, pe_offset + 4, machine)
    path.write_bytes(bytes(data))


def fake_verified(tmp_path: Path, *, version: str = "1.2.0"):
    installer = tmp_path / f"ChitLog-{version}-Setup.exe"
    write_minimal_pe(installer)

    artifact = VerifiedInstallerArtifact(
        path=installer.resolve(),
        version=version,
        size_bytes=installer.stat().st_size,
        sha256="0" * 64,
    )
    payload = SimpleNamespace(
        version=version,
        platform="windows",
        architecture="x64",
    )

    return VerifiedUpdateHandoff(
        handoff=SimpleNamespace(parent_pid=1234),
        payload=payload,
        decision=SimpleNamespace(update_available=True),
        installer=artifact,
        application_path=(tmp_path / "ChitLog.exe").resolve(),
        handoff_path=(tmp_path / "handoff.json").resolve(),
    )


@pytest.mark.parametrize("machine", [0x014C, 0x8664])
def test_pe_sanity_accepts_nsis_i386_and_amd64_executables(
    tmp_path,
    machine,
):
    installer = tmp_path / "ChitLog-1.2.0-Setup.exe"
    write_minimal_pe(installer, machine=machine)
    assert verify_windows_installer_pe(installer) == installer.resolve()


@pytest.mark.parametrize(
    "mutator",
    [
        lambda data: data.__setitem__(slice(0, 2), b"ZZ"),
        lambda data: struct.pack_into("<I", data, 0x3C, 0xFFFFFFF0),
        lambda data: data.__setitem__(slice(0x80, 0x84), b"NOPE"),
        lambda data: struct.pack_into("<H", data, 0x84, 0xAA64),
    ],
)
def test_pe_sanity_rejects_invalid_or_non_x64_images(tmp_path, mutator):
    installer = tmp_path / "ChitLog-1.2.0-Setup.exe"
    write_minimal_pe(installer)

    data = bytearray(installer.read_bytes())
    mutator(data)
    installer.write_bytes(bytes(data))

    with pytest.raises(InstallerImageError):
        verify_windows_installer_pe(installer)


def test_execution_rehashes_before_launch(tmp_path, monkeypatch):
    import chitlog.core.update_installer_execution as module

    verified = fake_verified(tmp_path)
    calls = []

    def final_verify(path, payload, *, max_installer_bytes):
        calls.append(("verify", Path(path), max_installer_bytes))
        return verified.installer

    def launcher(path, timeout):
        calls.append(("launch", Path(path), timeout))
        return 0

    monkeypatch.setattr(module, "verify_installer_file", final_verify)

    result = execute_verified_installer(
        verified,
        timeout_seconds=12,
        launcher=launcher,
    )

    assert isinstance(result, InstallerExecutionResult)
    assert result.exit_code == 0
    assert calls[0][0] == "verify"
    assert calls[1] == ("launch", verified.installer.path, 12.0)


def test_nonzero_installer_exit_is_fail_closed(tmp_path, monkeypatch):
    import chitlog.core.update_installer_execution as module

    verified = fake_verified(tmp_path)
    monkeypatch.setattr(
        module,
        "verify_installer_file",
        lambda *a, **k: verified.installer,
    )

    with pytest.raises(InstallerExitCodeError) as caught:
        execute_verified_installer(
            verified,
                launcher=lambda path, timeout: 5,
        )

    assert caught.value.exit_code == 5


def test_wrong_signed_platform_or_architecture_is_rejected(tmp_path, monkeypatch):
    import chitlog.core.update_installer_execution as module

    verified = fake_verified(tmp_path)
    monkeypatch.setattr(
        module,
        "verify_installer_file",
        lambda *a, **k: verified.installer,
    )

    verified.payload.platform = "linux"
    with pytest.raises(InstallerPlatformError):
        execute_verified_installer(
            verified,
                launcher=lambda path, timeout: 0,
        )

    verified.payload.platform = "windows"
    verified.payload.architecture = "x86"
    with pytest.raises(InstallerImageError):
        execute_verified_installer(
            verified,
                launcher=lambda path, timeout: 0,
        )


def test_final_verification_cannot_swap_to_another_path(tmp_path, monkeypatch):
    import chitlog.core.update_installer_execution as module

    verified = fake_verified(tmp_path)
    wrong = tmp_path / "unexpected.exe"
    write_minimal_pe(wrong)

    monkeypatch.setattr(
        module,
        "verify_installer_file",
        lambda *a, **k: VerifiedInstallerArtifact(
            path=wrong.resolve(),
            version="1.2.0",
            size_bytes=wrong.stat().st_size,
            sha256="0" * 64,
        ),
    )

    with pytest.raises(InstallerExecutionError, match="unexpected path"):
        execute_verified_installer(
            verified,
                launcher=lambda path, timeout: 0,
        )


def test_main_maps_successful_installer_result(monkeypatch, tmp_path, capsys):
    import chitlog.updater as updater
    from chitlog.core.update_application_relaunch import ApplicationRelaunchResult

    verified = fake_verified(tmp_path)
    monkeypatch.setattr(
        updater,
        "prepare_standalone_update",
        lambda path: verified,
    )
    monkeypatch.setattr(
        updater,
        "execute_verified_installer",
        lambda value: InstallerExecutionResult(
            installer_path=value.installer.path,
            exit_code=0,
        ),
    )
    monkeypatch.setattr(
        updater,
        "relaunch_updated_application",
        lambda value: ApplicationRelaunchResult(
            application_path=value.application_path,
            process_id=1234,
        ),
    )

    handoff = (tmp_path / "handoff.json").resolve()
    code = main(["--handoff", str(handoff)])
    captured = capsys.readouterr()

    assert code == EXIT_INSTALL_SUCCEEDED
    assert "completed successfully" in captured.out
    assert "restarted as process 1234" in captured.out


def test_main_maps_uac_cancel_without_reporting_success(
    monkeypatch,
    tmp_path,
    capsys,
):
    import chitlog.updater as updater

    verified = fake_verified(tmp_path)
    monkeypatch.setattr(
        updater,
        "prepare_standalone_update",
        lambda path: verified,
    )
    monkeypatch.setattr(
        updater,
        "execute_verified_installer",
        lambda value: (_ for _ in ()).throw(
            InstallerConsentCancelledError("secret")
        ),
    )

    handoff = (tmp_path / "handoff.json").resolve()
    code = main(["--handoff", str(handoff)])
    captured = capsys.readouterr()

    assert code == EXIT_INSTALLER_CANCELLED
    assert "cancelled" in captured.err.lower()
    assert "secret" not in captured.err


@pytest.mark.parametrize(
    "failure",
    [
        InstallerExecutionError("secret"),
        InstallerExitCodeError(7),
    ],
)
def test_main_maps_execution_failure_without_leaking_details(
    monkeypatch,
    tmp_path,
    capsys,
    failure,
):
    import chitlog.updater as updater

    verified = fake_verified(tmp_path)
    monkeypatch.setattr(
        updater,
        "prepare_standalone_update",
        lambda path: verified,
    )
    monkeypatch.setattr(
        updater,
        "execute_verified_installer",
        lambda value: (_ for _ in ()).throw(failure),
    )

    handoff = (tmp_path / "handoff.json").resolve()
    code = main(["--handoff", str(handoff)])
    captured = capsys.readouterr()

    assert code == EXIT_INSTALLER_FAILED
    assert "secret" not in captured.err
    assert "installer completed successfully" not in captured.err.lower()


def test_execution_source_has_fixed_windows_launch_contract():
    project = Path(__file__).resolve().parents[1]
    source = (
        project / "chitlog/core/update_installer_execution.py"
    ).read_text(encoding="utf-8")

    assert 'info.lpVerb = "runas"' in source
    assert "info.lpParameters = None" in source
    assert "verify_installer_file(" in source
    assert "verify_windows_installer_pe(" in source
    assert "_IMAGE_FILE_MACHINE_I386" in source
    assert "_IMAGE_FILE_MACHINE_AMD64" in source
    assert "WinVerifyTrust" not in source
    assert "TerminateProcess" not in source

    for forbidden in (
        "subprocess",
        "Popen",
        "os.system",
        "os.startfile",
        "shell=True",
        "cmd.exe",
        "powershell",
    ):
        assert forbidden not in source
