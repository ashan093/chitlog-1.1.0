"""Static security boundaries for Step 21 advertisement placeholder."""
from pathlib import Path


def test_ad_component_contains_no_browser_engine_or_network_client():
    project = Path(__file__).resolve().parents[1]
    source = (
        project / "chitlog/ui/advertisement_banner.py"
    ).read_text(encoding="utf-8")

    forbidden = (
        "QWebEngine",
        "QWebView",
        "QNetworkAccessManager",
        "requests.",
        "urllib.request",
        "javascript:",
        "eval(",
        "exec(",
        "pickle",
    )
    for item in forbidden:
        assert item not in source

    assert "QDesktopServices.openUrl" in source
    assert 'parts.scheme.lower() != "https"' in source
    assert "host not in allowed_hosts" in source
    assert "MAX_AD_IMAGE_BYTES" in source
    assert "ALLOWED_IMAGE_FORMATS" in source


def test_main_window_owns_collapsed_isolated_banner_slot():
    project = Path(__file__).resolve().parents[1]
    source = (
        project / "chitlog/ui/main_window.py"
    ).read_text(encoding="utf-8")

    assert (
        "from chitlog.ui.advertisement_banner import AdvertisementBanner"
        in source
    )
    assert "self.ad_banner = AdvertisementBanner(self.main_panel)" in source
    assert "main_layout.addWidget(self.ad_banner)" in source

    # Never give the advertisement component financial/storage services.
    assert "AdvertisementBanner(self.database" not in source
    assert "AdvertisementBanner(self.transaction_service" not in source
    assert "AdvertisementBanner(self.worker_service" not in source
    assert "AdvertisementBanner(self.backup_service" not in source
