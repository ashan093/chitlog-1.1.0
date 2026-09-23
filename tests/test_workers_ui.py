"""Offscreen integration test for the Step 11 Workers page."""
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


def test_workers_page_replaces_placeholder_when_service_available():
    code = r'''
import secrets,tempfile
from pathlib import Path
from PySide6.QtWidgets import QApplication
from chitlog.data.database import Database
from chitlog.data.worker_repository import WorkerRepository
from chitlog.services.worker_service import WorkerInput,WorkerService
from chitlog.ui.main_window import create_window
import chitlog.ui.pages.workers as workers_module
from chitlog.ui.pages.workers import WorkersPage
app=QApplication([])
with tempfile.TemporaryDirectory() as d:
    root=Path(d)
    db=Database(root/'test.db',secrets.token_bytes(32),root/'snapshots').open()
    try:
        service=WorkerService(WorkerRepository(db),'LKR')
        one=service.create_worker(WorkerInput('Kamal','permanent','0711111111',payment_method='monthly',normal_rate='50000',date_added='2026-09-01'))
        two=service.create_worker(WorkerInput('Nimal','temporary','0722222222',payment_method='daily',normal_rate='2500',date_added='2026-09-02'))
        w=create_window(worker_service=service,currency_code='LKR',currency_symbol='Rs')
        page=w.page_widgets['Workers']
        assert isinstance(page,WorkersPage)
        assert page.table.columnCount()==7
        assert page.table.rowCount()==2
        assert page.active_value.text()=='2'
        assert page.temporary_value.text()=='1'
        page.table.selectRow(0); app.processEvents()
        assert page.edit_button.isEnabled()
        assert page.active_button.isEnabled()
        assert page.delete_button.isEnabled()
        selected=page._selected_worker()
        service.deactivate_worker(selected.id)
        page.refresh(); app.processEvents()
        assert page.active_value.text()=='1'
        assert page.inactive_value.text()=='1'
        page.status_filter.setCurrentIndex(page.status_filter.findData('inactive')); app.processEvents()
        assert page.table.rowCount()==1
        page.table.selectRow(0); app.processEvents()
        assert page.active_button.text()=='Reactivate Worker'
        assert page.delete_button.isEnabled()
        # Permanent deletion is explicitly confirmed and removes even an inactive profile.
        workers_module._confirm_permanent_delete=lambda parent,name: True
        page.delete_button.click(); app.processEvents()
        assert service.get_worker(selected.id) is None
        assert page.inactive_value.text()=='0'
        w.resize(920,580); w.show(); app.processEvents()
        w.nav_buttons['Workers'].click(); app.processEvents()
        assert w.width()==920 and w.height()==580
        w.close()
    finally:
        db.close()
'''
    run_offscreen(code)
