"""Step 20 shorter/resizable main-window regression checks."""
from pathlib import Path


def test_main_window_default_and_minimum_height_are_lower():
    project = Path(__file__).resolve().parents[1]
    source = (
        project / "chitlog/ui/main_window.py"
    ).read_text(encoding="utf-8")

    assert "self.setMinimumSize(900, 480)" in source
    assert "self.resize(1120, 650)" in source
    assert "height = min(680, max(520, int(available.height() * 0.78)))" in source


def test_short_window_uses_compact_sidebar_density():
    project = Path(__file__).resolve().parents[1]
    source = (
        project / "chitlog/ui/main_window.py"
    ).read_text(encoding="utf-8")

    assert "def _update_vertical_density(self)" in source
    assert "short = self.height() < 560" in source
    assert "very_short = self.height() < 500" in source
    assert "nav_height = 36 if short else 40" in source
    assert "self.sidebar_note.setVisible(not short and not self.sidebar_collapsed)" in source
    assert "self.privacy_label.setVisible(not very_short and not self.sidebar_collapsed)" in source
