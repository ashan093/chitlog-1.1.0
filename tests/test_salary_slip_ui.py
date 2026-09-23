"""Step 15 payroll salary-slip selection UI checks."""
from pathlib import Path


def test_payroll_ui_has_worker_checkboxes_and_pdf_actions():
    project = Path(__file__).resolve().parents[1]
    source = (project / "chitlog/ui/pages/worker_payroll_summary.py").read_text(
        encoding="utf-8"
    )

    assert "ItemIsUserCheckable" in source
    assert "Generate Salary Slip PDF" in source
    assert "Select All Slips" in source
    assert "Clear Slips" in source
    assert "QFileDialog.getSaveFileName" in source
    assert "SalarySlipPdfService" in source
    assert "self._slip_worker_ids" in source


def test_payroll_salary_slip_save_dialog_symbol_is_imported():
    from chitlog.ui.pages import worker_payroll_summary as module

    assert module.QFileDialog is not None
