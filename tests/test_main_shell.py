"""Offscreen checks for Step 6 navigation and responsive shell behavior."""
import os
from pathlib import Path
import subprocess
import sys


def run_offscreen(code: str):
    project = Path(__file__).resolve().parents[1]
    result = subprocess.run(
        [sys.executable, "-c", code],
        cwd=project,
        env=dict(os.environ, QT_QPA_PLATFORM="offscreen"),
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, result.stderr


def test_shell_contains_all_top_level_pages_and_navigates():
    code = r'''
from PySide6.QtWidgets import QApplication
from chitlog.ui.main_window import create_window
app=QApplication([])
w=create_window()
w.show(); app.processEvents()
expected=['Dashboard','Transactions','Budget','Liabilities','Workers','Reports','Settings']
assert list(w.nav_buttons) == expected
assert list(w.page_widgets) == expected
assert w.current_page_name == 'Dashboard'
for name in expected:
    w.nav_buttons[name].click(); app.processEvents()
    assert w.current_page_name == name
    assert w.page_title.text() == name
w.close()
'''
    run_offscreen(code)


def test_sidebar_collapses_to_icons_without_losing_navigation():
    code = r'''
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication
from chitlog.ui.main_window import create_window
app=QApplication([])
w=create_window()
w.show(); app.processEvents()
assert not w.sidebar_collapsed and w.sidebar.width() == w.EXPANDED_SIDEBAR_WIDTH
w.toggle_sidebar(); app.processEvents()
assert w.sidebar_collapsed and w.sidebar.width() == w.COLLAPSED_SIDEBAR_WIDTH
for name, nav in w.nav_buttons.items():
    assert not nav.icon().isNull()
    assert nav.toolButtonStyle() == Qt.ToolButtonStyle.ToolButtonIconOnly
    assert nav.toolTip() == name
w.nav_buttons['Workers'].click(); app.processEvents()
assert w.current_page_name == 'Workers'
w.toggle_sidebar(); app.processEvents()
assert not w.sidebar_collapsed
assert w.nav_buttons['Workers'].toolButtonStyle() == Qt.ToolButtonStyle.ToolButtonTextBesideIcon
w.close()
'''
    run_offscreen(code)


def test_window_can_resize_smaller_and_larger_without_content_forcing_geometry():
    code = r'''
from PySide6.QtWidgets import QApplication
from chitlog.ui.main_window import create_window
app=QApplication([])
w=create_window()
w.show(); app.processEvents()
w.resize(920, 580); app.processEvents()
assert w.width() == 920 and w.height() == 580
w.resize(1280, 720); app.processEvents()
assert w.width() == 1280 and w.height() == 720
for name in w.nav_buttons:
    w.nav_buttons[name].click(); app.processEvents()
    assert w.width() == 1280 and w.height() == 720
w.close()
'''
    run_offscreen(code)


def test_placeholder_pages_scroll_and_do_not_expose_financial_input_controls():
    code = r'''
from PySide6.QtWidgets import QApplication, QLineEdit, QScrollArea
from chitlog.ui.main_window import create_window
app=QApplication([])
w=create_window()
for page in w.page_widgets.values():
    assert isinstance(page, QScrollArea)
    assert not page.findChildren(QLineEdit)
w.close()
'''
    run_offscreen(code)
