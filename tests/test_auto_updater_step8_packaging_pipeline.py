from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
BUILD_WINDOWS = PROJECT_ROOT / "packaging" / "build_windows.ps1"
BUILD_UPDATER = PROJECT_ROOT / "packaging" / "build_updater.ps1"
BUILD_INSTALLER = PROJECT_ROOT / "packaging" / "build_installer.ps1"


def _text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_normal_windows_pipeline_invokes_standalone_updater_build_once() -> None:
    text = _text(BUILD_WINDOWS)
    assert text.count('packaging\\build_updater.ps1') == 1
    assert '$UpdaterBuildScript = Join-Path $ProjectRoot "packaging\\build_updater.ps1"' in text
    assert '& $UpdaterBuildScript' in text


def test_pipeline_fails_closed_if_updater_build_script_or_output_is_missing() -> None:
    text = _text(BUILD_WINDOWS)
    assert 'Test-Path -LiteralPath $UpdaterBuildScript' in text
    assert 'Standalone updater build script was not found:' in text
    assert '$UpdaterExe = Join-Path $DistDir "ChitLogUpdater.exe"' in text
    assert 'Test-Path -LiteralPath $UpdaterExe' in text
    assert 'Standalone updater build completed without producing:' in text


def test_updater_is_built_after_license_collection_and_before_release_verification() -> None:
    text = _text(BUILD_WINDOWS)
    license_pos = text.index('python packaging\\collect_licenses.py')
    updater_pos = text.index('& $UpdaterBuildScript')
    release_verify_pos = text.index('python packaging\\verify_release.py')
    archive_pos = text.rindex('\nNew-PortableArchive\n')
    assert license_pos < updater_pos < release_verify_pos < archive_pos


def test_existing_one_folder_verification_and_licensing_steps_are_preserved() -> None:
    text = _text(BUILD_WINDOWS)
    required = (
        'EULA.txt',
        'THIRD_PARTY_NOTICES.txt',
        'QT_LGPL_COMPLIANCE.txt',
        'python packaging\\collect_licenses.py',
        'python packaging\\verify_release.py',
        'New-PortableArchive',
    )
    for marker in required:
        assert marker in text


def test_existing_updater_builder_still_owns_pyinstaller_and_frozen_verification() -> None:
    text = _text(BUILD_UPDATER)
    assert 'ChitLogUpdater.spec' in text
    assert 'verify_frozen_updater.py' in text
    assert 'ChitLogUpdater.exe' in text


def test_nsis_builder_still_reverifies_the_packaged_updater() -> None:
    text = _text(BUILD_INSTALLER)
    assert 'verify_frozen_updater.py' in text
    assert 'ChitLogUpdater.exe' in text
    assert 'SHA256' in text
