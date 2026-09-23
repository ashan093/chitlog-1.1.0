"""SecurityQuestionPicker runtime behavior."""
import os
from pathlib import Path
import subprocess
import sys


def test_security_question_picker_selects_known_and_custom_values():
    project = Path(__file__).resolve().parents[1]
    code = r"""
from PySide6.QtWidgets import QApplication
from chitlog.ui.pages.settings import SecurityQuestionPicker

app = QApplication([])
picker = SecurityQuestionPicker()

known = "What was the name of your first pet?"
picker.setText(known)
assert picker.text() == known
assert picker.choice.currentData() == known
assert not picker.custom.isVisible()

custom = "What private location do I remember?"
picker.setText(custom)
assert picker.text() == custom
assert picker.choice.currentData() == picker.CUSTOM_VALUE
assert picker.custom.text() == custom
assert picker.maxLength() == 120
"""
    result = subprocess.run(
        [sys.executable, "-c", code],
        cwd=project,
        env=dict(os.environ, QT_QPA_PLATFORM="offscreen"),
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, result.stderr
