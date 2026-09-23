"""Offscreen checks for the Step 16 Reports page."""
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


def test_reports_page_is_connected_and_responsive():
    code = r"""
import secrets,tempfile
from pathlib import Path
from PySide6.QtWidgets import QApplication
from chitlog.data.database import Database
from chitlog.data.report_repository import ReportRepository
from chitlog.data.transaction_repository import TransactionRepository
from chitlog.services.report_service import ReportService
from chitlog.ui.main_window import create_window
from chitlog.ui.pages.reports import ReportsPage

app=QApplication([])
with tempfile.TemporaryDirectory() as d:
    root=Path(d)
    db=Database(root/'test.db',secrets.token_bytes(32),root/'snapshots').open()
    try:
        repo=TransactionRepository(db)
        inc=repo.add_category('income','Report UI Sales')
        exp=repo.add_category('expense','Report UI Food')
        repo.create_transaction(transaction_type='income',transaction_date='2026-09-01',amount_minor=100000,category_id=inc,description='',payment_method='Cash')
        repo.create_transaction(transaction_type='expense',transaction_date='2026-09-02',amount_minor=25000,category_id=exp,description='',payment_method='Cash')
        reports=ReportService(ReportRepository(db))
        w=create_window(report_service=reports,currency_code='LKR',currency_symbol='Rs')
        page=w.page_widgets['Reports']
        assert isinstance(page, ReportsPage)

        page.selected_month=page.selected_month.fromString('2026-09-01','yyyy-MM-dd')
        page._update_month_navigation()
        page.refresh()
        assert '1,000.00' in page.income_value.text()
        assert '250.00' in page.expense_value.text()
        assert '750.00' in page.net_value.text()
        assert page.count_value.text()=='2'
        assert len(page.trend_chart.points)==6
        assert page.category_chart.categories[0].category_name=='Report UI Food'

        page._apply_responsive_layout(700)
        assert page._summary_mode=='compact'
        assert page._charts_mode=='stacked'
        page._apply_responsive_layout(1100)
        assert page._summary_mode=='wide'
        assert page._charts_mode=='wide'

        w.navigate('Reports'); app.processEvents()
        assert w.current_page_name=='Reports'
        w.close()
    finally:
        db.close()
"""
    run_offscreen(code)
