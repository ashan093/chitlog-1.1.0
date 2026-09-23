from pathlib import Path


def _root() -> Path:
    return Path(__file__).resolve().parents[1]


def test_installer_supports_current_user_and_all_users_modes():
    source = (_root() / "packaging/installer/ChitLog.nsi").read_text(encoding="utf-8")
    assert "MULTIUSER_EXECUTIONLEVEL Highest" in source
    assert "MULTIUSER_INSTALLMODE_DEFAULT_CURRENTUSER" in source
    assert "MULTIUSER_PAGE_INSTALLMODE" in source
    assert 'Install for me only (recommended)' in source
    assert 'Install for all users (administrator required)' in source
    assert '$LOCALAPPDATA\\Programs\\ChitLog' in source
    assert '$PROGRAMFILES64\\ChitLog' in source
    assert 'WriteRegStr SHCTX' in source
    assert 'DeleteRegKey SHCTX' in source


def test_installer_keeps_eula_and_version_metadata():
    source = (_root() / "packaging/installer/ChitLog.nsi").read_text(encoding="utf-8")
    assert 'MUI_PAGE_LICENSE "${PROJECT_ROOT}\\EULA.txt"' in source
    assert 'MUI_LICENSEPAGE_CHECKBOX' in source
    assert 'VIAddVersionKey /LANG=1033 "FileVersion" "1.0.0"' in source
    assert 'Icon "${PROJECT_ROOT}\\assets\\chit.ico"' in source


def test_application_has_global_window_icon_after_apply_script():
    source = (_root() / "chitlog/application.py").read_text(encoding="utf-8")
    assert "# STEP24_GLOBAL_WINDOW_ICON_HELPER_BEGIN" in source
    assert "app.setWindowIcon(QIcon(str(icon_path)))" in source
    assert "_apply_chitlog_window_icon(" in source
