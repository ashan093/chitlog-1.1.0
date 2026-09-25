"""Workers no longer uses child-tab scroll synchronization."""
from pathlib import Path


def test_worker_child_navigation_is_removed():
    source=(Path(__file__).resolve().parents[1]/"chitlog/ui/main_window.py").read_text(encoding="utf-8")
    assert "worker_page.tabs.currentChanged.connect" not in source
    assert "worker_page.tabs.setCurrentIndex" not in source
    assert "self.worker_subtabs.addTab" not in source
    assert "Workers is now a single-page workspace" in source
    assert "self.worker_subtabs.hide()" in source
