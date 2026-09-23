"""Regression checks for the Step 23 responsiveness/performance repair."""
from pathlib import Path


def _project() -> Path:
    return Path(__file__).resolve().parents[1]


def test_step23_does_not_full_repolish_after_every_button_click_or_style_event():
    source = (_project() / "chitlog/ui/step23_polish.py").read_text(encoding="utf-8")

    assert "step23ButtonSignature" in source
    assert "RESIZE_DEBOUNCE_MS = 90" in source
    assert "self._resize_timer.setSingleShot(True)" in source
    assert "self._resize_timer.timeout.connect(self.refresh_summaries)" in source
    assert "button.clicked.connect(self.schedule_refresh)" not in source
    assert "step23RefreshConnected" not in source
    assert "QEvent.Type.StyleChange" not in source
    assert "QEvent.Type.PaletteChange" not in source
    assert "QTimer.singleShot(120, controller.refresh)" not in source
    assert "QTimer.singleShot(350, controller.refresh)" not in source


def test_step23_resize_uses_cached_summary_cards_and_signature_short_circuit():
    source = (_project() / "chitlog/ui/step23_polish.py").read_text(encoding="utf-8")

    assert "_step23_summary_frames" in source
    assert "def _cached_summary_frames" in source
    assert 'frame.property("step23SummarySignature") == signature' in source
    assert "_polish_summaries(self.root, discover=False)" in source
    assert "if watched is self.root and event_type == QEvent.Type.Resize" in source


def test_background_artwork_is_not_smooth_scaled_on_every_paint():
    source = (_project() / "chitlog/ui/widgets.py").read_text(encoding="utf-8")

    assert "_scaled_artwork_cache" in source
    assert "def _cover_artwork" in source
    assert "cache_key = (theme_key, width, height)" in source
    # Smooth scaling remains allowed in the cached large-window path, but the
    # paintEvent itself must no longer call pixmap.scaled(...).
    paint_source = source[source.index("    def paintEvent(self, event):"):]
    assert ".scaled(" not in paint_source


def test_theme_and_navigation_use_explicit_lightweight_step23_refreshes():
    source = (_project() / "chitlog/ui/main_window.py").read_text(encoding="utf-8")

    assert 'hasattr(controller, "refresh_summaries")' in source
    assert "QTimer.singleShot(0, controller.refresh_summaries)" in source
    assert 'if bool(self.property("step23PolishApplied")):' in source
    assert "QTimer.singleShot(0, lambda: apply_step23_polish(self))" in source
