"""Offscreen checks for narrow-window button density."""
import os
from pathlib import Path
import subprocess
import sys


def test_main_window_switches_button_density_without_shrinking_nav_buttons():
    project = Path(__file__).resolve().parents[1]
    code = r'''
from PySide6.QtWidgets import QApplication, QPushButton
from chitlog.ui.main_window import create_window
app=QApplication([])
w=create_window()
w.resize(980,620); w.show(); app.processEvents(); w._update_responsive_buttons()
normal=w.theme_buttons['light']
assert normal.property('responsiveCompact') is True
assert w.nav_buttons['Dashboard'].property('responsiveCompact') is None
w.resize(1500,850); app.processEvents(); w._update_responsive_buttons()
assert normal.property('responsiveCompact') is False
w.close()
'''
    result = subprocess.run(
        [sys.executable, "-c", code],
        cwd=project,
        env=dict(os.environ, QT_QPA_PLATFORM="offscreen"),
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, result.stderr
