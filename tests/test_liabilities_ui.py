"""Offscreen smoke coverage for Step 10 liability page wiring."""
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


def test_liabilities_page_replaces_placeholder_when_service_is_available():
    code = r'''
import secrets, tempfile
from pathlib import Path
from PySide6.QtWidgets import QApplication
from chitlog.data.database import Database
from chitlog.data.liability_repository import LiabilityRepository
from chitlog.services.liability_service import LiabilityInput, LiabilityPaymentInput, LiabilityService
from chitlog.ui.main_window import create_window
from chitlog.ui.pages.liabilities import LiabilitiesPage, LiabilityPaymentDialog
app=QApplication([])
with tempfile.TemporaryDirectory() as d:
    root=Path(d)
    db=Database(root/'test.db',secrets.token_bytes(32),root/'snapshots').open()
    try:
        service=LiabilityService(LiabilityRepository(db),'LKR')
        liability_id=service.create_liability(LiabilityInput('Loan','Bank','1000.00','2026-09-01','2027-09-01'))
        service.add_payment(liability_id,LiabilityPaymentInput('2026-09-16','250.00','first'))
        w=create_window(liability_service=service,currency_code='LKR',currency_symbol='Rs')
        page=w.page_widgets['Liabilities']
        assert isinstance(page,LiabilitiesPage)
        badge=w.nav_buttons['Liabilities'].badge
        assert badge.text()=='1'
        assert not badge.isHidden()
        assert badge.width()==20 and badge.height()==20
        # Initial badge placement is deferred until the sidebar layout has its final width.
        w.show(); app.processEvents()
        assert badge.x() >= w.nav_buttons['Liabilities'].width() - badge.width() - 12
        payment_dialog=LiabilityPaymentDialog(service,liability_id,'LKR','Rs',parent=page)
        assert payment_dialog.payment_date.minimumDate().toString('yyyy-MM-dd')=='2026-09-01'
        payment_dialog.close()
        assert page.table.columnCount()==7
        assert page.payments_table.columnCount()==3
        assert page.table.rowCount()==1
        assert '750.00' in page.outstanding_value.text()
        page.table.selectRow(0); app.processEvents()
        assert page.edit_button.isEnabled()
        assert page.delete_button.isEnabled()
        assert page.delete_button.text()=='Delete Liability'
        assert page.delete_button.property('role')=='primary'
        page._set_header_compact(True)
        assert page._header_compact is True
        page._set_header_compact(False)
        assert page._header_compact is False
        assert page.undo_delete_button.text()=='Undo Delete'
        assert page.undo_delete_button.isHidden()
        assert page.payment_button.isEnabled()
        assert page.payments_table.rowCount()==1
        service.add_payment(liability_id,LiabilityPaymentInput('2026-10-16','750.00','final'))
        page.refresh(); app.processEvents()
        page.table.selectRow(0); app.processEvents()
        assert not page.payment_button.isEnabled()
        assert page.table.item(0,6).text()=='Paid'
        assert badge.isHidden()
        w.close()
    finally:
        db.close()
'''
    run_offscreen(code)
