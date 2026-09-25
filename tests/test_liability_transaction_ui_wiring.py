"""Static regression checks for liability-payment finance-view wiring."""
from pathlib import Path


def source(path: str) -> str:
    root = Path(__file__).resolve().parents[1]
    return (root / path).read_text(encoding="utf-8")


def test_liability_page_emits_linked_expense_refresh_after_payment():
    liabilities = source("chitlog/ui/pages/liabilities.py")
    main = source("chitlog/ui/main_window.py")
    assert "linked_expenses_changed = Signal()" in liabilities
    payment_block = liabilities[liabilities.index("def _record_payment"):]
    assert "self.linked_expenses_changed.emit()" in payment_block
    assert "page.linked_expenses_changed.connect(self._linked_expenses_changed)" in main


def test_transactions_keep_linked_expenses_noneditable_but_allow_source_aware_delete():
    service = source("chitlog/services/transaction_service.py")
    page = source("chitlog/ui/pages/transactions.py")
    main = source("chitlog/ui/main_window.py")
    assert "def linked_expense_reference" in service
    assert '("liability_payment", int(liability_payment_id))' in service
    assert "self.edit_button.setEnabled(enabled and not linked_expense)" in page
    assert "Delete this expense and the original liability payment record." in page
    assert "self.liability_service.delete_payment(source_id)" in page
    assert "self.liability_service.restore_payment(source_id)" in page
    assert "self.worker_payment_service.delete(source_id)" in page
    assert "self.worker_payment_service.restore(source_id)" in page
    assert "worker_payment_service=self.worker_payment_service" in main
    assert "liability_service=self.liability_service" in main
    assert "page.linked_payment_changed.connect(self._linked_payment_source_changed)" in main
    assert "self._set_liability_badge(self.liability_service.totals().open_count)" in main


def test_application_reconciles_liability_expense_links_on_startup():
    app = source("chitlog/application.py")
    block = app[app.index("liability_service = LiabilityService("):app.index("report_service = ReportService")]
    assert "liability_service.reconcile_transaction_expenses()" in block
