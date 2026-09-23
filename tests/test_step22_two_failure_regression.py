"""Step 22 two-failure regression checks."""
from pathlib import Path


def test_ad_preview_is_opt_in_only():
    project = Path(__file__).resolve().parents[1]
    source = (
        project / "chitlog/ui/main_window.py"
    ).read_text(encoding="utf-8")

    assert 'os.environ.get("CHITLOG_AD_PREVIEW", "").strip() == "1"' in source
    assert "self.ad_banner.show_local_test_preview()" in source


def test_salary_slip_keeps_step15_layout_and_step22_atomic_save():
    project = Path(__file__).resolve().parents[1]
    source = (
        project / "chitlog/services/salary_slip_service.py"
    ).read_text(encoding="utf-8")

    # Confirmed Step 15 visual/content behavior.
    assert "fullRectPixels" in source
    assert "QMarginsF(0, 0, 0, 0)" in source
    assert '"Work time"' in source
    assert "attendance_duration_label(record)" in source
    assert 'f"Status: {summary.status}"' not in source
    assert "carry_forward_for_worker(worker.id, month)" not in source

    # Step 22 file-integrity hardening.
    assert "def _render_pdf(" in source
    assert "def _validate_pdf_file(" in source
    assert "uuid4().hex" in source
    assert "os.replace(stage, output)" in source
    assert "output.is_symlink()" in source
