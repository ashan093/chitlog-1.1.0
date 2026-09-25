"""Regression checks for the Step 23 responsive sizing repair."""
from pathlib import Path


def _source() -> str:
    project = Path(__file__).resolve().parents[1]
    return (project / "chitlog/ui/step23_polish.py").read_text(encoding="utf-8")


def test_step23_uses_compact_bounded_buttons_and_leaves_settings_alone():
    source = _source()
    assert "ACTION_HEIGHT = 36" in source
    assert "ACTION_MIN_WIDTH = 96" in source
    assert "ACTION_MID_WIDTH = 128" in source
    assert "ACTION_MAX_WIDTH = 164" in source
    assert 'button.setProperty("step23FontTier", font_tier)' in source
    assert "button.setFixedSize(target_width, target_height)" in source
    assert "target_width = COMPACT_WIDTH" in source
    assert "target_width = NAV_ARROW_WIDTH" in source
    assert "target_height = COMPACT_HEIGHT" in source
    assert 'QPushButton[step23Density="action"][step23FontTier="small"]' in source
    assert 'QPushButton[step23Density="action"][step23FontTier="tiny"]' in source
    assert 'tiers = (' in source
    assert 'style.unpolish(button)' in source
    assert 'style.polish(button)' in source
    assert "if _is_in_settings(root, button) or _is_navigation_button(button):" in source


def test_step23_summary_cards_are_capped_and_fonts_follow_card_width():
    source = _source()
    assert "SUMMARY_MAX_HEIGHT = 128" in source
    assert "SUMMARY_DENSE_MAX_HEIGHT = 136" in source
    assert "SUMMARY_MAX_WIDTH = 560" in source
    assert "SUMMARY_COMPACT_WIDTH = 380" in source
    assert "SUMMARY_TIGHT_WIDTH = 300" in source
    assert '"max_height": frame.maximumHeight()' in source
    assert '"max_width": frame.maximumWidth()' in source
    assert "target_max_height = min(target_max_height, original_max_height)" in source
    assert "_step23_applied_max_height" in source
    assert 'frame.setProperty("step23SummaryDensity", density)' in source
    assert "label.setMaximumHeight(metric_height + 6)" in source
    assert 'QFrame[step23Summary="true"][step23SummaryDensity="compact"] QLabel[role="metric"]' in source
    assert 'QFrame[step23Summary="true"][step23SummaryDensity="tight"] QLabel[role="muted"]' in source
    assert "frame.setMaximumHeight(16777215)" not in source


def test_step23_never_treats_metric_labels_as_summary_cards():
    source = _source()
    assert "if isinstance(frame, QLabel):" in source
    assert 'return any(_norm(label.property("role")) == "metric" for label in labels)' in source
    assert "if label.parentWidget() is frame" in source
    assert "for frame in root.findChildren(QFrame):" in source
    assert "never apply card geometry to labels" in source


def test_step23_summary_highlights_use_chitlog_brand_family():
    source = _source()
    assert "brand family instead of rainbow semantic fills" in source
    assert "border-top: 3px solid #2F9D94" in source
    assert "border-top-color: #025F67" in source
    assert "border-top-color: #063154" in source
    # Summary metric color is now explicitly theme-scoped so Light/Dark/System
    # switching cannot leave one global metric color stuck across themes.
    assert 'QFrame[step23Summary="true"][step23Theme="light"] QLabel[role="metric"] { color: #025F67; }' in source
    assert 'QFrame[step23Summary="true"][step23Theme="dark"] QLabel[role="metric"] { color: #A6F2E9; font-weight: 700; }' in source
    assert 'QFrame[step23Summary="true"][step23Theme="dark"] QLabel[role="heading"] { color: #F7F6F2; font-weight: 700; }' in source
    assert "#D97706" not in source
    assert "#7C3AED" not in source


def test_step23_reacts_to_window_resize_without_relocating_controls():
    source = _source()
    assert "QEvent.Type.Resize" in source
    for forbidden in ("removeWidget(", "insertWidget(", "insertLayout(", "setParent("):
        assert forbidden not in source


def test_dashboard_does_not_pin_metric_font_over_responsive_step23_rules():
    project = Path(__file__).resolve().parents[1]
    source = (project / "chitlog/ui/pages/dashboard.py").read_text(encoding="utf-8")
    assert 'metric_style = "font-size: 20pt' not in source
    assert 'value.setStyleSheet("")' in source
    assert "metric_height = 30 if compact else 34" in source


def test_lazy_pages_receive_existing_step23_polish_immediately():
    project = Path(__file__).resolve().parents[1]
    source = (project / "chitlog/ui/main_window.py").read_text(encoding="utf-8")
    assert "QTimer.singleShot(0, lambda: apply_step23_polish(self))" in source
