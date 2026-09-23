"""Workers child-tab page-scroll reset regression checks."""
from pathlib import Path


def test_worker_child_tabs_reset_workers_outer_scroll_to_top():
    project = Path(__file__).resolve().parents[1]
    source = (
        project / "chitlog/ui/main_window.py"
    ).read_text(encoding="utf-8")

    assert (
        "worker_page.tabs.currentChanged.connect("
        "self._worker_child_tab_changed)"
    ) in source
    assert "def _worker_child_tab_changed(self, index: int) -> None:" in source
    assert 'scroll = self.page_scrolls.get("Workers")' in source
    assert "scroll.verticalScrollBar().setValue(0)" in source
    assert "scroll.horizontalScrollBar().setValue(0)" in source
    assert "lambda worker_scroll=scroll" in source
    assert "worker_scroll.verticalScrollBar().setValue(0)" in source
    assert "worker_scroll.horizontalScrollBar().setValue(0)" in source


def test_fixed_worker_tabs_still_drive_internal_worker_tabs():
    project = Path(__file__).resolve().parents[1]
    source = (
        project / "chitlog/ui/main_window.py"
    ).read_text(encoding="utf-8")

    assert (
        "self.worker_subtabs.currentChanged.connect("
        "worker_page.tabs.setCurrentIndex)"
    ) in source
    assert "self._sync_worker_subtab(index)" in source
