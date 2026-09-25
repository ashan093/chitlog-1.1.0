"""One-page monthly payroll UI source checks."""
from pathlib import Path


def test_payroll_overview_is_embedded_in_workers_page():
    source=(Path(__file__).resolve().parents[1]/"chitlog/ui/pages/workers.py").read_text(encoding="utf-8")
    assert 'Card("Monthly Payroll Overview")' in source
    assert "self.payroll_table = QTableWidget(0, 8)" in source
    assert "self.carry_checkbox = QCheckBox" in source
    assert "SalarySlipPdfService" in source
    assert "def generate_salary_slips" in source
    assert "summary_for_worker" in source
