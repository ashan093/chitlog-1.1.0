"""Step 14 monthly worker payroll summary UI."""
from __future__ import annotations

from PySide6.QtCore import QDate, QTimer, Qt
from PySide6.QtWidgets import (
    QComboBox,
    QFileDialog,
    QGridLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QScrollArea,
    QSizePolicy,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from chitlog.core.config import ASSETS
from chitlog.core.money import format_minor
from chitlog.services.worker_payroll_service import WorkerPayrollService
from chitlog.services.worker_service import WorkerService
from chitlog.services.salary_slip_service import SalarySlipError, SalarySlipPdfService
from chitlog.ui.theme import SPACE
from chitlog.ui.widgets import Card, button, text_label


WORKER_TYPE_LABELS = {"permanent": "Permanent", "temporary": "Temporary"}


class WorkerPayrollSummaryPage(QWidget):
    """Month-by-month payroll state for all matching workers.

    The cards show totals by default. Selecting a worker row switches the same
    cards to that worker's numbers. Global click-away selection handling is
    provided centrally by Step 23 so this page follows the same rule as every
    other ChitLog table.
    """

    def __init__(
        self,
        worker_service: WorkerService,
        payroll_service: WorkerPayrollService,
        currency_code: str,
        currency_symbol: str,
        parent=None,
    ):
        super().__init__(parent)
        self.worker_service = worker_service
        self.payroll_service = payroll_service
        self.currency_code = currency_code
        self.currency_symbol = currency_symbol
        today = QDate.currentDate()
        self.selected_month = QDate(today.year(), today.month(), 1)
        self._summary_by_worker_id = {}
        self._totals = (0, 0, 0, 0)
        self._slip_worker_ids: set[int] = set()
        self.salary_slip_service = SalarySlipPdfService(
            worker_service,
            payroll_service,
            currency_code,
            currency_symbol,
            ASSETS / 'chit.png',
        )

        root = QVBoxLayout(self)
        root.setContentsMargins(SPACE["sm"], SPACE["sm"], SPACE["sm"], SPACE["sm"])
        root.setSpacing(SPACE["sm"])
        self.setMinimumWidth(0)

        intro = QVBoxLayout()
        intro.setSpacing(SPACE["xs"])
        intro.addWidget(text_label("MONTHLY PAYROLL SUMMARY", "eyebrow"))
        intro.addWidget(text_label("Worker balances and payment state", "title"))
        intro.addWidget(
            text_label(
                "Previous unpaid balances carry forward. Work records define the amount to pay; advances and payments reduce what remains due.",
                "muted",
            )
        )
        root.addLayout(intro)

        # Summary cards are first.  In the totals view they summarize every
        # currently filtered worker; selecting a row changes them to that one
        # worker without changing the underlying payroll calculations.
        self.cards_widget = QWidget()
        self.cards_widget.setMinimumWidth(0)
        self.cards_layout = QGridLayout(self.cards_widget)
        self.cards_layout.setContentsMargins(0, 0, 0, 0)
        self.cards_layout.setHorizontalSpacing(SPACE["sm"])
        self.cards_layout.setVerticalSpacing(SPACE["sm"])

        self.earnings_card = Card("Total Amount to Pay")
        self.earnings_card.setToolTip(
            "Total current-month amount to pay from worked days, fixed monthly salary, and extra work records. Previous unpaid balance is shown through Remaining Due instead."
        )
        self.earnings_value = text_label("—", "metric")
        self.earnings_card.body.addWidget(self.earnings_value)

        self.given_card = Card("Total Money Given")
        self.given_card.setToolTip(
            "Payments plus advances recorded in the selected month."
        )
        self.given_value = text_label("—", "metric")
        self.given_card.body.addWidget(self.given_value)

        self.due_card = Card("Total Remaining Due")
        self.due_card.setToolTip(
            "Previous unpaid balance plus the selected month's amount to pay, minus advances and payments."
        )
        self.due_value = text_label("—", "metric")
        self.due_card.body.addWidget(self.due_value)

        self.state_card = Card("Workers With Balance")
        self.state_card.setToolTip(
            "Number of filtered workers who still have a positive amount due for the selected month."
        )
        self.state_value = text_label("—", "metric")
        self.state_card.body.addWidget(self.state_value)

        self._summary_cards = (
            self.earnings_card,
            self.given_card,
            self.due_card,
            self.state_card,
        )
        self._summary_values = (
            self.earnings_value,
            self.given_value,
            self.due_value,
            self.state_value,
        )
        self._summary_titles = tuple(card.body.itemAt(0).widget() for card in self._summary_cards)

        for card in self._summary_cards:
            card.setMinimumWidth(0)
            card.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        root.addWidget(self.cards_widget)

        # Search/filter row.
        filters = QHBoxLayout()
        filters.setSpacing(SPACE["sm"])
        filters.addWidget(text_label("Show", "muted"))
        self.status_filter = QComboBox()
        self.status_filter.addItem("All workers", "all")
        self.status_filter.addItem("Active", "active")
        self.status_filter.addItem("Inactive", "inactive")
        self.status_filter.setProperty("compact", True)
        filters.addWidget(self.status_filter)

        self.type_filter = QComboBox()
        self.type_filter.addItem("All types", "all")
        self.type_filter.addItem("Permanent", "permanent")
        self.type_filter.addItem("Temporary", "temporary")
        self.type_filter.setProperty("compact", True)
        filters.addWidget(self.type_filter)

        self.search_edit = QLineEdit()
        self.search_edit.setPlaceholderText("Search worker name or phone")
        self.search_edit.setProperty("compact", True)
        filters.addWidget(self.search_edit, 1)

        self.refresh_button = button("Refresh")
        self.refresh_button.setProperty("compact", True)
        filters.addWidget(self.refresh_button)
        root.addLayout(filters)

        # Month navigation.
        month_row = QHBoxLayout()
        month_row.setSpacing(SPACE["sm"])
        month_row.addStretch(1)
        self.previous_month_button = button("‹")
        self.previous_month_button.setFixedWidth(42)
        self.previous_month_button.setToolTip("Previous month")
        self.month_label = text_label("", "heading")
        self.month_label.setMinimumWidth(175)
        self.month_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.month_label.setWordWrap(False)
        self.next_month_button = button("›")
        self.next_month_button.setFixedWidth(42)
        self.next_month_button.setToolTip("Next month")
        month_row.addWidget(self.previous_month_button)
        month_row.addWidget(self.month_label)
        month_row.addWidget(self.next_month_button)
        month_row.addStretch(1)
        root.addLayout(month_row)

        # Payroll detail table.  At narrow widths we intentionally keep the
        # real table and its horizontal scrollbar rather than squeezing/hiding
        # financial values.  This preserves readable full records.
        self.table = QTableWidget(0, 8)
        self.table.setObjectName("payrollSummaryTable")
        self.table.setHorizontalHeaderLabels(
            (
                "Worker",
                "Type",
                "Amount to Pay",
                "Advances",
                "Payments",
                "Previous Balance",
                "Remaining Due",
                "Status",
            )
        )
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self.table.verticalHeader().setVisible(False)
        self.table.setMinimumWidth(0)
        self.table.setMinimumHeight(220)
        self.table.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.table.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.table.setHorizontalScrollMode(QTableWidget.ScrollMode.ScrollPerPixel)
        header = self.table.horizontalHeader()
        # Fixed, calculated widths give us both desired behaviors:
        # 1) on a wide/maximized window the columns expand to fill the table;
        # 2) on a narrow window readable minimum widths are preserved and the
        #    normal horizontal scrollbar appears.
        header.setSectionResizeMode(QHeaderView.ResizeMode.Fixed)
        header.setMinimumSectionSize(86)
        header.setStretchLastSection(False)

        # Carry-forward uses one compact themed toggle.
        # - No worker selected: it controls every worker for this payroll month.
        # - Worker selected: it controls only that worker for this payroll month.
        # Carry remains ON by default for existing/new month-worker combinations.
        self.carry_control = QWidget()
        carry_layout = QHBoxLayout(self.carry_control)
        carry_layout.setContentsMargins(0, 0, 0, 0)
        carry_layout.setSpacing(0)
        self.carry_choice = button("Carry")
        self.carry_choice.setCheckable(True)
        self.carry_choice.setProperty("compact", True)
        self.carry_choice.setFixedSize(64, 28)
        self.carry_choice.setStyleSheet("font-size: 8pt; padding: 2px 7px;")
        self.carry_choice.setAccessibleName("Carry remaining due to next month")
        carry_layout.addWidget(self.carry_choice)
        self.carry_control.setVisible(True)
        carry_layout.addStretch(1)
        self.select_slips_button = button("Select All Slips")
        self.select_slips_button.setProperty("compact", True)
        self.clear_slips_button = button("Clear Slips")
        self.clear_slips_button.setProperty("compact", True)
        self.generate_slips_button = button("Generate Salary Slip PDF", "primary")
        self.generate_slips_button.setProperty("compact", True)
        self.generate_slips_button.setEnabled(False)
        carry_layout.addWidget(self.select_slips_button)
        carry_layout.addSpacing(8)
        carry_layout.addWidget(self.clear_slips_button)
        carry_layout.addSpacing(8)
        carry_layout.addWidget(self.generate_slips_button)
        root.addWidget(self.carry_control)

        root.addWidget(self.table, 1)

        self.note = QLabel(
            "Select a worker to show that worker's figures in the cards. Click outside the payroll table to return to total figures."
        )
        self.note.setProperty("role", "muted")
        self.note.setWordWrap(True)
        root.addWidget(self.note)
        self.slip_feedback = text_label("", "muted")
        self.slip_feedback.setWordWrap(True)
        self.slip_feedback.setVisible(False)
        root.addWidget(self.slip_feedback)

        self.status_filter.currentIndexChanged.connect(lambda *_: self.refresh())
        self.type_filter.currentIndexChanged.connect(lambda *_: self.refresh())
        self.search_edit.textChanged.connect(lambda *_: self.refresh())
        self.refresh_button.clicked.connect(self.refresh)
        self.previous_month_button.clicked.connect(self._previous_month)
        self.next_month_button.clicked.connect(self._next_month)
        self.table.itemSelectionChanged.connect(self._selection_changed)
        self.carry_choice.toggled.connect(self._carry_choice_changed)
        self.table.itemChanged.connect(self._slip_item_changed)
        self.select_slips_button.clicked.connect(self._select_all_slips)
        self.clear_slips_button.clicked.connect(self._clear_slips)
        self.generate_slips_button.clicked.connect(self._generate_salary_slips)

        self._responsive_mode = None
        self._update_month_navigation()
        self._apply_responsive_layout(self.width())
        self.refresh()

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._apply_responsive_layout(event.size().width())
        QTimer.singleShot(0, self._size_table_columns)

    def _place_summary_cards(self, columns: int) -> None:
        while self.cards_layout.count():
            item = self.cards_layout.takeAt(0)
            del item
        for index, card in enumerate(self._summary_cards):
            row, column = divmod(index, columns)
            self.cards_layout.addWidget(card, row, column)
        for column in range(columns):
            self.cards_layout.setColumnStretch(column, 1)

    def _apply_responsive_layout(self, width: int) -> None:
        # Cards remain responsive, but the records stay a real scrollable table.
        if width < 700:
            mode = "narrow"
            card_columns = 1
        elif width < 920:
            mode = "compact"
            card_columns = 2
        else:
            mode = "wide"
            card_columns = 4

        if self._responsive_mode == mode:
            return
        self._responsive_mode = mode
        compact = mode != "wide"
        self._place_summary_cards(card_columns)

        card_margins = (12, 9, 12, 9) if compact else (18, 12, 18, 12)
        for card in self._summary_cards:
            card.body.setContentsMargins(*card_margins)
            card.setMinimumHeight(88 if compact else 96)
            card.setMaximumHeight(108 if compact else 116)
            title = card.body.itemAt(0).widget()
            if title is not None:
                # Step 23 owns responsive summary typography. Keep only the
                # wrapping behavior here; inline QSS would override it.
                title.setStyleSheet("")
                title.setWordWrap(True)
        for value in self._summary_values:
            value.setStyleSheet("")
            value.setWordWrap(False)

    def _size_table_columns(self) -> None:
        """Fill wide tables while preserving readable widths on narrow windows."""
        if self.table.columnCount() != 8:
            return
        # Worker, Type, Amount to Pay, Advances, Payments, Previous Balance,
        # Remaining Due, Status.
        base = [150, 110, 150, 110, 120, 160, 150, 120]
        available = max(0, self.table.viewport().width() - 2)
        base_total = sum(base)
        widths = list(base)

        if available > base_total:
            extra = available - base_total
            # Distribute spare width instead of leaving the right half of a
            # maximized table empty. Descriptive columns receive more room.
            weights = [4, 2, 2, 1, 1, 2, 2, 3]
            weight_total = sum(weights)
            assigned = 0
            for index, weight in enumerate(weights):
                addition = (extra * weight) // weight_total
                widths[index] += addition
                assigned += addition
            widths[-1] += extra - assigned

        for column, width in enumerate(widths):
            self.table.setColumnWidth(column, width)

    def _month_start_text(self) -> str:
        return self.selected_month.toString("yyyy-MM-01")

    def _update_month_navigation(self) -> None:
        self.month_label.setText(self.selected_month.toString("MMMM yyyy"))
        today = QDate.currentDate()
        current = QDate(today.year(), today.month(), 1)
        self.previous_month_button.setEnabled(True)
        self.next_month_button.setEnabled(self.selected_month < current)

    def _previous_month(self) -> None:
        self.selected_month = self.selected_month.addMonths(-1)
        self._slip_worker_ids.clear()
        self._update_month_navigation()
        self.refresh()

    def _next_month(self) -> None:
        today = QDate.currentDate()
        current = QDate(today.year(), today.month(), 1)
        candidate = self.selected_month.addMonths(1)
        if candidate <= current:
            self.selected_month = candidate
            self._slip_worker_ids.clear()
            self._update_month_navigation()
            self.refresh()

    def _set_card_titles(self, titles: tuple[str, str, str, str]) -> None:
        for label, title in zip(self._summary_titles, titles):
            label.setText(title)

    def _show_total_cards(self) -> None:
        amount_to_pay, money_given, remaining_due, with_balance = self._totals
        self._set_card_titles(
            (
                "Total Amount to Pay",
                "Total Money Given",
                "Total Remaining Due",
                "Workers With Balance",
            )
        )
        self.earnings_value.setText(
            format_minor(amount_to_pay, self.currency_code, self.currency_symbol)
        )
        self.given_value.setText(
            format_minor(money_given, self.currency_code, self.currency_symbol)
        )
        self.due_value.setText(
            format_minor(remaining_due, self.currency_code, self.currency_symbol)
        )
        self.state_value.setText(str(with_balance))

    def _show_worker_cards(self, summary) -> None:
        self._set_card_titles(
            ("Amount to Pay", "Money Given", "Remaining Due", "Status")
        )
        self.earnings_value.setText(
            format_minor(summary.earnings_minor, self.currency_code, self.currency_symbol)
        )
        self.given_value.setText(
            format_minor(summary.money_given_minor, self.currency_code, self.currency_symbol)
        )
        self.due_value.setText(
            format_minor(summary.remaining_due_minor, self.currency_code, self.currency_symbol)
        )
        self.state_value.setText(summary.status)

    def _apply_carry_button_style(self, checked: bool) -> None:
        # Reuse the normal ChitLog themed primary-button styling for the ON
        # state instead of hard-coding light/dark colors here.
        self.carry_choice.setProperty("role", "primary" if checked else "")
        self.carry_choice.style().unpolish(self.carry_choice)
        self.carry_choice.style().polish(self.carry_choice)
        self.carry_choice.update()

    def _eligible_workers_for_month(self):
        # "Carry All" intentionally means all workers who exist in the selected
        # month, not only the currently filtered/search-visible rows.
        workers = self.worker_service.list_workers(
            status="all", worker_type="all", search=""
        )
        month_end = self.selected_month.addMonths(1).addDays(-1).toString("yyyy-MM-dd")
        return [worker for worker in workers if worker.date_added <= month_end]

    def _carry_tooltip(self, checked: bool, *, global_mode: bool) -> str:
        if global_mode:
            message = (
                "Carry remaining due for all workers into next month. Click to turn off for all."
                if checked
                else "Carry is not enabled for every worker. Click to turn on for all workers."
            )
        else:
            message = (
                "Carry this worker's remaining due to next month. Click to turn off."
                if checked
                else "Do not carry this worker's remaining due. Click to turn on."
            )
        return f'<span style="font-size:9pt;">{message}</span>'

    def _set_global_carry_context(self) -> None:
        workers = self._eligible_workers_for_month()
        enabled = bool(workers) and all(
            self.payroll_service.carry_forward_for_worker(
                worker.id, self._month_start_text()
            )
            for worker in workers
        )
        # With no workers yet, keep the visual default as ON but disable the
        # control because there is nothing to update.
        if not workers:
            enabled = True

        self.carry_choice.blockSignals(True)
        self.carry_choice.setText("Carry All")
        self.carry_choice.setChecked(enabled)
        self.carry_choice.blockSignals(False)
        self.carry_choice.setEnabled(bool(workers))
        self.carry_choice.setToolTip(
            self._carry_tooltip(enabled, global_mode=True)
            if workers
            else '<span style="font-size:9pt;">No workers in this month.</span>'
        )
        self._apply_carry_button_style(enabled)
        self.carry_control.setVisible(True)

    def _set_carry_context(self, worker_id: int, worker_name: str) -> None:
        enabled = self.payroll_service.carry_forward_for_worker(
            worker_id, self._month_start_text()
        )
        self.carry_choice.blockSignals(True)
        self.carry_choice.setText("Carry")
        self.carry_choice.setChecked(enabled)
        self.carry_choice.blockSignals(False)
        self.carry_choice.setEnabled(True)
        self.carry_choice.setToolTip(
            self._carry_tooltip(enabled, global_mode=False)
        )
        self._apply_carry_button_style(enabled)
        self.carry_control.setVisible(True)

    def _carry_choice_changed(self, checked: bool) -> None:
        rows = self.table.selectionModel().selectedRows()

        if rows:
            # A selected worker makes the toggle local to only that worker.
            item = self.table.item(rows[0].row(), 0)
            if item is None:
                return
            worker_id = item.data(Qt.ItemDataRole.UserRole)
            if worker_id is None:
                return
            self.payroll_service.set_carry_forward(
                int(worker_id), self._month_start_text(), checked
            )
            self._set_carry_context(int(worker_id), item.text())
            return

        # No worker selected: apply this choice to every worker belonging to
        # the selected month, even if a search/filter is currently narrowing
        # the visible table.
        for worker in self._eligible_workers_for_month():
            self.payroll_service.set_carry_forward(
                worker.id, self._month_start_text(), checked
            )
        self._set_global_carry_context()

    def _selection_changed(self) -> None:
        rows = self.table.selectionModel().selectedRows()
        if not rows:
            self._show_total_cards()
            self._set_global_carry_context()
            return
        item = self.table.item(rows[0].row(), 0)
        worker_id = item.data(Qt.ItemDataRole.UserRole) if item is not None else None
        summary = self._summary_by_worker_id.get(worker_id)
        if summary is None:
            self._show_total_cards()
            self._set_global_carry_context()
            return
        self._show_worker_cards(summary)
        self._set_carry_context(int(worker_id), item.text())

    def _slip_item_changed(self, item: QTableWidgetItem) -> None:
        if item.column() != 0:
            return
        worker_id = item.data(Qt.ItemDataRole.UserRole)
        if worker_id is None:
            return
        worker_id = int(worker_id)
        if item.checkState() == Qt.CheckState.Checked:
            self._slip_worker_ids.add(worker_id)
        else:
            self._slip_worker_ids.discard(worker_id)
        self._update_slip_actions()

    def _update_slip_actions(self) -> None:
        count = len(self._slip_worker_ids)
        self.generate_slips_button.setEnabled(count > 0)
        self.clear_slips_button.setEnabled(count > 0)
        self.generate_slips_button.setText(
            "Generate Salary Slip PDF"
            if count == 0
            else f"Generate Salary Slip PDF ({count})"
        )

    def _select_all_slips(self) -> None:
        self.table.blockSignals(True)
        try:
            for row in range(self.table.rowCount()):
                item = self.table.item(row, 0)
                if item is None:
                    continue
                worker_id = item.data(Qt.ItemDataRole.UserRole)
                if worker_id is None:
                    continue
                self._slip_worker_ids.add(int(worker_id))
                item.setCheckState(Qt.CheckState.Checked)
        finally:
            self.table.blockSignals(False)
        self._update_slip_actions()

    def _clear_slips(self) -> None:
        self._slip_worker_ids.clear()
        self.table.blockSignals(True)
        try:
            for row in range(self.table.rowCount()):
                item = self.table.item(row, 0)
                if item is not None:
                    item.setCheckState(Qt.CheckState.Unchecked)
        finally:
            self.table.blockSignals(False)
        self._update_slip_actions()

    def _generate_salary_slips(self) -> None:
        if not self._slip_worker_ids:
            return

        month_name = self.selected_month.toString("MMMM-yyyy")
        default_name = f"ChitLog-Salary-Slips-{month_name}.pdf"
        path, _ = QFileDialog.getSaveFileName(
            self,
            "Save Salary Slip PDF",
            default_name,
            "PDF files (*.pdf)",
        )
        if not path:
            return
        if not path.lower().endswith(".pdf"):
            path += ".pdf"

        try:
            count = self.salary_slip_service.generate(
                path,
                sorted(self._slip_worker_ids),
                self._month_start_text(),
            )
        except SalarySlipError as error:
            self.slip_feedback.setText(str(error))
            self.slip_feedback.setVisible(True)
            return

        self.slip_feedback.setText(
            f"Saved {count} salary slip{'s' if count != 1 else ''} to: {path}"
        )
        self.slip_feedback.setVisible(True)

    def refresh(self) -> None:
        workers = self.worker_service.list_workers(
            status=self.status_filter.currentData(),
            worker_type=self.type_filter.currentData(),
            search=self.search_edit.text(),
        )

        month_end = self.selected_month.addMonths(1).addDays(-1).toString("yyyy-MM-dd")
        workers = [worker for worker in workers if worker.date_added <= month_end]
        visible_worker_ids = {worker.id for worker in workers}
        self._slip_worker_ids.intersection_update(visible_worker_ids)

        rows = []
        amount_to_pay_total = 0
        advances_total = 0
        payments_total = 0
        due_total = 0
        with_balance = 0
        self._summary_by_worker_id = {}

        for worker in workers:
            summary = self.payroll_service.summary_for_worker(
                worker.id, self._month_start_text()
            )
            rows.append((worker, summary))
            self._summary_by_worker_id[worker.id] = summary
            amount_to_pay_total += summary.earnings_minor
            advances_total += summary.advances_minor
            payments_total += summary.payments_minor
            due_total += summary.remaining_due_minor
            if summary.remaining_due_minor > 0:
                with_balance += 1

        self.table.blockSignals(True)
        self.table.clearSelection()
        self.table.setRowCount(len(rows))
        for row, (worker, summary) in enumerate(rows):
            values = (
                worker.name,
                WORKER_TYPE_LABELS.get(worker.worker_type, worker.worker_type.title()),
                format_minor(summary.earnings_minor, self.currency_code, self.currency_symbol),
                format_minor(summary.advances_minor, self.currency_code, self.currency_symbol),
                format_minor(summary.payments_minor, self.currency_code, self.currency_symbol),
                format_minor(summary.previous_unpaid_minor, self.currency_code, self.currency_symbol),
                format_minor(summary.remaining_due_minor, self.currency_code, self.currency_symbol),
                summary.status,
            )
            for column, value in enumerate(values):
                item = QTableWidgetItem(value)
                if column == 0:
                    item.setData(Qt.ItemDataRole.UserRole, worker.id)
                    item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
                    item.setCheckState(
                        Qt.CheckState.Checked
                        if worker.id in self._slip_worker_ids
                        else Qt.CheckState.Unchecked
                    )
                    item.setToolTip(
                        "Check this worker to include them in the salary slip PDF."
                    )
                if column in (2, 3, 4, 5, 6):
                    item.setTextAlignment(
                        Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
                    )
                item.setToolTip(value)
                self.table.setItem(row, column, item)
        self.table.blockSignals(False)
        self._size_table_columns()

        self._totals = (
            amount_to_pay_total,
            advances_total + payments_total,
            due_total,
            with_balance,
        )
        self._show_total_cards()
        self._set_global_carry_context()
        self._update_slip_actions()
        QTimer.singleShot(0, self._size_table_columns)
