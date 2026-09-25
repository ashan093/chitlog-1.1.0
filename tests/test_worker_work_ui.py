"""One-page worker work-record UI source checks."""
from pathlib import Path


def test_work_actions_live_on_main_workers_page():
    source=(Path(__file__).resolve().parents[1]/"chitlog/ui/pages/workers.py").read_text(encoding="utf-8")
    assert 'button("+ Work", "primary")' in source
    assert 'button("+ Other Earning")' in source
    assert "WorkDayDialog" in source
    assert "WorkRecordDialog" in source
    assert "list_attendance_month" in source
    assert "list_for_worker_month" in source
    assert '"attendance"' in source and '"work"' in source
