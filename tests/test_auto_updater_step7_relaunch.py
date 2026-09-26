"""Step 7E tests for post-install ChitLog relaunch."""
from __future__ import annotations

from pathlib import Path
import struct
from types import SimpleNamespace

import pytest

from chitlog.core.update_application_relaunch import (
    ApplicationRelaunchError,
    ApplicationRelaunchLaunchError,
    ApplicationRelaunchPathError,
    ApplicationRelaunchResult,
    relaunch_updated_application,
    validate_relaunch_application,
)
from chitlog.core.update_handoff import VerifiedUpdateHandoff
from chitlog.core.update_installer_staging import VerifiedInstallerArtifact
from chitlog.updater import (
    EXIT_INSTALLER_CANCELLED,
    EXIT_INSTALLER_FAILED,
    EXIT_RELAUNCH_FAILED,
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


def fake_verified(tmp_path: Path):
    app = tmp_path / "ChitLog.exe"
    write_minimal_pe(app)
    installer = tmp_path / "ChitLog-1.2.0-Setup.exe"
    write_minimal_pe(installer, machine=0x014C)
    artifact = VerifiedInstallerArtifact(
        path=installer.resolve(),
        version="1.2.0",
        size_bytes=installer.stat().st_size,
        sha256="0" * 64,
    )
    return VerifiedUpdateHandoff(
        handoff=SimpleNamespace(parent_pid=1234),
        payload=SimpleNamespace(
            version="1.2.0",
            platform="windows",
            architecture="x64",
        ),
        decision=SimpleNamespace(update_available=True),
        installer=artifact,
        application_path=app.resolve(),
        handoff_path=(tmp_path / "handoff.json").resolve(),
    )


def test_validate_relaunch_accepts_exact_chitlog_pe(tmp_path):
    verified = fake_verified(tmp_path)
    assert validate_relaunch_application(
        verified.application_path
    ) == verified.application_path


def test_validate_relaunch_rejects_wrong_filename(tmp_path):
    other = tmp_path / "Other.exe"
    write_minimal_pe(other)
    with pytest.raises(ApplicationRelaunchPathError, match="ChitLog.exe"):
        validate_relaunch_application(other)


def test_validate_relaunch_rejects_missing_file(tmp_path):
    with pytest.raises(ApplicationRelaunchPathError):
        validate_relaunch_application(tmp_path / "ChitLog.exe")


def test_relaunch_passes_only_validated_path_to_launcher(tmp_path):
    verified = fake_verified(tmp_path)
    calls = []

    result = relaunch_updated_application(
        verified,
        launcher=lambda path: calls.append(path) or 9876,
    )

    assert isinstance(result, ApplicationRelaunchResult)
    assert result.application_path == verified.application_path
    assert result.process_id == 9876
    assert calls == [verified.application_path]


def test_relaunch_rejects_nonpositive_process_id(tmp_path):
    verified = fake_verified(tmp_path)
    with pytest.raises(ApplicationRelaunchLaunchError, match="process ID"):
        relaunch_updated_application(
            verified,
            launcher=lambda path: 0,
        )


def test_main_does_not_relaunch_when_installer_fails(monkeypatch, tmp_path):
    import chitlog.updater as updater
    from chitlog.core.update_installer_execution import InstallerExecutionError

    verified = fake_verified(tmp_path)
    relaunched = []
    monkeypatch.setattr(updater, "prepare_standalone_update", lambda path: verified)
    monkeypatch.setattr(
        updater,
        "execute_verified_installer",
        lambda value: (_ for _ in ()).throw(InstallerExecutionError("secret")),
    )
    monkeypatch.setattr(
        updater,
        "relaunch_updated_application",
        lambda value: relaunched.append(value),
    )

    code = main(["--handoff", str((tmp_path / "handoff.json").resolve())])
    assert code == EXIT_INSTALLER_FAILED
    assert relaunched == []


def test_main_does_not_relaunch_when_install_cancelled(monkeypatch, tmp_path):
    import chitlog.updater as updater
    from chitlog.core.update_installer_execution import InstallerConsentCancelledError

    verified = fake_verified(tmp_path)
    relaunched = []
    monkeypatch.setattr(updater, "prepare_standalone_update", lambda path: verified)
    monkeypatch.setattr(
        updater,
        "execute_verified_installer",
        lambda value: (_ for _ in ()).throw(InstallerConsentCancelledError("cancel")),
    )
    monkeypatch.setattr(
        updater,
        "relaunch_updated_application",
        lambda value: relaunched.append(value),
    )

    code = main(["--handoff", str((tmp_path / "handoff.json").resolve())])
    assert code == EXIT_INSTALLER_CANCELLED
    assert relaunched == []


def test_main_reports_install_success_even_if_relaunch_fails(
    monkeypatch,
    tmp_path,
    capsys,
):
    import chitlog.updater as updater
    from chitlog.core.update_installer_execution import InstallerExecutionResult

    verified = fake_verified(tmp_path)
    monkeypatch.setattr(updater, "prepare_standalone_update", lambda path: verified)
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
        lambda value: (_ for _ in ()).throw(ApplicationRelaunchError("secret")),
    )

    code = main(["--handoff", str((tmp_path / "handoff.json").resolve())])
    captured = capsys.readouterr()

    assert code == EXIT_RELAUNCH_FAILED
    assert "installed successfully" in captured.err
    assert "Start ChitLog manually" in captured.err
    assert "secret" not in captured.err


def test_relaunch_source_uses_exact_createprocess_contract():
    project = Path(__file__).resolve().parents[1]
    source = (
        project / "chitlog/core/update_application_relaunch.py"
    ).read_text(encoding="utf-8")

    assert "CreateProcessW" in source
    assert "str(application_path)" in source
    assert "lpCommandLine is NULL" in source
    assert "TerminateProcess" not in source

    for forbidden in (
        "subprocess",
        "Popen",
        "os.system",
        "os.startfile",
        "ShellExecute",
        "shell=True",
        "cmd.exe",
        "powershell",
    ):
        assert forbidden not in source
