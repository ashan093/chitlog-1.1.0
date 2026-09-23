"""Worker profile management for permanent and temporary workers."""
from __future__ import annotations

from PySide6.QtCore import QDate, Qt
from PySide6.QtWidgets import (
    QComboBox,
    QDateEdit,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QGridLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QTextEdit,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from chitlog.core.money import amount_text_from_minor, format_minor, minor_digits
from chitlog.services.worker_service import WorkerError, WorkerInput, WorkerService
from chitlog.ui.theme import SPACE, stylesheet
from chitlog.ui.widgets import Card, button, text_label
from chitlog.ui.pages.worker_work_records import WorkerWorkPanel
from chitlog.ui.pages.worker_payments import WorkerPaymentsPanel
from chitlog.ui.pages.worker_payroll_summary import WorkerPayrollSummaryPage


PAYMENT_LABELS = {
    "daily": "Daily",
    "job": "Per Job",
    "period": "Custom Period",
    "monthly": "Monthly",
}
WORKER_TYPE_LABELS = {"permanent": "Permanent", "temporary": "Temporary"}


def _theme_name_from_widget(widget) -> str:
    current = widget
    while current is not None:
        name = getattr(current, "theme_name", None)
        if name in {"light", "dark", "system"}:
            return name
        current = current.parentWidget() if hasattr(current, "parentWidget") else None
    return "light"


def _apply_dialog_theme(dialog: QDialog, parent) -> None:
    dialog.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
    dialog.setAutoFillBackground(True)
    dialog.setStyleSheet(stylesheet(_theme_name_from_widget(parent)))


def _confirm_deactivate(parent, worker_name: str) -> bool:
    dialog = QDialog(parent)
    dialog.setWindowTitle("Deactivate Worker")
    dialog.setModal(True)
    _apply_dialog_theme(dialog, parent)
    dialog.setMinimumWidth(480)
    layout = QVBoxLayout(dialog)
    layout.setContentsMargins(SPACE["lg"], SPACE["lg"], SPACE["lg"], SPACE["lg"])
    layout.setSpacing(SPACE["md"])
    layout.addWidget(text_label("Deactivate worker?", "heading"))
    layout.addWidget(
        text_label(
            f'“{worker_name}” will move to Inactive workers. The profile remains saved and can be reactivated later.'
        )
    )
    actions = QHBoxLayout()
    actions.addStretch(1)
    cancel = button("Cancel")
    deactivate = button("Deactivate Worker", "primary")
    actions.addWidget(cancel)
    actions.addWidget(deactivate)
    layout.addLayout(actions)
    cancel.clicked.connect(dialog.reject)
    deactivate.clicked.connect(dialog.accept)
    cancel.setDefault(True)
    return dialog.exec() == QDialog.DialogCode.Accepted




def _confirm_permanent_delete(parent, worker_name: str) -> bool:
    dialog = QDialog(parent)
    dialog.setWindowTitle("Permanently Delete Worker")
    dialog.setModal(True)
    _apply_dialog_theme(dialog, parent)
    dialog.setMinimumWidth(500)
    layout = QVBoxLayout(dialog)
    layout.setContentsMargins(SPACE["lg"], SPACE["lg"], SPACE["lg"], SPACE["lg"])
    layout.setSpacing(SPACE["md"])
    layout.addWidget(text_label("Permanently delete worker?", "heading"))
    layout.addWidget(
        text_label(
            f'“{worker_name}” will be completely removed from ChitLog. '
            "This cannot be undone. If the worker has work, payment, or payroll history, "
            "ChitLog will block permanent deletion to protect financial records."
        )
    )
    actions = QHBoxLayout()
    actions.addStretch(1)
    cancel = button("Cancel")
    delete = button("Delete Permanently", "danger")
    actions.addWidget(cancel)
    actions.addWidget(delete)
    layout.addLayout(actions)
    cancel.clicked.connect(dialog.reject)
    delete.clicked.connect(dialog.accept)
    cancel.setDefault(True)
    return dialog.exec() == QDialog.DialogCode.Accepted


class InlineMessage(QLabel):
    def __init__(self):
        super().__init__("")
        self.setProperty("role", "error")
        self.setWordWrap(True)
        self.setMinimumHeight(22)
        self.setVisible(False)

    def show_message(self, message: str) -> None:
        self.setText(message)
        self.setVisible(True)

    def clear_message(self) -> None:
        self.clear()
        self.setVisible(False)


class WorkerDialog(QDialog):
    def __init__(
        self,
        service: WorkerService,
        currency_code: str,
        worker_id: int | None = None,
        parent=None,
    ):
        super().__init__(parent)
        self.service = service
        self.currency_code = currency_code
        self.worker_id = worker_id
        self.setWindowTitle("Edit Worker" if worker_id else "Add Worker")
        self.setModal(True)
        _apply_dialog_theme(self, parent)
        self.resize(590, 680)

        root = QVBoxLayout(self)
        root.setContentsMargins(SPACE["lg"], SPACE["lg"], SPACE["lg"], SPACE["lg"])
        root.setSpacing(SPACE["md"])
        root.addWidget(text_label("Edit worker" if worker_id else "Add worker", "pageTitle"))
        root.addWidget(
            text_label(
                "Store only the information you need. Temporary workers remain reusable later even after deactivation.",
                "muted",
            )
        )
        self.error = InlineMessage()
        root.addWidget(self.error)

        form = QFormLayout()
        form.setHorizontalSpacing(SPACE["lg"])
        form.setVerticalSpacing(SPACE["md"])

        self.name_edit = QLineEdit()
        self.name_edit.setPlaceholderText("Worker name")
        self.name_edit.setMaxLength(120)
        form.addRow("Name", self.name_edit)

        self.type_combo = QComboBox()
        self.type_combo.addItem("Permanent", "permanent")
        self.type_combo.addItem("Temporary", "temporary")
        form.addRow("Worker type", self.type_combo)

        self.phone_edit = QLineEdit()
        self.phone_edit.setPlaceholderText("Optional phone number")
        self.phone_edit.setMaxLength(40)
        form.addRow("Phone", self.phone_edit)

        self.address_edit = QTextEdit()
        self.address_edit.setPlaceholderText("Optional address")
        self.address_edit.setMaximumHeight(78)
        form.addRow("Address", self.address_edit)

        self.payment_combo = QComboBox()
        self.payment_combo.addItem("Daily", "daily")
        self.payment_combo.addItem("Per Job / Work Completed", "job")
        self.payment_combo.addItem("Period / Custom Work Period", "period")
        self.payment_combo.addItem("Monthly", "monthly")
        form.addRow("Default payment", self.payment_combo)

        self.rate_label = QLabel()
        self.rate_edit = QLineEdit()
        self._rate_digits = minor_digits(currency_code)
        self.rate_edit.setMaxLength(24)
        form.addRow(self.rate_label, self.rate_edit)

        self.date_added = QDateEdit(QDate.currentDate())
        self.date_added.setCalendarPopup(True)
        self.date_added.setDisplayFormat("yyyy-MM-dd")
        self.date_added.setMinimumWidth(150)
        form.addRow("Date added", self.date_added)

        self.notes_edit = QTextEdit()
        self.notes_edit.setPlaceholderText("Optional notes")
        self.notes_edit.setMaximumHeight(90)
        form.addRow("Notes", self.notes_edit)
        root.addLayout(form)

        buttons = QDialogButtonBox()
        self.save_button = buttons.addButton(
            "Save Worker", QDialogButtonBox.ButtonRole.AcceptRole
        )
        self.save_button.setProperty("role", "primary")
        buttons.addButton("Cancel", QDialogButtonBox.ButtonRole.RejectRole)
        buttons.accepted.connect(self.save)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)

        for edit in (self.name_edit, self.phone_edit, self.rate_edit):
            edit.textChanged.connect(lambda *_: self.error.clear_message())
        self.type_combo.currentIndexChanged.connect(lambda *_: self.error.clear_message())
        self.payment_combo.currentIndexChanged.connect(lambda *_: self.error.clear_message())
        self.payment_combo.currentIndexChanged.connect(lambda *_: self._sync_rate_field())
        self._sync_rate_field()

        if worker_id is not None:
            self._load(worker_id)

    def _sync_rate_field(self) -> None:
        method = self.payment_combo.currentData()
        if method == "daily":
            self.rate_label.setText(f"Daily rate ({self.currency_code})")
            prefix = "Required — "
        elif method == "monthly":
            self.rate_label.setText(f"Monthly salary ({self.currency_code})")
            prefix = "Required — "
        else:
            self.rate_label.setText(f"Normal rate ({self.currency_code})")
            prefix = "Optional — "
        sample = "0" if self._rate_digits == 0 else "0." + "0" * self._rate_digits
        self.rate_edit.setPlaceholderText(prefix + sample)

    def _load(self, worker_id: int) -> None:
        worker = self.service.get_worker(worker_id)
        if worker is None:
            self.error.show_message("That worker no longer exists.")
            self.save_button.setEnabled(False)
            return
        self.name_edit.setText(worker.name)
        index = self.type_combo.findData(worker.worker_type)
        if index >= 0:
            self.type_combo.setCurrentIndex(index)
        self.phone_edit.setText(worker.phone)
        self.address_edit.setPlainText(worker.address)
        index = self.payment_combo.findData(worker.payment_method)
        if index >= 0:
            self.payment_combo.setCurrentIndex(index)
        if worker.normal_rate_minor is not None:
            self.rate_edit.setText(amount_text_from_minor(worker.normal_rate_minor, self.currency_code))
        added = QDate.fromString(worker.date_added, "yyyy-MM-dd")
        if added.isValid():
            self.date_added.setDate(added)
        self.notes_edit.setPlainText(worker.notes)

    def _input(self) -> WorkerInput:
        return WorkerInput(
            name=self.name_edit.text(),
            worker_type=self.type_combo.currentData(),
            phone=self.phone_edit.text(),
            address=self.address_edit.toPlainText(),
            notes=self.notes_edit.toPlainText(),
            payment_method=self.payment_combo.currentData(),
            normal_rate=self.rate_edit.text(),
            date_added=self.date_added.date().toString("yyyy-MM-dd"),
        )

    def save(self) -> None:
        self.error.clear_message()
        try:
            if self.worker_id is None:
                self.service.create_worker(self._input())
            else:
                self.service.update_worker(self.worker_id, self._input())
        except WorkerError as error:
            self.error.show_message(str(error))
            return
        self.accept()


