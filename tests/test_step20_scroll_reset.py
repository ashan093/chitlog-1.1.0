"""Step 20 page-scroll reset regression checks."""
from pathlib import Path


def test_sidebar_navigation_resets_destination_scroll_to_top():
    project = Path(__file__).resolve().parents[1]
    source = (
        project / "chitlog/ui/main_window.py"
    ).read_text(encoding="utf-8")

    assert "destination_scroll = self.page_scrolls[name]" in source
    assert "destination_scroll.verticalScrollBar().setValue(0)" in source
    assert "destination_scroll.horizontalScrollBar().setValue(0)" in source
    assert "lambda scroll=destination_scroll" in source
    assert "scroll.verticalScrollBar().setValue(0)" in source
    assert "scroll.horizontalScrollBar().setValue(0)" in source
