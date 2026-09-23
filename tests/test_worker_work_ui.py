"""Offscreen integration test for worker child tabs and monthly work UI."""
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


def test_workers_page_child_tabs_month_navigation_daily_rate_and_monthly_salary():
    code = r'''
import secrets,tempfile
from pathlib import Path
from PySide6.QtWidgets import QApplication
from chitlog.data.database import Database
from chitlog.data.worker_repository import WorkerRepository
from chitlog.data.worker_work_repository import WorkerWorkRepository
from chitlog.services.worker_service import WorkerInput,WorkerService
from chitlog.services.worker_work_service import WorkerAttendanceInput,WorkerWorkInput,WorkerWorkService
from chitlog.ui.main_window import create_window
from chitlog.ui.pages.worker_work_records import WorkDayDialog
app=QApplication([])
with tempfile.TemporaryDirectory() as d:
    root=Path(d)
    db=Database(root/'test.db',secrets.token_bytes(32),root/'snapshots').open()
    try:
        worker_repo=WorkerRepository(db)
        workers=WorkerService(worker_repo,'LKR')
        work=WorkerWorkService(WorkerWorkRepository(db),worker_repo,'LKR')
        daily_id=workers.create_worker(WorkerInput('Kamal','permanent',payment_method='daily',normal_rate='2500',date_added='2026-08-01'))
        monthly_id=workers.create_worker(WorkerInput('Nimal','permanent',payment_method='monthly',normal_rate='50000',date_added='2026-08-01'))
        work.create_attendance(daily_id,WorkerAttendanceInput('2026-09-16','','site work'))
        work.create_attendance(daily_id,WorkerAttendanceInput('2026-09-15','3000','long day'))
        work.create_attendance(daily_id,WorkerAttendanceInput('2026-08-20','','august'))
        work.create_attendance(monthly_id,WorkerAttendanceInput('2026-09-10','','present'))
        work.create(monthly_id,WorkerWorkInput('job','2026-09-14','2026-09-14','2000','extra'))
        w=create_window(worker_service=workers,worker_work_service=work,currency_code='LKR',currency_symbol='Rs')
        page=w.page_widgets['Workers']
        assert page.tabs.count()==4
        assert page.tabs.tabText(0)=='Worker Profiles'
        assert page.tabs.tabText(1)=='Work Records'
        assert page.tabs.tabText(2)=='Payments & Advances'
        assert page.tabs.tabText(3)=='Payroll Summary'
        # Worker child tabs are fixed in the main shell, outside content_scroll.
        w.navigate('Workers'); app.processEvents()
        assert w.worker_subtabs.count()==4
        assert w.worker_subtabs.tabText(0) in {'Worker Profiles', 'Profiles'}
        assert w.worker_subtabs.tabToolTip(0)=='Worker Profiles'
        assert w.worker_subtabs.tabText(1) in {'Work Records', 'Records'}
        assert w.worker_subtabs.tabToolTip(1)=='Work Records'
        assert w.worker_subtabs.tabText(2) in {'Payments & Advances', 'Payments'}
        assert w.worker_subtabs.tabToolTip(2)=='Payments & Advances'
        assert w.worker_subtabs.tabText(3) in {'Payroll Summary', 'Payroll'}
        assert w.worker_subtabs.tabToolTip(3)=='Payroll Summary'
        assert not w.content_scroll.isAncestorOf(w.worker_subtabs)
        assert not w.worker_subtabs.isHidden()
        assert page.tabs.tabBar().isHidden()
        assert page.table is not page.record_table
        assert page.record_search_edit.placeholderText()=='Search worker name or phone'
        w.worker_subtabs.setCurrentIndex(1); app.processEvents()
        assert page.tabs.currentIndex()==1

        # Select daily worker in record-browser table.
        daily_row=next(r for r in range(page.record_table.rowCount()) if page.record_table.item(r,0).data(256)==daily_id)
        page.record_table.selectRow(daily_row); app.processEvents()
        panel=page.work_panel
        assert panel is not None and panel.worker.id==daily_id
        assert panel.add_day_button.text()=='+ Work Record'
        assert 'Attendance: 2 full days' in panel.month_summary.text()
        assert '5,500.00' in panel.month_summary.text()
        dlg=WorkDayDialog(work,workers.get_worker(daily_id),'LKR',parent=panel)
        assert dlg.duration_combo.currentData()=='full_day'
        assert dlg.amount_edit.text()=='2500.00'
        dlg.duration_combo.setCurrentIndex(dlg.duration_combo.findData('half_day')); app.processEvents()
        assert dlg.amount_edit.text()=='1250.00'
        dlg.duration_combo.setCurrentIndex(dlg.duration_combo.findData('hours')); app.processEvents()
        # The dialog itself is not shown in this offscreen unit check, so
        # QWidget.isVisible() is False even when the Hours field has been
        # correctly unhidden. Test the widget's explicit hidden state.
        assert not dlg.hours_edit.isHidden()
        assert dlg.amount_edit.text()==''
        dlg.close()
        current=panel.selected_month
        panel.previous_month_button.click(); app.processEvents()
        assert panel.selected_month==current.addMonths(-1)
        assert panel.table.rowCount()==1
        panel.next_month_button.click(); app.processEvents()

        # Monthly worker automatically receives fixed salary + extra earnings.
        monthly_row=next(r for r in range(page.record_table.rowCount()) if page.record_table.item(r,0).data(256)==monthly_id)
        page.record_table.selectRow(monthly_row); app.processEvents()
        assert panel.worker.id==monthly_id
        assert 'Fixed salary:' in panel.month_summary.text()
        assert '50,000.00' in panel.month_summary.text()
        assert '52,000.00' in panel.month_summary.text()
        w.close()
    finally:
        db.close()
'''
    run_offscreen(code)