class WorkersPage(QWidget):
    """Worker area with separate Profile, Work Records, and Payments child tabs."""

    def __init__(
        self,
        service: WorkerService,
        currency_code: str,
        currency_symbol: str,
        parent=None,
        work_service=None,
        payment_service=None,
        payroll_service=None,
    ):
        super().__init__(parent)
        self.service = service
        self.currency_code = currency_code
        self.currency_symbol = currency_symbol
        self.work_service = work_service
        self.payment_service = payment_service
        self.payroll_service = payroll_service
        self._selected_id: int | None = None
        self._record_selected_id: int | None = None
        self._payment_selected_id: int | None = None
        self._header_compact = False

        self.root_layout = QVBoxLayout(self)
        self.root_layout.setContentsMargins(0, 0, 0, 0)
        self.root_layout.setSpacing(SPACE["sm"])

        self.tabs = QTabWidget()
        self.tabs.setObjectName("workerTabs")
        self.tabs.setDocumentMode(True)
        self.tabs.setMovable(False)
        self.root_layout.addWidget(self.tabs)

        self.management_tab = QWidget()
        self.records_tab = QWidget()
        self.payments_tab = QWidget()
        self.payroll_tab = QWidget()
        self.tabs.addTab(self.management_tab, "Worker Profiles")
        self.tabs.addTab(self.records_tab, "Work Records")
        self.tabs.addTab(self.payments_tab, "Payments & Advances")
        self.tabs.addTab(self.payroll_tab, "Payroll Summary")

        self._build_management_tab()
        self._build_records_tab()
        self._build_payments_tab()
        self._build_payroll_tab()
        self.tabs.currentChanged.connect(self._tab_changed)

        self.refresh()
        from PySide6.QtCore import QTimer
        QTimer.singleShot(0, lambda: self._set_header_compact(self.width() < 900))

    # ----------------------------- shared UI helpers -----------------------------
    @staticmethod
    def _configure_worker_table(table: QTableWidget) -> None:
        table.setHorizontalHeaderLabels(
            ["Name", "Type", "Default Payment", "Normal Rate", "Phone", "Status", "Date Added"]
        )
        table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        table.setAlternatingRowColors(False)
        table.verticalHeader().setVisible(False)
        header_view = table.horizontalHeader()
        header_view.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        for column in range(1, 7):
            header_view.setSectionResizeMode(column, QHeaderView.ResizeMode.ResizeToContents)

    def _fill_worker_table(self, table: QTableWidget, workers, selected_id: int | None) -> int:
        table.setRowCount(len(workers))
        selected_row = -1
        for row, worker in enumerate(workers):
            name_item = QTableWidgetItem(worker.name)
            name_item.setData(Qt.ItemDataRole.UserRole, worker.id)
            table.setItem(row, 0, name_item)
            table.setItem(row, 1, QTableWidgetItem(WORKER_TYPE_LABELS[worker.worker_type]))
            table.setItem(row, 2, QTableWidgetItem(PAYMENT_LABELS[worker.payment_method]))
            rate = "—" if worker.normal_rate_minor is None else format_minor(
                worker.normal_rate_minor, self.currency_code, self.currency_symbol
            )
            table.setItem(row, 3, QTableWidgetItem(rate))
            table.setItem(row, 4, QTableWidgetItem(worker.phone or "—"))
            table.setItem(row, 5, QTableWidgetItem("Active" if worker.is_active else "Inactive"))
            table.setItem(row, 6, QTableWidgetItem(worker.date_added))
            if worker.id == selected_id:
                selected_row = row
        return selected_row

    @staticmethod
    def _selected_id_from_table(table: QTableWidget) -> int | None:
        rows = table.selectionModel().selectedRows()
        if not rows:
            return None
        item = table.item(rows[0].row(), 0)
        if item is None:
            return None
        value = item.data(Qt.ItemDataRole.UserRole)
        return int(value) if value is not None else None

    # ------------------------------- profile tab -------------------------------
    def _build_management_tab(self) -> None:
        layout = QVBoxLayout(self.management_tab)
        layout.setContentsMargins(SPACE["sm"], SPACE["sm"], SPACE["sm"], SPACE["sm"])
        layout.setSpacing(SPACE["md"])
        layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        self.management_layout = layout

        self.intro = QGridLayout()
        self.intro.setContentsMargins(0, 0, 0, 0)
        self.intro.setHorizontalSpacing(SPACE["md"])
        self.intro.setVerticalSpacing(SPACE["sm"])
        self.intro.setColumnStretch(0, 1)

        intro_text_widget = QWidget()
        intro_text_widget.setMinimumWidth(0)
        title = QVBoxLayout(intro_text_widget)
        title.setContentsMargins(0, 0, 0, 0)
        title.setSpacing(SPACE["xs"])
        title.addWidget(text_label("WORKERS", "eyebrow"))
        title.addWidget(text_label("People who work for you", "title"))
        title.addWidget(
            text_label(
                "Add, edit, deactivate, reactivate, or permanently remove worker profiles.",
                "muted",
            )
        )

        self.actions_widget = QWidget()
        self.actions_layout = QHBoxLayout(self.actions_widget)
        self.actions_layout.setContentsMargins(0, 0, 0, 0)
        self.actions_layout.setSpacing(SPACE["sm"])
        self.add_button = button("+ Worker", "primary")
        self.edit_button = button("Edit Worker")
        self.active_button = button("Deactivate Worker")
        self.delete_button = button("Delete Permanently")
        self.edit_button.setEnabled(False)
        self.active_button.setEnabled(False)
        self.delete_button.setEnabled(False)
        self.add_button.clicked.connect(self.add_worker)
        self.edit_button.clicked.connect(self.edit_worker)
        self.active_button.clicked.connect(self.toggle_active)
        self.delete_button.clicked.connect(self.delete_worker_permanently)
        self.actions_layout.addWidget(self.add_button)
        self.actions_layout.addWidget(self.edit_button)
        self.actions_layout.addWidget(self.active_button)
        self.actions_layout.addWidget(self.delete_button)

        self.intro.addWidget(intro_text_widget, 0, 0)
        self.intro.addWidget(self.actions_widget, 0, 1, Qt.AlignmentFlag.AlignBottom)
        layout.addLayout(self.intro)

        cards = QHBoxLayout()
        cards.setSpacing(SPACE["md"])
        self.active_card = Card("Active Workers")
        self.active_value = text_label("0", "metric")
        self.active_card.body.addWidget(self.active_value)
        self.active_card.body.addWidget(text_label("Currently available worker profiles.", "muted"))
        cards.addWidget(self.active_card, 1)

        self.temporary_card = Card("Temporary Workers")
        self.temporary_value = text_label("0", "metric")
        self.temporary_card.body.addWidget(self.temporary_value)
        self.temporary_card.body.addWidget(text_label("Stored for easy reuse when they return.", "muted"))
        cards.addWidget(self.temporary_card, 1)

        self.inactive_card = Card("Inactive")
        self.inactive_value = text_label("0", "metric")
        self.inactive_card.body.addWidget(self.inactive_value)
        self.inactive_card.body.addWidget(text_label("Archived profiles kept for history.", "muted"))
        cards.addWidget(self.inactive_card, 1)
        layout.addLayout(cards)

        filters = QHBoxLayout()
        filters.setSpacing(SPACE["sm"])
        filters.addWidget(text_label("Show", "muted"))
        self.status_filter = QComboBox()
        self.status_filter.addItem("Active", "active")
        self.status_filter.addItem("Inactive", "inactive")
        self.status_filter.addItem("All workers", "all")
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
        layout.addLayout(filters)

        self.table = QTableWidget(0, 7)
        self._configure_worker_table(self.table)
        self.table.setMinimumHeight(210)
        layout.addWidget(self.table, 1)

        self.feedback = text_label("", "muted")
        layout.addWidget(self.feedback)

        self.status_filter.currentIndexChanged.connect(self.refresh)
        self.type_filter.currentIndexChanged.connect(self.refresh)
        self.search_edit.textChanged.connect(self.refresh)
        self.refresh_button.clicked.connect(self.refresh)
        self.table.itemSelectionChanged.connect(self._selection_changed)

    # ----------------------------- work-record tab -----------------------------
    def _build_records_tab(self) -> None:
        layout = QVBoxLayout(self.records_tab)
        layout.setContentsMargins(SPACE["sm"], SPACE["sm"], SPACE["sm"], SPACE["sm"])
        layout.setSpacing(SPACE["sm"])
        layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        self.records_layout = layout

        filters = QHBoxLayout()
        filters.setSpacing(SPACE["sm"])
        filters.addWidget(text_label("Show", "muted"))
        self.record_status_filter = QComboBox()
        self.record_status_filter.addItem("Active", "active")
        self.record_status_filter.addItem("Inactive", "inactive")
        self.record_status_filter.addItem("All workers", "all")
        self.record_status_filter.setProperty("compact", True)
        filters.addWidget(self.record_status_filter)

        self.record_type_filter = QComboBox()
        self.record_type_filter.addItem("All types", "all")
        self.record_type_filter.addItem("Permanent", "permanent")
        self.record_type_filter.addItem("Temporary", "temporary")
        self.record_type_filter.setProperty("compact", True)
        filters.addWidget(self.record_type_filter)

        self.record_search_edit = QLineEdit()
        self.record_search_edit.setPlaceholderText("Search worker name or phone")
        self.record_search_edit.setProperty("compact", True)
        filters.addWidget(self.record_search_edit, 1)
        self.record_refresh_button = button("Refresh")
        self.record_refresh_button.setProperty("compact", True)
        filters.addWidget(self.record_refresh_button)
        layout.addLayout(filters)

        self.record_table = QTableWidget(0, 7)
        self._configure_worker_table(self.record_table)
        self.record_table.setMinimumHeight(150)
        self.record_table.setMaximumHeight(235)
        layout.addWidget(self.record_table)

        self.work_panel = None
        if self.work_service is not None:
            self.work_panel = WorkerWorkPanel(
                self.work_service,
                self.currency_code,
                self.currency_symbol,
                self.records_tab,
            )
            layout.addWidget(self.work_panel)
        else:
            layout.addWidget(text_label("Worker work records are not available.", "muted"))

        self.record_status_filter.currentIndexChanged.connect(self._refresh_record_browser)
        self.record_type_filter.currentIndexChanged.connect(self._refresh_record_browser)
        self.record_search_edit.textChanged.connect(self._refresh_record_browser)
        self.record_refresh_button.clicked.connect(self._refresh_record_browser)
        self.record_table.itemSelectionChanged.connect(self._record_selection_changed)

    # -------------------------- payments / advances tab --------------------------
    def _build_payments_tab(self) -> None:
        layout = QVBoxLayout(self.payments_tab)
        layout.setContentsMargins(SPACE["sm"], SPACE["sm"], SPACE["sm"], SPACE["sm"])
        layout.setSpacing(SPACE["sm"])
        layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        self.payments_layout = layout

        # Keep the same worker finder used by Work Records so payments stay easy
        # to use without switching back to another child tab just to select a worker.
        filters = QHBoxLayout()
        filters.setSpacing(SPACE["sm"])
        filters.addWidget(text_label("Show", "muted"))
        self.payment_status_filter = QComboBox()
        self.payment_status_filter.addItem("Active", "active")
        self.payment_status_filter.addItem("Inactive", "inactive")
        self.payment_status_filter.addItem("All workers", "all")
        self.payment_status_filter.setProperty("compact", True)
        filters.addWidget(self.payment_status_filter)

        self.payment_type_filter = QComboBox()
        self.payment_type_filter.addItem("All types", "all")
        self.payment_type_filter.addItem("Permanent", "permanent")
        self.payment_type_filter.addItem("Temporary", "temporary")
        self.payment_type_filter.setProperty("compact", True)
        filters.addWidget(self.payment_type_filter)

        self.payment_search_edit = QLineEdit()
        self.payment_search_edit.setPlaceholderText("Search worker name or phone")
        self.payment_search_edit.setProperty("compact", True)
        filters.addWidget(self.payment_search_edit, 1)
        self.payment_refresh_button = button("Refresh")
        self.payment_refresh_button.setProperty("compact", True)
        filters.addWidget(self.payment_refresh_button)
        layout.addLayout(filters)

        self.payment_worker_table = QTableWidget(0, 7)
        self._configure_worker_table(self.payment_worker_table)
        self.payment_worker_table.setMinimumHeight(150)
        self.payment_worker_table.setMaximumHeight(235)
        layout.addWidget(self.payment_worker_table)

        self.payment_panel = None
        if self.payment_service is not None:
            self.payment_panel = WorkerPaymentsPanel(
                self.payment_service,
                self.currency_code,
                self.currency_symbol,
                self.payments_tab,
            )
            layout.addWidget(self.payment_panel)
        else:
            layout.addWidget(text_label("Worker payments and advances are not available.", "muted"))

        self.payment_status_filter.currentIndexChanged.connect(self._refresh_payment_browser)
        self.payment_type_filter.currentIndexChanged.connect(self._refresh_payment_browser)
        self.payment_search_edit.textChanged.connect(self._refresh_payment_browser)
        self.payment_refresh_button.clicked.connect(self._refresh_payment_browser)
        self.payment_worker_table.itemSelectionChanged.connect(self._payment_selection_changed)

    # ----------------------------- payroll summary tab -----------------------------
    def _build_payroll_tab(self) -> None:
        layout = QVBoxLayout(self.payroll_tab)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        self.payroll_page = None
        if self.payroll_service is not None:
            self.payroll_page = WorkerPayrollSummaryPage(
                self.service,
                self.payroll_service,
                self.currency_code,
                self.currency_symbol,
                self.payroll_tab,
            )
            layout.addWidget(self.payroll_page)
        else:
            layout.setContentsMargins(SPACE["sm"], SPACE["sm"], SPACE["sm"], SPACE["sm"])
            layout.addWidget(text_label("Monthly payroll summary is not available.", "muted"))

    def _tab_changed(self, index: int) -> None:
        current = self.tabs.widget(index)
        if current is self.records_tab:
            self._refresh_record_browser()
        elif current is self.payments_tab:
            self._refresh_payment_browser()
        elif current is self.payroll_tab and self.payroll_page is not None:
            self.payroll_page.refresh()

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        compact = self.width() < 900
        if compact != self._header_compact:
            self._set_header_compact(compact)

    def _set_header_compact(self, compact: bool) -> None:
        self._header_compact = compact
        self.intro.removeWidget(self.actions_widget)
        if compact:
            self.intro.addWidget(self.actions_widget, 1, 0, 1, 2)
            self.actions_layout.setAlignment(Qt.AlignmentFlag.AlignLeft)
        else:
            self.intro.addWidget(
                self.actions_widget, 0, 1, 1, 1,
                Qt.AlignmentFlag.AlignBottom | Qt.AlignmentFlag.AlignRight,
            )
            self.actions_layout.setAlignment(Qt.AlignmentFlag.AlignRight)
        self.actions_widget.updateGeometry()

    # ----------------------------- profile behavior -----------------------------
    def _selected_worker(self):
        if self._selected_id is None:
            return None
        return self.service.get_worker(self._selected_id)

    def _selection_changed(self) -> None:
        self._selected_id = self._selected_id_from_table(self.table)
        worker = self._selected_worker()
        self.edit_button.setEnabled(worker is not None)
        self.active_button.setEnabled(worker is not None)
        self.delete_button.setEnabled(worker is not None)
        if worker is not None and not worker.is_active:
            self.active_button.setText("Reactivate Worker")
        else:
            self.active_button.setText("Deactivate Worker")

    def refresh(self) -> None:
        previous = self._selected_id
        counts = self.service.counts()
        self.active_value.setText(str(counts.active))
        self.temporary_value.setText(str(counts.temporary))
        self.inactive_value.setText(str(counts.inactive))

        workers = self.service.list_workers(
            status=self.status_filter.currentData(),
            worker_type=self.type_filter.currentData(),
            search=self.search_edit.text(),
        )
        selected_row = self._fill_worker_table(self.table, workers, previous)
        if selected_row >= 0:
            self.table.selectRow(selected_row)
        else:
            self.table.clearSelection()
            self._selected_id = None
        self._selection_changed()
        self._refresh_record_browser()
        self._refresh_payment_browser()
        if getattr(self, "payroll_page", None) is not None:
            self.payroll_page.refresh()

    def _refresh_record_browser(self) -> None:
        if not hasattr(self, "record_table"):
            return
        previous = self._record_selected_id
        workers = self.service.list_workers(
            status=self.record_status_filter.currentData(),
            worker_type=self.record_type_filter.currentData(),
            search=self.record_search_edit.text(),
        )
        selected_row = self._fill_worker_table(self.record_table, workers, previous)
        if selected_row >= 0:
            self.record_table.selectRow(selected_row)
        else:
            self.record_table.clearSelection()
            self._record_selected_id = None
        self._record_selection_changed()

    def _record_selection_changed(self) -> None:
        self._record_selected_id = self._selected_id_from_table(self.record_table)
        worker = (
            self.service.get_worker(self._record_selected_id)
            if self._record_selected_id is not None
            else None
        )
        if self.work_panel is not None:
            self.work_panel.set_worker(worker)

    def _refresh_payment_browser(self) -> None:
        if not hasattr(self, "payment_worker_table"):
            return
        previous = self._payment_selected_id
        workers = self.service.list_workers(
            status=self.payment_status_filter.currentData(),
            worker_type=self.payment_type_filter.currentData(),
            search=self.payment_search_edit.text(),
        )
        selected_row = self._fill_worker_table(self.payment_worker_table, workers, previous)
        if selected_row >= 0:
            self.payment_worker_table.selectRow(selected_row)
        else:
            self.payment_worker_table.clearSelection()
            self._payment_selected_id = None
        self._payment_selection_changed()

    def _payment_selection_changed(self) -> None:
        self._payment_selected_id = self._selected_id_from_table(self.payment_worker_table)
        worker = (
            self.service.get_worker(self._payment_selected_id)
            if self._payment_selected_id is not None
            else None
        )
        if self.payment_panel is not None:
            self.payment_panel.set_worker(worker)

    def add_worker(self) -> None:
        dialog = WorkerDialog(self.service, self.currency_code, parent=self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self.feedback.setText("Worker saved.")
            self.refresh()

    def edit_worker(self) -> None:
        worker = self._selected_worker()
        if worker is None:
            return
        dialog = WorkerDialog(self.service, self.currency_code, worker.id, self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self.feedback.setText("Worker updated.")
            self.refresh()

    def toggle_active(self) -> None:
        worker = self._selected_worker()
        if worker is None:
            return
        try:
            if worker.is_active:
                if not _confirm_deactivate(self, worker.name):
                    return
                self.service.deactivate_worker(worker.id)
                self.feedback.setText("Worker deactivated. The profile remains saved for future reuse.")
            else:
                self.service.reactivate_worker(worker.id)
                self.feedback.setText("Worker reactivated.")
        except WorkerError as error:
            self.feedback.setText(str(error))
            return
        self.refresh()

    def delete_worker_permanently(self) -> None:
        worker = self._selected_worker()
        if worker is None:
            return
        if not _confirm_permanent_delete(self, worker.name):
            return
        try:
            self.service.delete_worker_permanently(worker.id)
        except WorkerError as error:
            self.feedback.setText(str(error))
            return
        self._selected_id = None
        if self._record_selected_id == worker.id:
            self._record_selected_id = None
        if self._payment_selected_id == worker.id:
            self._payment_selected_id = None
        self.feedback.setText("Worker permanently deleted.")
        self.refresh()
