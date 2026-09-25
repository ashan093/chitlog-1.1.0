"""Step 20 independent top-level scrolling regression checks."""
from pathlib import Path


def test_every_sidebar_page_has_its_own_scroll_viewport_and_height_threshold():
    project = Path(__file__).resolve().parents[1]
    source = (
        project / "chitlog/ui/main_window.py"
    ).read_text(encoding="utf-8")

    for name in (
        "Dashboard",
        "Transactions",
        "Budget",
        "Liabilities",
        "Workers",
        "Reports",
        "Settings",
    ):
        assert f'"{name}":' in source

    assert "PAGE_SCROLL_MIN_HEIGHTS" in source
    assert "page.setMinimumHeight(PAGE_SCROLL_MIN_HEIGHTS.get(name, 620))" in source
    assert "self.page_scrolls[name] = page_scroll" in source
    assert "self.page_containers[name] = page_scroll" in source
    assert "page_scroll.setWidget(page)" in source
    assert "page_scroll.setVerticalScrollBarPolicy(" in source
    assert "ScrollBarAsNeeded" in source

    # Critical safety invariant: do not reintroduce the previous nested
    # page-host layer that caused native geometry recursion/stack overflow.
    assert 'pageHost_' not in source
    assert "self.page_hosts: dict[str, QWidget]" not in source


def test_workers_no_longer_adds_fixed_child_tabs_to_shell():
    project = Path(__file__).resolve().parents[1]
    source = (project / "chitlog/ui/main_window.py").read_text(encoding="utf-8")
    assert "main_layout.addWidget(self.worker_subtabs)" not in source
    assert "self.worker_subtabs.addTab" not in source
    assert "Workers is now a single-page workspace" in source

def test_scroll_alias_follows_active_page():
    project = Path(__file__).resolve().parents[1]
    source = (
        project / "chitlog/ui/main_window.py"
    ).read_text(encoding="utf-8")

    assert 'self.content_scroll = self.page_scrolls["Dashboard"]' in source
    assert "self.content_scroll = self.page_scrolls[name]" in source
