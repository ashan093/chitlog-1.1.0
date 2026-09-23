"""Step 20 post-login startup optimization regression checks."""
from pathlib import Path


def test_real_application_enables_lazy_page_construction():
    project = Path(__file__).resolve().parents[1]
    application = (
        project / "chitlog/application.py"
    ).read_text(encoding="utf-8")
    main_window = (
        project / "chitlog/ui/main_window.py"
    ).read_text(encoding="utf-8")

    assert "lazy_pages=True" in application
    assert "lazy_pages: bool = False" in main_window
    assert "self.lazy_pages = bool(lazy_pages)" in main_window
    assert "self._lazy_unloaded_pages" in main_window
    assert 'if self.lazy_pages and name != "Dashboard":' in main_window
    assert "if name in self._lazy_unloaded_pages:" in main_window
    assert "self._load_lazy_page(name)" in main_window


def test_lazy_mode_does_not_change_default_test_helper_behavior():
    project = Path(__file__).resolve().parents[1]
    main_window = (
        project / "chitlog/ui/main_window.py"
    ).read_text(encoding="utf-8")

    # create_window/default MainWindow remains eager unless production opts in.
    assert main_window.count("lazy_pages: bool = False") >= 2


def test_duplicate_theme_pass_is_avoided_after_login():
    project = Path(__file__).resolve().parents[1]
    application = (
        project / "chitlog/application.py"
    ).read_text(encoding="utf-8")

    assert 'if getattr(window, "theme_name", None) != active_theme:' in application
    assert "window.apply_theme(active_theme)" in application
