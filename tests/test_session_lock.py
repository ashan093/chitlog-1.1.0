from pathlib import Path


def _project() -> Path:
    return Path(__file__).resolve().parents[1]


def test_main_window_exposes_lock_action_without_adding_a_navigation_page():
    source = (_project() / "chitlog/ui/main_window.py").read_text(encoding="utf-8")
    assert "lock_requested = Signal()" in source
    assert 'self.lock_button.setText("Lock")' in source
    assert "self.lock_button.clicked.connect(self.lock_requested.emit)" in source
    assert '("Lock",' not in source.split("NAV_ITEMS", 1)[1].split(")", 1)[0]


def test_login_dialog_supports_locked_mode_and_unlock_wording():
    source = (_project() / "chitlog/ui/login_dialog.py").read_text(encoding="utf-8")
    assert "locked: bool = False" in source
    assert '"ChitLog is locked" if self.locked else "Welcome back"' in source
    assert 'button("Unlock" if self.locked else "Login", "primary")' in source
    assert 'action = "unlock" if self.locked else "open"' in source


def test_application_wires_lock_to_existing_authentication_dialog():
    source = (_project() / "chitlog/application.py").read_text(encoding="utf-8")
    assert "# STEP24_SESSION_LOCK_BEGIN" in source
    assert "window.lock_requested.connect(_lock_current_session)" in source
    assert "window.hide()" in source
    assert "locked=True" in source
    assert "window.show()" in source
    assert "window.close()" in source
