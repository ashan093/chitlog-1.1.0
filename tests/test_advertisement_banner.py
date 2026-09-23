"""Step 21 safe advertisement-banner tests."""
import os
from pathlib import Path
import subprocess
import sys


def run_offscreen(code: str):
    project = Path(__file__).resolve().parents[1]
    result = subprocess.run(
        [sys.executable, "-c", code],
        cwd=project,
        env=dict(os.environ, QT_QPA_PLATFORM="offscreen"),
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, result.stderr


def test_banner_is_collapsed_by_default_and_text_only_content_is_safe():
    code = r"""
from PySide6.QtWidgets import QApplication
from chitlog.ui.advertisement_banner import AdvertisementBanner, BannerContent

app = QApplication([])
banner = AdvertisementBanner()

assert banner.isHidden()
assert not banner.has_content
assert banner.height() == banner.BANNER_HEIGHT

banner.set_content(BannerContent(text="A short approved local banner."))
assert not banner.isHidden()
assert banner.has_content
assert banner.message_label.text() == "A short approved local banner."
assert banner.disclosure_label.text() == "ADVERTISEMENT"
assert banner.link_button.isHidden()
assert banner.image_label.isHidden()

banner.clear_content()
assert banner.isHidden()
assert not banner.has_content
"""
    run_offscreen(code)


def test_banner_rejects_unapproved_or_non_https_links():
    code = r"""
from PySide6.QtWidgets import QApplication
from chitlog.ui.advertisement_banner import (
    AdvertisementBanner,
    AdvertisementValidationError,
    BannerContent,
)

app = QApplication([])
banner = AdvertisementBanner(allowed_link_hosts=("example.com",))

for link in (
    "http://example.com/ad",
    "https://evil.example/ad",
    "javascript:alert(1)",
    "file:///C:/secret.txt",
):
    try:
        banner.set_content(BannerContent(text="Test", link_url=link))
    except AdvertisementValidationError:
        pass
    else:
        raise AssertionError("Unsafe/unapproved link was accepted: " + link)

banner.set_content(
    BannerContent(
        text="Approved",
        link_url="https://example.com/ad",
    )
)
assert not banner.link_button.isHidden()
"""
    run_offscreen(code)
