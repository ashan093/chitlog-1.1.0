"""Regression checks for the simplified one-page Workers workspace."""
from pathlib import Path


def _workers_source() -> str:
    return (Path(__file__).resolve().parents[1] / "chitlog/ui/pages/workers.py").read_text(encoding="utf-8")


def test_workers_is_one_page_with_simplified_worker_list():
    source = _workers_source()
    assert "class WorkersPage(QWidget)" in source
    assert "QTabWidget" not in source
    assert "Worker Profiles" not in source
    assert "Payments & Advances" not in source
    assert "self.worker_table = QTableWidget(0, 2)" in source
    assert 'self.worker_table.setHorizontalHeaderLabels(("Worker", "Type"))' in source
    assert "self.activity_table = QTableWidget(0, 5)" in source
    assert 'self.activity_table.setHorizontalHeaderLabels(("Date", "Record", "Type", "Note", "Amount"))' in source
    assert "self.payroll_table = QTableWidget(0, 8)" in source


def test_worker_actions_search_and_month_navigation_keep_approved_layout():
    source = _workers_source()
    assert "root.addLayout(month_row)" in source
    assert "month_row.addWidget(self.previous_month_button)" in source
    assert "month_row.addWidget(self.month_label)" in source
    assert "month_row.addWidget(self.next_month_button)" in source
    assert 'browser = Card("Workers")' in source
    assert "browser.body.addLayout(filters)" in source
    assert "browser.body.addWidget(self.search_edit)" in source
    assert 'self.search_edit.setPlaceholderText("Name or phone…")' in source
    assert 'self.search_edit.setAccessibleName("Worker name or phone filter")' in source
    assert 'self.search_edit.setToolTip("Search worker name or phone number")' in source
    assert "self.search_edit.setMinimumHeight(42)" in source
    assert source.index("root.addLayout(month_row)") < source.index('browser = Card("Workers")')
    assert 'self.add_worker_button = button("+ Add Worker", "primary")' in source
    assert 'self.edit_worker_button = button("Edit")' in source
    assert 'self.active_worker_button = button("Deactivate")' in source
    # Page-level permanent delete follows the normal ChitLog theme. Only the
    # confirmation dialog keeps the red danger action.
    assert 'self.delete_worker_button = button("Delete Permanently")' in source
    assert 'delete = button("Delete Permanently", "danger")' in source
    assert 'self.undo_button = button("Undo Delete")' in source
    assert 'self.undo_button.setVisible(False)' in source
    assert "self.more_button" not in source
    assert "def _show_more_menu" not in source
    assert source.index("root.addLayout(worker_actions)") < source.index('browser = Card("Workers")')


def test_permanent_worker_delete_has_dedicated_delayed_undo():
    source = _workers_source()
    assert "self._pending_worker_delete" in source
    assert "self.worker_delete_timer = QTimer(self)" in source
    assert "self.worker_delete_timer.timeout.connect(self._finalize_pending_worker_delete)" in source
    assert "def undo_worker_delete(self)" in source
    assert "def _finalize_pending_worker_delete(self)" in source
    assert "self.worker_delete_timer.start(self.UNDO_MS)" in source
    assert "self.undo_button.setVisible(True)" in source
    assert "self.undo_button.clicked.connect(self.undo_worker_delete)" in source
    # Activity-record undo is kept separate so the top Undo Delete button only
    # appears for a worker-profile permanent deletion.
    assert 'self.activity_undo_button = button("Undo")' in source
    assert "self.activity_undo_button.clicked.connect(self.undo_delete)" in source


def test_combined_activity_identifies_and_highlights_record_source():
    source = _workers_source()
    assert 'record_label = "Payment" if kind == "payment" else "Work"' in source
    assert "def _activity_palette" in source
    assert "QColor(SAPPHIRE if is_payment else SCOOTER)" in source
    assert "QColor(SAPPHIRE if is_payment else BLUE_LAGOON)" in source
    assert "record_item.setBackground(badge_brush)" in source


