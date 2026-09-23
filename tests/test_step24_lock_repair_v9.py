from pathlib import Path


def _root() -> Path:
    return Path(__file__).resolve().parents[1]


def test_lock_dialog_is_ready_before_finance_window_is_hidden():
    source = (_root() / "chitlog/application.py").read_text(encoding="utf-8")
    assert "# STEP24_SESSION_LOCK_REPAIR_V9" in source
    start = source.index("# STEP24_SESSION_LOCK_BEGIN")
    end = source.index("# STEP24_SESSION_LOCK_END", start)
    block = source[start:end]
    assert block.index("lock_dialog = LoginDialog(") < block.index("window.hide()")
    assert block.index("lock_dialog.show()") < block.index("window.hide()")
    assert "app.processEvents()" in block


def test_lock_failure_restores_main_window_and_lock_close_quits_app():
    source = (_root() / "chitlog/application.py").read_text(encoding="utf-8")
    start = source.index("# STEP24_SESSION_LOCK_BEGIN")
    end = source.index("# STEP24_SESSION_LOCK_END", start)
    block = source[start:end]
    assert "except Exception:" in block
    assert "window.show()" in block
    assert "window.activateWindow()" in block
    assert "window.close()" in block
    assert "app.quit()" in block


def test_installer_uses_mixed_scope_instead_of_obsolete_user_only_assertion():
    installer = (_root() / "packaging/installer/ChitLog.nsi").read_text(encoding="utf-8")
    assert "MULTIUSER_EXECUTIONLEVEL Highest" in installer
    assert "MULTIUSER_INSTALLMODE_DEFAULT_CURRENTUSER" in installer
    assert "MULTIUSER_PAGE_INSTALLMODE" in installer
    assert "$LOCALAPPDATA\\Programs\\ChitLog" in installer
    assert "$PROGRAMFILES64\\ChitLog" in installer
