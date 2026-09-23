"""Step 21 preview security regression."""
from pathlib import Path


def test_preview_does_not_add_network_or_google_mobile_ads_sdk():
    project = Path(__file__).resolve().parents[1]
    banner = (
        project / "chitlog/ui/advertisement_banner.py"
    ).read_text(encoding="utf-8")
    main = (
        project / "chitlog/ui/main_window.py"
    ).read_text(encoding="utf-8")

    combined = banner + main
    for forbidden in (
        "google_mobile_ads",
        "com.google.android.gms.ads",
        "QWebEngineView",
        "QNetworkAccessManager",
        "requests.get(",
        "urllib.request",
    ):
        assert forbidden not in combined

    assert "show_local_test_preview" in banner
    assert "No ad network request" in banner
