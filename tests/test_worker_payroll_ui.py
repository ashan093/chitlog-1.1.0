"""Offscreen Step 14 payroll-summary integration check."""
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


def test_payroll_summary_is_fourth_fixed_worker_child_tab():
    code = r"""
import secrets,tempfile
from pathlib import Path
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication
from chitlog.data.database import Database
from chitlog.data.worker_repository import WorkerRepository
from chitlog.data.worker_work_repository import WorkerWorkRepository
from chitlog.data.worker_payment_repository import WorkerPaymentRepository
from chitlog.data.worker_payroll_repository import WorkerPayrollRepository
from chitlog.services.worker_service import WorkerInput,WorkerService
from chitlog.services.worker_work_service import WorkerAttendanceInput,WorkerWorkService
from chitlog.services.worker_payment_service import WorkerPaymentInput,WorkerPaymentService
from chitlog.services.worker_payroll_service import WorkerPayrollService
from chitlog.ui.main_window import create_window
app=QApplication([])
with tempfile.TemporaryDirectory() as d:
    root=Path(d)
    db=Database(root/'test.db',secrets.token_bytes(32),root/'snapshots').open()
    try:
        repo=WorkerRepository(db)
        workers=WorkerService(repo,'LKR')
        work=WorkerWorkService(WorkerWorkRepository(db),repo,'LKR')
        payments=WorkerPaymentService(WorkerPaymentRepository(db),repo,'LKR')
        payroll=WorkerPayrollService(repo,work,payments,WorkerPayrollRepository(db))
        wid=workers.create_worker(WorkerInput('Kamal','permanent',payment_method='daily',normal_rate='2500',date_added='2026-09-01'))
        work.create_attendance(wid,WorkerAttendanceInput('2026-09-05','','day one'))
        work.create_attendance(wid,WorkerAttendanceInput('2026-09-06','','day two'))
        payments.create(wid,WorkerPaymentInput('2026-09-06','2500','partial','part paid'))
        w=create_window(worker_service=workers,worker_work_service=work,worker_payment_service=payments,worker_payroll_service=payroll,currency_code='LKR',currency_symbol='Rs')
        w.navigate('Workers'); app.processEvents()
        page=w.page_widgets['Workers']
        assert page.tabs.count()==4
        assert w.worker_subtabs.count()==4
        assert w.worker_subtabs.tabText(3) in {'Payroll Summary', 'Payroll'}
        assert w.worker_subtabs.tabToolTip(3)=='Payroll Summary'
        assert w.worker_subtabs.expanding()
        assert not w.content_scroll.isAncestorOf(w.worker_subtabs)
        w.worker_subtabs.setCurrentIndex(3); app.processEvents()
        assert page.tabs.currentWidget() is page.payroll_tab
        payroll_page=page.payroll_page
        assert payroll_page is not None
        assert payroll_page.table.columnCount()==8
        assert not payroll_page.carry_control.isHidden()
        assert payroll_page.carry_choice.isCheckable()
        assert payroll_page.carry_choice.text()=='Carry All'
        assert payroll_page.carry_choice.isChecked()
        assert payroll_page.table.horizontalScrollBarPolicy() == Qt.ScrollBarPolicy.ScrollBarAsNeeded
        payroll_page._apply_responsive_layout(700)
        assert payroll_page._responsive_mode == 'compact'
        # Step 23 owns responsive metric typography. Payroll must not pin an
        # inline font size that would outrank the global responsive stylesheet.
        assert payroll_page.earnings_value.styleSheet() == ''
        assert payroll_page.given_value.styleSheet() == ''
        assert payroll_page.due_value.styleSheet() == ''
        assert payroll_page.earnings_card.maximumHeight() == 108
        assert payroll_page.cards_layout.indexOf(payroll_page.due_card) >= 0
        payroll_page._apply_responsive_layout(1000)
        assert payroll_page._responsive_mode == 'wide'
        row=next(r for r in range(payroll_page.table.rowCount()) if payroll_page.table.item(r,0).text()=='Kamal')
        assert '5,000.00' in payroll_page.table.item(row,2).text()
        assert '2,500.00' in payroll_page.table.item(row,4).text()
        assert '2,500.00' in payroll_page.table.item(row,6).text()
        assert payroll_page.table.item(row,7).text()=='Partially Paid'
        # Totals are shown with no row selected, and the global toggle applies
        # to all workers in this month.
        assert payroll_page._summary_titles[0].text()=='Total Amount to Pay'
        assert payroll_page.carry_choice.text()=='Carry All'
        assert payroll_page.carry_choice.isChecked()
        # Selecting a worker changes the same cards to that worker's detail.
        payroll_page.table.selectRow(row); app.processEvents()
        assert payroll_page._summary_titles[0].text()=='Amount to Pay'
        assert payroll_page._summary_titles[3].text()=='Status'
        assert payroll_page.state_value.text()=='Partially Paid'
        assert '5,000.00' in payroll_page.earnings_value.text()
        assert '2,500.00' in payroll_page.given_value.text()
        assert '2,500.00' in payroll_page.due_value.text()
        assert not payroll_page.carry_control.isHidden()
        assert payroll_page.carry_choice.text()=='Carry'
        assert payroll_page.carry_choice.isChecked()
        assert 'font-size:9pt' in payroll_page.carry_choice.toolTip()
        payroll_page.carry_choice.setChecked(False); app.processEvents()
        assert payroll.carry_forward_for_worker(wid, payroll_page._month_start_text()) is False
        # Clearing selection restores totals.
        payroll_page.table.clearSelection(); app.processEvents()
        assert payroll_page._summary_titles[0].text()=='Total Amount to Pay'
        assert payroll_page._summary_titles[3].text()=='Workers With Balance'
        assert not payroll_page.carry_control.isHidden()
        assert payroll_page.carry_choice.text()=='Carry All'
        assert not payroll_page.carry_choice.isChecked()

        # With no row selected, switching Carry All ON applies to all workers.
        payroll_page.carry_choice.setChecked(True); app.processEvents()
        assert payroll.carry_forward_for_worker(wid, payroll_page._month_start_text()) is True
        w.close()
    finally:
        db.close()
"""
    run_offscreen(code)
