"""Step 21/22 advertisement preview remains opt-in development behavior."""
import os
from pathlib import Path
import subprocess
import sys


def run_offscreen(code: str, *, preview: bool):
    project = Path(__file__).resolve().parents[1]
    environment = dict(os.environ, QT_QPA_PLATFORM="offscreen")
    if preview:
        environment["CHITLOG_AD_PREVIEW"] = "1"
    else:
        environment.pop("CHITLOG_AD_PREVIEW", None)

    result = subprocess.run(
        [sys.executable, "-c", code],
        cwd=project,
        env=environment,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, result.stderr


def test_local_banner_preview_method_is_explicitly_test_only():
    code = r"""
from PySide6.QtWidgets import QApplication
from chitlog.ui.advertisement_banner import AdvertisementBanner

app = QApplication([])
banner = AdvertisementBanner()
assert banner.isHidden()

banner.show_local_test_preview()
assert not banner.isHidden()
assert banner.disclosure_label.text() == "TEST ADVERTISEMENT"
assert "No ad network request" in banner.message_label.text()
assert banner.link_button.isHidden()
"""
    run_offscreen(code, preview=False)


def test_main_window_preview_is_environment_opt_in():
    project = Path(__file__).resolve().parents[1]
    source = (
        project / "chitlog/ui/main_window.py"
    ).read_text(encoding="utf-8")

    assert 'os.environ.get("CHITLOG_AD_PREVIEW", "").strip() == "1"' in source
    assert "self.ad_banner.show_local_test_preview()" in source
