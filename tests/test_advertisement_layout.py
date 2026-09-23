"""Step 21 advertisement placement regression."""
from pathlib import Path


def test_ad_banner_sits_below_pages_and_above_status_feedback():
    project = Path(__file__).resolve().parents[1]
    source = (
        project / "chitlog/ui/main_window.py"
    ).read_text(encoding="utf-8")

    pages = source.index("main_layout.addWidget(self.pages, 1)")
    banner = source.index("main_layout.addWidget(self.ad_banner)")
    feedback = source.index('self.feedback = text_label(')

    assert pages < banner < feedback
