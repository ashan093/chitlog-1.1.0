"""Step 17 theme and Windows app-identity regression checks."""
from pathlib import Path

from chitlog.ui.theme import stylesheet


def test_time_edit_uses_chitlog_dark_theme():
    qss = stylesheet("dark")
    assert "QTimeEdit" in qss
    assert "QTimeEdit::up-button" in qss
    assert "QTimeEdit::down-button" in qss
    assert "#08273B" in qss  # dark theme field


def test_application_sets_chitlog_display_identity():
    project = Path(__file__).resolve().parents[1]
    source = (project / "chitlog/application.py").read_text(encoding="utf-8")
    assert "setApplicationDisplayName(APP_NAME)" in source
    assert "SetCurrentProcessExplicitAppUserModelID" in source
    assert '"ChitLog"' in source
    assert "ChitLog.Desktop" not in source