def test_worker_and_activity_selection_are_preserved_across_refresh():
    source = _workers_source()
    assert "self._selected_activity" in source
    assert "previous = self._selected_id" in source
    assert "if worker.id == previous:" in source
    assert "previous = self._selected_activity" in source
    assert "if previous == (kind, rid):" in source
    assert "self.worker_table.selectRow(0)" not in source
    assert "self._activity_fallback_row" in source
    # Workers now follows the same global selection rule as every other page:
    # controls keep the row selected; only empty page/background space clears.
    assert 'preserveClickAwaySelection' not in source


def test_workers_use_global_empty_background_selection_rule():
    root = Path(__file__).resolve().parents[1]
    step23 = (root / "chitlog/ui/step23_polish.py").read_text(encoding="utf-8")
    assert "def _is_empty_background_target" in step23
    assert "if not self._is_empty_background_target(watched):" in step23
    assert 'preserveClickAwaySelection' not in step23


def test_worker_payment_changes_refresh_linked_finance_views():
    root = Path(__file__).resolve().parents[1]
    workers = _workers_source()
    main = (root / "chitlog/ui/main_window.py").read_text(encoding="utf-8")
    assert "linked_expenses_changed = Signal()" in workers
    assert "self.linked_expenses_changed.emit()" in workers
    assert "worker_page.linked_expenses_changed.connect(self._worker_transaction_setting_changed)" in main
    transaction_branch = main[main.index('elif name == "Transactions"'):main.index('elif name == "Budget"')]
    assert 'hasattr(transactions, "refresh")' in transaction_branch
    assert "transactions.refresh()" in transaction_branch


def test_workers_workspace_keeps_usable_minimum_widths_and_refreshes_selected_panel_explicitly():
    source = _workers_source()
    assert "workspace.setColumnMinimumWidth(0, 300)" in source
    assert "workspace.setColumnMinimumWidth(1, 620)" in source
    assert "browser.setMinimumWidth(300)" in source
    assert "detail.setMinimumWidth(620)" in source
    assert "self.setMinimumWidth(980)" in source
    refresh_block = source[source.index("def refresh(self)"):source.index("def _refresh_selected_worker") ]
    assert "self.worker_table.blockSignals(False)" in refresh_block
    assert "self._refresh_selected_worker()" in refresh_block
    assert refresh_block.index("self.worker_table.blockSignals(False)") < refresh_block.index("self._refresh_selected_worker()")


def test_salary_slip_selection_has_check_all_and_empty_selection_message():
    source = _workers_source()
    assert 'self.check_all_slips = QCheckBox("Check all")' in source
    assert 'self.check_all_slips.toggled.connect(self._toggle_all_slips)' in source
    assert 'def _toggle_all_slips(self, checked: bool)' in source
    assert 'def _sync_check_all_slips(self)' in source
    assert 'self.payroll_table.setObjectName("workersPayrollTable")' in source
    assert 'Select at least one worker using the checkbox (or Check all)' in source
    assert 'self.payroll_feedback.setVisible(True)' in source


def test_worker_dialog_dark_mode_fields_and_permanent_delete_menu_use_global_theme_rules():
    root = Path(__file__).resolve().parents[1]
    theme = (root / "chitlog/ui/theme.py").read_text(encoding="utf-8")
    assert 'QLineEdit, QComboBox, QDateEdit, QTimeEdit, QTextEdit, QPlainTextEdit' in theme
    assert 'QMenu {' in theme
    assert 'QMenu::item:selected' in theme
    assert 'QTableWidget#workersPayrollTable::indicator:unchecked' in theme
    assert 'image: url("{checkmark_path}")' in theme


def test_dark_summary_cards_use_opaque_brand_dark_gradient_for_clarity():
    root = Path(__file__).resolve().parents[1]
    step23 = (root / "chitlog/ui/step23_polish.py").read_text(encoding="utf-8")
    assert 'stop:0 #071F31' in step23
    assert 'stop:1 #0B4050' in step23
    assert 'QLabel[role="metric"] { color: #A6F2E9; font-weight: 700; }' in step23
    assert 'theme_value = resolve_theme(configured)' in step23
    assert '"CHITLOG_STEP23_OVERLAY" not in current_css' in step23


def test_worker_month_summary_uses_cost_wording_for_the_owner():
    source = _workers_source()
    assert 'self.earnings_card = Card("Worker Cost")' in source
    assert 'self.earnings_card = Card("Month Earnings")' not in source
