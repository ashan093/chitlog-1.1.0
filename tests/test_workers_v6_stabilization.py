from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def read(relative: str) -> str:
    return (ROOT / relative).read_text(encoding="utf-8")


def test_summary_theme_is_carried_by_each_card_not_parent_selector():
    source = read("chitlog/ui/step23_polish.py")
    assert "def _polish_summary(frame: QFrame, theme_value: str)" in source
    assert 'frame.setProperty("step23Theme", theme_value)' in source
    assert 'f"{theme_value}|{density}|{accent}' in source
    assert 'QFrame[step23Summary="true"][step23Theme="dark"]' in source
    assert 'QFrame[step23Summary="true"][step23Theme="light"]' in source
    assert 'QWidget[step23Theme="dark"] QFrame[step23Summary="true"]' not in source
    assert 'QWidget[step23Theme="light"] QFrame[step23Summary="true"]' not in source


def test_theme_switch_reapplies_global_summary_style_synchronously():
    source = read("chitlog/ui/main_window.py")
    block = source[source.index("def apply_theme(self, name: str)"):source.index("def select_theme(self, name: str)")]
    assert "self.setStyleSheet(stylesheet(name))" in block
    assert "apply_step23_polish(self)" in block
    assert "QTimer.singleShot(0, lambda: apply_step23_polish(self))" not in block
    assert "controller.schedule_summary_refresh" in block


def test_worker_compact_list_has_status_dot_and_selected_profile_details():
    source = read("chitlog/ui/pages/workers.py")
    assert "def _status_dot_icon(active: bool)" in source
    assert "QColor(SCOOTER if active else HEATHER)" in source
    assert "name.setIcon(_status_dot_icon(worker.is_active))" in source
    assert "self.worker_table = QTableWidget(0, 2)" in source
    assert 'self.worker_table.setHorizontalHeaderLabels(("Worker", "Type"))' in source
    assert "self.worker_details_toggle = QToolButton()" in source
    assert "Qt.ArrowType.DownArrow" in source
    for label in (
        '"Phone"', '"Address"', '"Notes"', '"Default payment"', '"Normal rate"',
        '"Date added"', '"Created"', '"Last updated"', '"Status"', '"Worker type"',
    ):
        assert label in source


def test_permanent_delete_preflights_live_history_but_allows_recordless_worker():
    worker_ui = read("chitlog/ui/pages/workers.py")
    repository = read("chitlog/data/worker_repository.py")
    assert "self.service.permanent_delete_status(worker.id)" in worker_ui
    assert 'if status == "history":' in worker_ui
    assert "_confirm_permanent_delete(self, worker.name)" in worker_ui
    assert 'sql += " AND is_deleted=0"' in repository
    assert "WHERE worker_id=? AND is_deleted=1" in repository


def test_worker_payment_mirror_is_atomic_and_reconciled_before_ui_opens():
    service = read("chitlog/services/worker_payment_service.py")
    application = read("chitlog/application.py")
    assert "with self.repository.database.transaction() as tx:" in service
    assert "self.repository.create(worker_id=worker_id, connection=tx" in service
    assert "self._sync_transaction_expense(payment_id, connection=tx)" in service
    assert "def reconcile_transaction_expenses(self)" in service
    assert "if current == target:" in service
    assert "worker_payment_service.reconcile_transaction_expenses()" in application


def test_worker_profile_edit_refreshes_linked_expense_descriptions_and_date_added_is_sane():
    workers = read("chitlog/ui/pages/workers.py")
    service = read("chitlog/services/worker_service.py")
    repository = read("chitlog/data/worker_repository.py")
    assert "self.payment_service.reconcile_transaction_expenses()" in workers
    assert "self.linked_expenses_changed.emit()" in workers
    assert 'Date Added cannot be in the future.' in service
    assert 'WHERE worker_id=? AND is_deleted=0' in repository


def test_permanent_worker_delete_has_safe_undo_window_before_irreversible_delete():
    source = read("chitlog/ui/pages/workers.py")
    block = source[source.index("def delete_worker_permanently(self)"):source.index("def add_work(self)")]
    assert "self._pending_worker_delete = (worker.id, worker.name, worker.is_active)" in block
    assert "self.worker_delete_timer.start(self.UNDO_MS)" in block
    assert "self.undo_button.setVisible(True)" in block
    assert "def undo_worker_delete(self)" in block
    assert "self.worker_delete_timer.stop()" in block
    assert "def _finalize_pending_worker_delete(self)" in block
    assert "self.service.delete_worker_permanently(worker_id)" in block
    # Irreversible deletion is deferred until the timer callback rather than
    # happening in the confirmation handler itself.
    confirm_part = block[:block.index("def undo_worker_delete(self)")]
    assert "self.service.delete_worker_permanently(worker.id)" not in confirm_part
