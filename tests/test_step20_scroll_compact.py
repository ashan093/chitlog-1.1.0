"""Step 20 independent scrolling + compact Settings regression checks."""
from pathlib import Path


def test_every_top_level_page_has_an_independent_scroll_viewport():
    project = Path(__file__).resolve().parents[1]
    source = (
        project / "chitlog/ui/main_window.py"
    ).read_text(encoding="utf-8")

    assert "PAGE_SCROLL_MIN_HEIGHTS" in source
    assert "page.setMinimumHeight(PAGE_SCROLL_MIN_HEIGHTS.get(name, 620))" in source
    assert 'page_scroll.setObjectName(' in source
    assert '"pageScroll_" + name.lower().replace(" ", "_")' in source
    assert "page_scroll.setWidget(page)" in source
    assert "self.page_scrolls[name] = page_scroll" in source
    assert "self.page_containers[name] = page_scroll" in source
    assert "self.content_scroll = self.page_scrolls[name]" in source

    # Critical safety condition from the previous native-crash investigation:
    # direct QScrollArea -> page ownership, with no extra page-host wrapper.
    assert 'pageHost_' not in source
    assert "self.page_hosts: dict[str, QWidget]" not in source


def test_all_required_page_scroll_thresholds_are_present():
    project = Path(__file__).resolve().parents[1]
    source = (
        project / "chitlog/ui/main_window.py"
    ).read_text(encoding="utf-8")

    for line in (
        '"Dashboard": 560',
        '"Transactions": 660',
        '"Budget": 620',
        '"Liabilities": 640',
        '"Workers": 700',
        '"Reports": 640',
        '"Settings": 820',
    ):
        assert line in source


def test_step20_settings_remains_compact():
    project = Path(__file__).resolve().parents[1]
    settings = (
        project / "chitlog/ui/pages/settings.py"
    ).read_text(encoding="utf-8")
    notifications = (
        project / "chitlog/ui/pages/notifications.py"
    ).read_text(encoding="utf-8")
    backup = (
        project / "chitlog/ui/pages/backup_settings.py"
    ).read_text(encoding="utf-8")

    assert 'self.setObjectName("settingsPage")' in settings
    assert "font-size: 13px" in settings
    assert 'button("Change Login", "primary")' in settings
    assert 'setToolTip("Change Login Credentials")' in settings
    assert 'button("Update Recovery", "primary")' in settings
    assert 'setToolTip("Update Recovery Questions")' in settings
    assert "security_columns = QHBoxLayout()" in settings
    assert "embedded=True" in settings
    assert "compact=True" in settings
    assert "if not self.embedded:" in notifications
    assert "self.compact = bool(compact)" in backup
