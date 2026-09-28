"""Step 7F packaging contract tests for ChitLogUpdater.exe."""
from __future__ import annotations

import importlib.util
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PACKAGING = ROOT / "packaging"


def _text(name: str) -> str:
    return (PACKAGING / name).read_text(encoding="utf-8")


def test_updater_packaging_files_exist():
    for relative in (
        "updater_entry.py",
        "ChitLogUpdater.spec",
        "verify_frozen_updater.py",
        "build_updater.ps1",
    ):
        assert (PACKAGING / relative).is_file(), relative


def test_frozen_entry_self_test_uses_public_material_only():
    source = _text("updater_entry.py")

    assert "--chitlog-updater-self-test" in source
    assert "Ed25519PublicKey" in source
    assert "Ed25519PrivateKey" not in source
    assert "private_key" not in source.lower()
    assert "load_and_verify_update_handoff" in source
    assert "execute_verified_installer" in source
    assert "wait_for_process_exit" in source


def test_frozen_entry_self_test_runs_from_source():
    path = PACKAGING / "updater_entry.py"
    spec = importlib.util.spec_from_file_location(
        "_chitlog_updater_packaging_entry",
        path,
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    assert module._frozen_self_test() == 0


def test_spec_builds_windowless_one_file_without_qt():
    source = _text("ChitLogUpdater.spec")

    # PyInstaller sets SPECPATH to the directory containing the .spec file.
    # packaging/ChitLogUpdater.spec therefore needs exactly one parent to
    # reach the repository root.
    assert "project_root = Path(SPECPATH).resolve().parent" in source
    assert ".parent.parent" not in source

    assert 'name="ChitLogUpdater"' in source
    assert "console=False" in source
    assert "a.binaries" in source
    assert "a.datas" in source
    assert "COLLECT(" not in source
    assert '"PySide6"' in source
    assert "version=str(version_file)" in source


def test_build_script_verifies_before_and_after_portable_copy():
    source = _text("build_updater.ps1")

    assert "python -m PyInstaller" in source
    assert "verify_frozen_updater.py" in source
    assert source.count("python $Verifier") == 2
    assert 'dist\\ChitLog' in source
    assert 'ChitLogUpdater.exe' in source
    assert "Copy-Item -Force $BuiltUpdater $PackagedUpdater" in source
    assert "build_windows.ps1 -SkipTests" in source


def test_build_script_runs_step7_regressions_and_security_audit():
    source = _text("build_updater.ps1")

    for name in (
        "test_auto_updater_step7_handoff.py",
        "test_auto_updater_step7_process_skeleton.py",
        "test_auto_updater_step7_installer_execution.py",
        "test_auto_updater_step7_main_handoff.py",
        "test_auto_updater_step7_relaunch.py",
        "test_auto_updater_step7_packaging.py",
    ):
        assert name in source

    assert "python -m chitlog.core.security_audit" in source


def test_verifier_requires_x64_pe_and_runs_frozen_self_test():
    source = _text("verify_frozen_updater.py")

    assert "EXPECTED_MACHINE_AMD64 = 0x8664" in source
    assert "--chitlog-updater-self-test" in source
    assert "subprocess.run(" in source
    assert "timeout=45" in source
    assert "SHA256:" in source
