"""Offscreen wiring checks for the Step 9 Budget page."""
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


def test_budget_page_replaces_placeholder_and_refreshes():
    code = r'''
import secrets, tempfile
from pathlib import Path
from PySide6.QtWidgets import QApplication
from chitlog.data.database import Database
from chitlog.data.budget_repository import BudgetRepository
from chitlog.services.budget_service import BudgetService
from chitlog.ui.main_window import create_window
from chitlog.ui.pages.budget import BudgetPage
app=QApplication([])
with tempfile.TemporaryDirectory() as d:
    root=Path(d)
    db=Database(root/'test.db',secrets.token_bytes(32),root/'snapshots').open()
    try:
        service=BudgetService(BudgetRepository(db),'LKR')
        w=create_window(budget_service=service,currency_code='LKR',currency_symbol='Rs')
        assert isinstance(w.page_widgets['Budget'], BudgetPage)
        page=w.page_widgets['Budget']
        service.set_monthly_budget(page._month(),'50000.00',True)
        page.refresh()
        assert '50,000.00' in page.available_value.text()
        assert page.progress.minimum() == 0 and page.progress.maximum() == 100
        assert page.category_table.columnCount() == 5
        assert page.save_monthly.text() == 'Save Monthly Budget'
        w.nav_buttons['Budget'].click(); app.processEvents()
        assert w.current_page_name == 'Budget'
        w.close()
    finally:
        db.close()
'''
    run_offscreen(code)
