"""Deterministic Step 15 salary-slip layout checks."""
from pathlib import Path


def test_salary_slip_is_centered_and_prints_attendance_duration_without_internal_status():
    project = Path(__file__).resolve().parents[1]
    source = (project / "chitlog/services/salary_slip_service.py").read_text(
        encoding="utf-8"
    )

    assert "fullRectPixels" in source
    assert "QMarginsF(0, 0, 0, 0)" in source
    assert '"SALARY SLIP"' in source
    assert "align=Qt.AlignmentFlag.AlignCenter" in source
    assert '"Work time"' in source
    assert "attendance_duration_label(record)" in source
    assert 'f"Status: {summary.status}"' not in source
    assert "carry_forward_for_worker(worker.id, month)" not in source
