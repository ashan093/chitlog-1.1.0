"""Offscreen checks for Step 7 transaction page wiring."""
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


def test_transactions_page_replaces_placeholder_when_service_is_available():
    code = r'''
import secrets, tempfile
from pathlib import Path
from PySide6.QtWidgets import QApplication, QScrollArea
from chitlog.data.database import Database
from chitlog.data.transaction_repository import TransactionRepository
from chitlog.services.transaction_service import TransactionService
from chitlog.ui.main_window import create_window
from chitlog.ui.pages.transactions import TransactionsPage
app=QApplication([])
with tempfile.TemporaryDirectory() as d:
    root=Path(d)
    db=Database(root/'test.db',secrets.token_bytes(32),root/'snapshots').open()
    try:
        service=TransactionService(TransactionRepository(db),'LKR')
        w=create_window(transaction_service=service,currency_code='LKR',currency_symbol='Rs')
        assert isinstance(w.page_widgets['Transactions'], TransactionsPage)
        assert not isinstance(w.page_widgets['Transactions'], QScrollArea)
        page=w.page_widgets['Transactions']
        assert page.table.columnCount() == 6
        assert page.add_income.text() == '+ Income'
        assert page.add_expense.text() == '+ Expense'
        assert page.type_filter.property('compact') is True
        assert page.category_filter.property('compact') is True
        assert page.search.property('compact') is True
        assert page.use_date_range.property('compact') is True
        assert page.start_date.minimumWidth() >= 150
        assert page.end_date.minimumWidth() >= 150
        assert page.table.minimumHeight() <= 160
        assert page.table.maximumHeight() > 420
        assert not page.income_value.wordWrap()
        assert not page.expense_value.wordWrap()
        assert not page.net_value.wordWrap()
        assert page.transaction_actions_layout.indexOf(page.undo_button) == page.transaction_actions_layout.indexOf(page.delete_button) + 1
        assert page.undo_button.text() == 'Undo Delete'
        # Transaction actions belong in the records section above the record list.
        assert page.records_section_layout.indexOf(page.table) > page.records_section_layout.indexOf(page.transaction_actions_layout)
        assert page.table.sizePolicy().verticalPolicy().name == 'Expanding'
        assert page.feedback_bar.height() <= 50
        assert page.feedback_bar.maximumHeight() <= 50
        assert page.month_label.text() == page.selected_month.toString('MMMM yyyy')
        assert page.previous_month_button.isEnabled()
        assert not page.next_month_button.isEnabled()
        start, end = page._month_bounds()
        assert start == page.selected_month.toString('yyyy-MM-01')
        assert end == page.selected_month.addMonths(1).addDays(-1).toString('yyyy-MM-dd')
        w.resize(920,580); w.show(); app.processEvents()
        w.nav_buttons['Transactions'].click(); app.processEvents()
        assert w.width() == 920 and w.height() == 580

        # Test the deterministic responsive styling helper directly. Qt's
        # offscreen platform keeps layout-owned child widgets at the layout's
        # geometry, so manual page.resize(...) is not a reliable native-width test.
        page._set_summary_compact(True)
        # Step 23 owns metric typography through the responsive card stylesheet.
        # Page-level inline font sizes must stay empty in both density modes so
        # they cannot override the global responsive font rules.
        assert page.income_value.styleSheet() == ''
        assert page.expense_value.styleSheet() == ''
        assert page.net_value.styleSheet() == ''
        assert page.income_card.maximumHeight() == 116
        page._set_summary_compact(False)
        assert page.income_value.styleSheet() == ''
        assert page.expense_value.styleSheet() == ''
        assert page.net_value.styleSheet() == ''
        assert page.income_card.maximumHeight() == 122

        # Sidebar collapse itself is verified by its state and fixed width.
        w.toggle_sidebar(); app.processEvents()
        assert w.sidebar_collapsed is True
        assert w.sidebar.width() == w.COLLAPSED_SIDEBAR_WIDTH
        # The page shell itself must not need a scrollbar; only the data table may scroll.
        assert not hasattr(page, 'verticalScrollBar')
        # The month navigator browses backwards/forwards and stops at the current month.
        current_month = page.selected_month
        page.previous_month_button.click(); app.processEvents()
        assert page.selected_month == current_month.addMonths(-1)
        assert page.month_label.text() == page.selected_month.toString('MMMM yyyy')
        assert page.next_month_button.isEnabled()
        page.next_month_button.click(); app.processEvents()
        assert page.selected_month == current_month
        assert not page.next_month_button.isEnabled()

        # Custom date range temporarily owns the date filter and disables month browsing.
        page.use_date_range.setChecked(True); app.processEvents()
        assert page.month_label.text() == 'Custom date range'
        assert not page.previous_month_button.isEnabled()
        assert not page.next_month_button.isEnabled()
        assert page.previous_month_button.toolTip() == 'Turn off Date range to browse months.'
        assert page.next_month_button.toolTip() == 'Turn off Date range to browse months.'
        # Date-range edits keep a valid chronological range.
        page.start_date.setDate(page.end_date.date().addDays(10)); app.processEvents()
        assert page.start_date.date() == page.end_date.date()
        page.use_date_range.setChecked(False); app.processEvents()
        assert page.month_label.text() == current_month.toString('MMMM yyyy')
        assert page.previous_month_button.isEnabled()
        assert not page.next_month_button.isEnabled()
        assert page.previous_month_button.toolTip() == 'Previous month'
        assert page.next_month_button.toolTip() == 'Next month'
        w.close()
    finally:
        db.close()
'''
    run_offscreen(code)
