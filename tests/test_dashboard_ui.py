"""Offscreen UI smoke test for the Step 8 Dashboard page."""
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


def test_dashboard_page_is_real_and_hide_is_non_destructive():
    code = r'''
import secrets, tempfile
from pathlib import Path
from PySide6.QtWidgets import QApplication, QScrollArea
from chitlog.data.database import Database
from chitlog.data.transaction_repository import TransactionRepository
from chitlog.services.dashboard_service import DashboardService
from chitlog.services.transaction_service import TransactionInput, TransactionService
from chitlog.ui.main_window import create_window
import chitlog.ui.pages.dashboard as dashboard_module
from chitlog.ui.pages.dashboard import DashboardPage
app=QApplication([])
with tempfile.TemporaryDirectory() as d:
    root=Path(d)
    db=Database(root/'test.db',secrets.token_bytes(32),root/'snapshots').open()
    try:
        repo=TransactionRepository(db)
        tx=TransactionService(repo,'LKR')
        dashboard=DashboardService(repo)
        salary=next(c.id for c in tx.list_categories('income') if c.name=='Salary')
        item=tx.create_transaction(TransactionInput('income','2026-09-16','250.00',salary,'Salary','Bank Transfer'))
        w=create_window(transaction_service=tx,dashboard_service=dashboard,currency_code='LKR',currency_symbol='Rs')
        page=w.page_widgets['Dashboard']
        assert isinstance(page, DashboardPage)
        assert not isinstance(page, QScrollArea)
        assert isinstance(w.content_scroll, QScrollArea)
        assert w.content_scroll.widgetResizable()
        # Main content reserves a right gutter so overlay-style scrollbars do not cover it.
        assert w.content_host.layout().contentsMargins().right() >= 12
        w.resize(1000,650); w.show(); app.processEvents()
        w.nav_buttons['Dashboard'].click(); app.processEvents()
        assert w.width() == 1000 and w.height() == 650
        assert page.table.rowCount() == 1
        assert 'Rs' in page.balance_value.text()
        page.table.selectRow(0); app.processEvents()
        assert page.hide_recent_button.isEnabled()

        # Canceling confirmation must leave Recent Activity unchanged.
        dashboard_module._confirm_hide_recent=lambda parent: False
        page.hide_recent_button.click(); app.processEvents()
        assert page.table.rowCount() == 1
        assert tx.get_transaction(item) is not None

        # Confirming hides only the Dashboard item and enables Undo Hide.
        dashboard_module._confirm_hide_recent=lambda parent: True
        page.hide_recent_button.click(); app.processEvents()
        assert page.table.rowCount() == 0
        assert page.undo_hide_button.isVisible()
        assert tx.get_transaction(item) is not None
        assert tx.totals()[0] == 25000
        page.undo_hide_button.click(); app.processEvents()
        assert page.table.rowCount() == 1
        assert tx.get_transaction(item) is not None
        assert tx.totals()[0] == 25000
        w.close()
    finally:
        db.close()
'''
    run_offscreen(code)
