"""Offscreen integration checks for Step 13 worker payment UI."""
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


def test_worker_payment_panel_has_separate_child_tab_worker_browser_and_month():
    code = r'''
import secrets,tempfile
from pathlib import Path
from PySide6.QtWidgets import QApplication
from chitlog.data.database import Database
from chitlog.data.worker_repository import WorkerRepository
from chitlog.data.worker_work_repository import WorkerWorkRepository
from chitlog.data.worker_payment_repository import WorkerPaymentRepository
from chitlog.services.worker_service import WorkerInput,WorkerService
from chitlog.services.worker_work_service import WorkerWorkService
from chitlog.services.worker_payment_service import WorkerPaymentInput,WorkerPaymentService
from chitlog.ui.main_window import create_window
from chitlog.ui.pages.worker_payments import WorkerPaymentDialog
app=QApplication([])
with tempfile.TemporaryDirectory() as d:
    root=Path(d)
    db=Database(root/'test.db',secrets.token_bytes(32),root/'snapshots').open()
    try:
        repo=WorkerRepository(db)
        workers=WorkerService(repo,'LKR')
        work=WorkerWorkService(WorkerWorkRepository(db),repo,'LKR')
        payments=WorkerPaymentService(WorkerPaymentRepository(db),repo,'LKR')
        daily_id=workers.create_worker(WorkerInput('Kamal','permanent',payment_method='daily',normal_rate='2500',date_added='2026-08-01'))
        monthly_id=workers.create_worker(WorkerInput('Nimal','permanent',payment_method='monthly',normal_rate='50000',date_added='2026-08-01'))
        payments.create(daily_id,WorkerPaymentInput('2026-09-16','2500','end_of_day','paid today'))
        payments.create(daily_id,WorkerPaymentInput('2026-09-10','1000','advance','advance'))
        w=create_window(worker_service=workers,worker_work_service=work,worker_payment_service=payments,currency_code='LKR',currency_symbol='Rs')
        page=w.page_widgets['Workers']
        assert page.payment_panel is not None
        assert w.worker_subtabs.count()==4
        assert w.worker_subtabs.tabText(2)=='Payments & Advances'
        assert w.worker_subtabs.tabText(3)=='Payroll Summary'
        w.worker_subtabs.setCurrentIndex(2); app.processEvents()
        assert page.tabs.currentWidget() is page.payments_tab
        row=next(r for r in range(page.payment_worker_table.rowCount()) if page.payment_worker_table.item(r,0).data(256)==daily_id)
        page.payment_worker_table.selectRow(row); app.processEvents()
        panel=page.payment_panel
        assert panel.worker.id==daily_id
        assert panel.add_payment_button.text()=='+ Payment'
        assert panel.add_advance_button.text()=='+ Advance'
        assert '2,500.00' in panel.summary.text()
        assert '1,000.00' in panel.summary.text()
        assert '3,500.00' in panel.summary.text()
        current=panel.selected_month
        panel.previous_month_button.click(); app.processEvents()
        assert panel.selected_month==current.addMonths(-1)
        panel.next_month_button.click(); app.processEvents()
        assert panel.selected_month==current

        daily_dialog=WorkerPaymentDialog(payments,workers.get_worker(daily_id),'LKR',parent=panel)
        assert daily_dialog.type_combo.currentData()=='end_of_day'
        daily_dialog.close()
        monthly_dialog=WorkerPaymentDialog(payments,workers.get_worker(monthly_id),'LKR',parent=panel)
        assert monthly_dialog.type_combo.currentData()=='salary'
        monthly_dialog.close()
        advance_dialog=WorkerPaymentDialog(payments,workers.get_worker(daily_id),'LKR',force_type='advance',parent=panel)
        assert advance_dialog.type_combo.currentData()=='advance'
        assert not advance_dialog.type_combo.isEnabled()
        advance_dialog.close()
        w.close()
    finally:
        db.close()
'''
    run_offscreen(code)
