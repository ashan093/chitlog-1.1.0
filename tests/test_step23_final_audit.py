"""Final Step 23 audit regressions: page responsiveness must not fight polish."""
from pathlib import Path


def _project() -> Path:
    return Path(__file__).resolve().parents[1]


def test_step23_accepts_new_page_authored_card_limits_after_breakpoint_change():
    source = (_project() / "chitlog/ui/step23_polish.py").read_text(encoding="utf-8")
    assert "current_limits = {" in source
    assert "_step23_applied_min_height" in source
    assert "_step23_applied_max_height" in source
    assert "if last_applied is not None and int(current) != int(last_applied):" in source


def test_transactions_do_not_override_step23_metric_font_with_inline_qss():
    source = (_project() / "chitlog/ui/pages/transactions.py").read_text(encoding="utf-8")
    block = source[source.index("    def _set_summary_compact"):source.index("    def _selected_id")]
    assert "font-size: 18pt" not in block
    assert 'value.setStyleSheet("")' in block


def test_payroll_summary_does_not_override_step23_card_fonts_with_inline_qss():
    source = (_project() / "chitlog/ui/pages/worker_payroll_summary.py").read_text(encoding="utf-8")
    block = source[source.index("    def _apply_responsive_layout"):source.index("    def _size_table_columns")]
    assert "font-size: 18pt" not in block
    assert "font-size: 10.5pt" not in block
    assert 'title.setStyleSheet("")' in block
    assert 'value.setStyleSheet("")' in block
