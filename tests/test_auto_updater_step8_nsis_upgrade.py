"""Step 8A NSIS upgrade-foundation tests."""
from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
NSI = ROOT / "packaging" / "installer" / "ChitLog.nsi"
BUILD = ROOT / "packaging" / "build_installer.ps1"


def _nsi() -> str:
    return NSI.read_text(encoding="utf-8")


def _build() -> str:
    return BUILD.read_text(encoding="utf-8")


def test_existing_install_mode_and_directory_are_restored_from_registry():
    source = _nsi()

    assert (
        '!define MULTIUSER_INSTALLMODE_DEFAULT_REGISTRY_KEY "${APP_REG_KEY}"'
        in source
    )
    assert (
        '!define MULTIUSER_INSTALLMODE_DEFAULT_REGISTRY_VALUENAME "InstallDir"'
        in source
    )
    assert (
        '!define MULTIUSER_INSTALLMODE_INSTDIR_REGISTRY_KEY "${APP_REG_KEY}"'
        in source
    )
    assert (
        '!define MULTIUSER_INSTALLMODE_INSTDIR_REGISTRY_VALUENAME "InstallDir"'
        in source
    )


def test_fresh_install_still_defaults_to_current_user():
    source = _nsi()

    assert "!define MULTIUSER_INSTALLMODE_DEFAULT_CURRENTUSER" in source
    assert 'StrCpy $INSTDIR "$LOCALAPPDATA\\Programs\\ChitLog"' in source
    assert 'StrCpy $INSTDIR "$PROGRAMFILES64\\ChitLog"' in source


def test_installer_uses_in_place_overwrite_without_deleting_program_tree_first():
    source = _nsi()
    section = source.split('Section "ChitLog application" SEC_MAIN', 1)[1]
    section = section.split("SectionEnd", 1)[0]

    assert "SetOverwrite on" in section
    assert 'File /r "${PROJECT_ROOT}\\dist\\ChitLog\\*"' in section
    assert 'RMDir /r "$INSTDIR"' not in section


def test_success_exit_code_is_explicit_and_abort_codes_are_not_overridden():
    source = _nsi()

    assert "Function .onInstSuccess" in source
    assert "SetErrorLevel 0" in source
    assert "Function .onUserAbort" not in source
    assert "Function .onInstFailed" not in source


def test_uninstaller_only_removes_install_tree_not_user_data_locations():
    source = _nsi()
    uninstall = source.split('Section "Uninstall"', 1)[1]

    assert 'RMDir /r "$INSTDIR"' in uninstall
    assert 'RMDir /r "$LOCALAPPDATA\\ChitLog"' not in uninstall
    assert 'RMDir /r "$APPDATA\\ChitLog"' not in uninstall
    assert 'Delete "$LOCALAPPDATA\\ChitLog' not in uninstall
    assert 'Delete "$APPDATA\\ChitLog' not in uninstall


def test_installer_build_requires_and_verifies_frozen_updater():
    source = _build()

    assert (
        '$Updater = Join-Path $ProjectRoot '
        '"dist\\ChitLog\\ChitLogUpdater.exe"'
        in source
    )
    assert (
        '$UpdaterVerifier = Join-Path $ProjectRoot '
        '"packaging\\verify_frozen_updater.py"'
        in source
    )
    assert "python $UpdaterVerifier $Updater" in source
    assert "ChitLogUpdater.exe is missing" in source


def test_installer_build_detects_updater_change_during_compilation():
    source = _build()

    assert "$UpdaterHashBefore" in source
    assert "$UpdaterHashAfter" in source
    assert "$UpdaterSizeBefore" in source
    assert "$UpdaterSizeAfter" in source
    assert "changed during installer compilation" in source
    assert "Remove-Item -Force $Installer" in source


def test_build_output_records_both_installer_and_updater_hashes():
    source = _build()

    assert "CHITLOG STEP 8A NSIS UPGRADE BUILD: PASS" in source
    assert 'Write-Host "Installer SHA256: $Hash"' in source
    assert 'Write-Host "Updater SHA256:   $UpdaterHashAfter"' in source
