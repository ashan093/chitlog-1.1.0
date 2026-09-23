"""Appearance persistence and shell theme behavior."""
import os
from pathlib import Path
import subprocess
import sys

import pytest

from chitlog.core.settings import AppearanceSettings


def test_theme_roundtrip(tmp_path):
    store = AppearanceSettings(tmp_path / "appearance.json")
    assert store.load_theme() == "light"
    store.save_theme("dark")
    assert AppearanceSettings(store.path).load_theme() == "dark"
    store.save_theme("light")
    assert store.load_theme() == "light"
    store.save_theme("system")
    assert store.load_theme() == "system"


@pytest.mark.parametrize(
    "contents",
    ["broken", "[]", '{"theme":"unknown"}', '{"theme":null}', '{"theme":[]}', "x" * 4097],
)
def test_invalid_preferences_fall_back(tmp_path, contents):
    path = tmp_path / "appearance.json"
    path.write_text(contents, encoding="utf-8")
    assert AppearanceSettings(path).load_theme() == "light"


def test_invalid_selection_does_not_overwrite(tmp_path):
    store = AppearanceSettings(tmp_path / "appearance.json")
    store.save_theme("dark")
    with pytest.raises(ValueError):
        store.save_theme("invalid")
    assert store.load_theme() == "dark"


def test_failed_replace_preserves_previous_setting(tmp_path, monkeypatch):
    store = AppearanceSettings(tmp_path / "appearance.json")
    store.save_theme("dark")

    def deny(*args):
        raise PermissionError("denied")

    monkeypatch.setattr(os, "replace", deny)
    with pytest.raises(PermissionError):
        store.save_theme("light")
    assert store.load_theme() == "dark"
    assert len(list(tmp_path.iterdir())) == 1


def test_shell_theme_controls_and_fallback(tmp_path):
    code = r'''
from pathlib import Path
import sys
from PySide6.QtWidgets import QApplication
from chitlog.ui.main_window import create_window
from chitlog.core.settings import AppearanceSettings
app = QApplication([])
store = AppearanceSettings(Path(sys.argv[1]) / "appearance.json")
w = create_window(Path(sys.argv[1]) / "missing-art", store)
w.show()
app.processEvents()
w.theme_buttons["dark"].click()
assert w.theme_name == "dark" and store.load_theme() == "dark"
w.theme_buttons["light"].click()
assert w.theme_name == "light" and store.load_theme() == "light"
w.theme_buttons["system"].click()
assert w.theme_name == "system" and store.load_theme() == "system"
w.resize(980, 640)
app.processEvents()
assert not w.grab().isNull()
w.close()
new = create_window(settings=store)
assert new.theme_name == "system"
new.close()
'''
    result = subprocess.run(
        [sys.executable, "-c", code, str(tmp_path)],
        cwd=Path(__file__).resolve().parents[1],
        env=dict(os.environ, QT_QPA_PLATFORM="offscreen"),
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, result.stderr


def test_shell_theme_saver_callback(tmp_path):
    project = Path(__file__).resolve().parents[1]
    code = r'''
from pathlib import Path
from PySide6.QtWidgets import QApplication
from chitlog.core.settings import AppearanceSettings
from chitlog.ui.main_window import create_window
import sys
app = QApplication([])
saved=[]
store=AppearanceSettings(Path(sys.argv[1]) / 'appearance.json')
w=create_window(settings=store, theme_saver=saved.append)
w.select_theme('dark')
assert store.load_theme() == 'dark'
assert saved == ['dark']
w.select_theme('light')
assert store.load_theme() == 'light'
assert saved == ['dark','light']
w.close()
'''
    result = subprocess.run(
        [sys.executable, "-c", code, str(tmp_path)],
        cwd=project,
        env=dict(os.environ, QT_QPA_PLATFORM="offscreen"),
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, result.stderr


def test_system_theme_refreshes_live_without_changing_saved_preference(tmp_path):
    """System-mode OS changes must rebuild QSS; fixed Light/Dark modes must not."""
    project = Path(__file__).resolve().parents[1]
    code = r'''
from pathlib import Path
import sys
from PySide6.QtWidgets import QApplication
import chitlog.ui.main_window as main_window
from chitlog.core.settings import AppearanceSettings

app = QApplication([])
store = AppearanceSettings(Path(sys.argv[1]) / "appearance.json")
store.save_theme("system")

calls = []
real_stylesheet = main_window.stylesheet

def traced_stylesheet(name):
    calls.append(name)
    return real_stylesheet(name)

main_window.stylesheet = traced_stylesheet
w = main_window.create_window(settings=store)
w.show(); app.processEvents()
assert w.theme_name == "system"
assert w.theme_buttons["system"].isChecked()

# Simulate the callback Qt emits when Windows changes Light/Dark. The handler
# queues a fresh stylesheet build so concrete colors are resolved again.
calls.clear()
w._on_system_color_scheme_changed()
app.processEvents()
assert calls == ["system"]
assert w.theme_name == "system"
assert store.load_theme() == "system"

# A system-color change must not override an explicit Light/Dark selection.
w.select_theme("light")
calls.clear()
w._on_system_color_scheme_changed()
app.processEvents()
assert calls == []
assert w.theme_name == "light"
assert store.load_theme() == "light"
w.close()
'''
    result = subprocess.run(
        [sys.executable, "-c", code, str(tmp_path)],
        cwd=project,
        env=dict(os.environ, QT_QPA_PLATFORM="offscreen"),
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, result.stderr
