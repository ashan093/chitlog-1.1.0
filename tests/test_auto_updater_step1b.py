"""Step 1B regression checks for centralized ChitLog version wiring."""
from pathlib import Path

import chitlog.core.config as legacy_config
from chitlog.core.version import APP_VERSION


ROOT = Path(__file__).resolve().parents[1]


def read(relative: str) -> str:
    return (ROOT / relative).read_text(encoding="utf-8")


def test_legacy_config_reexports_the_central_app_version():
    config = read("chitlog/core/config.py")
    assert legacy_config.APP_VERSION == APP_VERSION
    assert "from chitlog.core.version import APP_VERSION" in config
    assert 'APP_VERSION = "' not in config


def test_runtime_consumers_still_receive_the_central_version():
    application = read("chitlog/application.py")
    settings = read("chitlog/ui/pages/settings.py")
    assert "from chitlog.core.config import APP_NAME, APP_VERSION" in application
    assert "app.setApplicationVersion(APP_VERSION)" in application
    assert "from chitlog.core.config import APP_NAME, APP_VERSION" in settings
    assert 'info_grid.addRow("Version", QLabel(APP_VERSION))' in settings


def test_nsis_metadata_matches_the_central_version():
    source = read("packaging/installer/ChitLog.nsi")
    assert f'!define APP_VERSION "{APP_VERSION}"' in source
    assert f'VIProductVersion "{APP_VERSION}.0"' in source
    assert f'VIAddVersionKey /LANG=1033 "ProductVersion" "{APP_VERSION}"' in source
    assert f'VIAddVersionKey /LANG=1033 "FileVersion" "{APP_VERSION}"' in source


def test_packaging_artifact_names_match_the_central_version():
    installer = read("packaging/build_installer.ps1")
    windows = read("packaging/build_windows.ps1")
    finalize = read("packaging/finalize_portable.ps1")
    assert f"ChitLog-{APP_VERSION}-Setup.exe" in installer
    assert f"ChitLog-{APP_VERSION}-Setup.sha256.txt" in installer
    assert f"ChitLog-{APP_VERSION}-windows-x64-portable.zip" in windows
    assert f"ChitLog-{APP_VERSION}-windows-x64-portable.sha256.txt" in windows
    assert f"ChitLog-{APP_VERSION}-windows-x64-portable.zip" in finalize
    assert f"ChitLog-{APP_VERSION}-windows-x64-portable.sha256.txt" in finalize


def test_windows_version_info_matches_the_central_version():
    source = read("packaging/version_info.txt")
    assert f"StringStruct('FileVersion', '{APP_VERSION}')" in source
    assert f"StringStruct('ProductVersion', '{APP_VERSION}')" in source


def test_release_notices_match_the_central_version():
    qt_notice = read("QT_LGPL_COMPLIANCE.txt")
    third_party = read("THIRD_PARTY_NOTICES.txt")
    assert f"Release: ChitLog {APP_VERSION}" in qt_notice
    assert f"Release: ChitLog {APP_VERSION}" in third_party


def test_packaging_source_is_not_blanket_ignored():
    ignore = read(".gitignore").splitlines()
    assert "packaging/" not in ignore
    assert "/installer/" in ignore
    assert "/installers/" in ignore


def test_packaging_sources_are_utf8_without_bom_or_mojibake():
    packaging_files = [
        "packaging/build_installer.ps1",
        "packaging/build_windows.ps1",
        "packaging/ChitLog.spec",
        "packaging/collect_licenses.py",
        "packaging/finalize_portable.ps1",
        "packaging/STEP24.md",
        "packaging/verify_release.py",
        "packaging/version_info.txt",
        "packaging/installer/ChitLog.nsi",
    ]
    for relative in packaging_files:
        raw = (ROOT / relative).read_bytes()
        assert not raw.startswith(b"\xef\xbb\xbf"), relative
        text = raw.decode("utf-8")
        assert "Â©" not in text, relative
        assert "Ã" not in text, relative
