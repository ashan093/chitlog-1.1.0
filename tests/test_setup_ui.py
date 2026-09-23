"""Small UI regressions for first-run controls; uses no real user data."""
import os
from pathlib import Path
import subprocess
import sys


def test_setup_secret_field_and_theme_regressions(tmp_path):
    project = Path(__file__).resolve().parents[1]
    code = r'''
from PySide6.QtWidgets import QApplication, QLineEdit
from chitlog.ui.setup_wizard import SecretInput
from chitlog.ui.theme import stylesheet

app = QApplication([])
field = SecretInput()
field.configure_for_pin()
assert field.edit.inputMask() == ""
field.edit.setText("1234")
assert field.text() == "1234"
field.edit.clear()
assert field.text() == ""
assert field.edit.echoMode() == QLineEdit.EchoMode.Password
field.toggle.click()
assert field.edit.echoMode() == QLineEdit.EchoMode.Normal
field.toggle.click()
assert field.edit.echoMode() == QLineEdit.EchoMode.Password

dark = stylesheet("dark")
assert "QRadioButton:focus" in dark
assert "border: none" in dark
assert "QWizard" in dark
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
