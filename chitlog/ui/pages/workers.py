"""Worker profile management for permanent and temporary workers."""
from __future__ import annotations

from PySide6.QtCore import QDate, QTimer, Qt, Signal
from PySide6.QtGui import QColor, QBrush, QIcon, QPainter, QPixmap
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QDateEdit,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QTextEdit,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from chitlog.core.money import amount_text_from_minor, format_minor, minor_digits
from chitlog.services.worker_service import WorkerError, WorkerInput, WorkerService
from chitlog.services.worker_work_service import attendance_duration_label
from chitlog.services.salary_slip_service import SalarySlipError, SalarySlipPdfService
from chitlog.core.config import ASSETS
from chitlog.ui.theme import ALABASTER, BLUE_LAGOON, HEATHER, SAPPHIRE, SCOOTER, SPACE, THEMES, resolve_theme, stylesheet
from chitlog.ui.widgets import Card, button, text_label
from chitlog.ui.date_picker import configure_date_edit
from chitlog.ui.pages.worker_work_records import WorkDayDialog, WorkRecordDialog, WORK_TYPE_LABELS
from chitlog.ui.pages.worker_payments import WorkerPaymentDialog, PAYMENT_TYPE_LABELS


PAYMENT_LABELS = {
    "daily": "Daily",
    "job": "Per Job",
    "period": "Custom Period",
    "monthly": "Monthly",
}
WORKER_TYPE_LABELS = {"permanent": "Permanent", "temporary": "Temporary"}


def _status_dot_icon(active: bool) -> QIcon:
    """Small palette-safe worker status marker used in the compact list."""
    pixmap = QPixmap(12, 12)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QColor(SCOOTER if active else HEATHER))
    painter.drawEllipse(2, 2, 8, 8)
    painter.end()
    return QIcon(pixmap)


def _display_value(value: str | None) -> str:
    text = (value or "").strip()
    return text if text else "—"


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
            f'“{worker_name}” is eligible for permanent deletion because no retained work/payment history exists. '
            "After confirmation, ChitLog gives you 10 seconds to undo. When that window expires, "
            "the worker and any already-deleted records are permanently purged."
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


def _permanent_delete_blocked(parent, worker_name: str, is_active: bool) -> bool:
    """Explain protected history and optionally ask to deactivate instead."""
    dialog = QDialog(parent)
    dialog.setWindowTitle("Worker Cannot Be Permanently Deleted")
    dialog.setModal(True)
    _apply_dialog_theme(dialog, parent)
    dialog.setMinimumWidth(540)
    layout = QVBoxLayout(dialog)
    layout.setContentsMargins(SPACE["lg"], SPACE["lg"], SPACE["lg"], SPACE["lg"])
    layout.setSpacing(SPACE["md"])
    layout.addWidget(text_label("Permanent deletion is unavailable", "heading"))
    layout.addWidget(
        text_label(
            f'“{worker_name}” has work, payment, or payroll history. ChitLog keeps '
            "that worker profile so the financial history remains valid."
        )
    )
    if is_active:
        layout.addWidget(
            text_label(
                "Deactivate this worker instead? The worker will move to Inactive, "
                "all existing history will remain available, and the worker can be reactivated later.",
                "muted",
            )
        )
    else:
        layout.addWidget(
            text_label(
                "This worker is already inactive. Existing history is being retained for financial integrity.",
                "muted",
            )
        )

    actions = QHBoxLayout()
    actions.addStretch(1)
    close = button("Keep Worker" if is_active else "Close")
    actions.addWidget(close)
    deactivate = None
    if is_active:
        deactivate = button("Deactivate Worker", "primary")
        actions.addWidget(deactivate)
    layout.addLayout(actions)
    close.clicked.connect(dialog.reject)
    if deactivate is not None:
        deactivate.clicked.connect(dialog.accept)
        deactivate.setDefault(True)
    else:
        close.setDefault(True)
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
        configure_date_edit(
            self.date_added,
            minimum=QDate(1900, 1, 1),
            maximum=QDate.currentDate(),
        )
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
    linked_expenses_changed = Signal()
    """Single-page worker workspace.

    Worker profiles, work/earnings, payments/advances, balances, and payroll are
    intentionally presented in one month-oriented page. The existing services
    remain the source of truth; this class only simplifies the workflow.
    """

    UNDO_MS = 10_000

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
        today = QDate.currentDate()
        self.selected_month = QDate(today.year(), today.month(), 1)
        self._selected_id: int | None = None
        self._selected_activity: tuple[str, int] | None = None
        self._activity_fallback_row: int | None = None
        self._last_deleted: tuple[str, int] | None = None
        self._pending_worker_delete: tuple[int, str, bool] | None = None
        self._slip_worker_ids: set[int] = set()
        self.undo_timer = QTimer(self)
        self.undo_timer.setSingleShot(True)
        self.undo_timer.timeout.connect(self._expire_undo)
        self.worker_delete_timer = QTimer(self)
        self.worker_delete_timer.setSingleShot(True)
        self.worker_delete_timer.timeout.connect(self._finalize_pending_worker_delete)
        self.salary_slip_service = (
            SalarySlipPdfService(
                service,
                payroll_service,
                currency_code,
                currency_symbol,
                ASSETS / "chit.png",
            )
            if payroll_service is not None
            else None
        )

        root = QVBoxLayout(self)
        root.setContentsMargins(SPACE["sm"], SPACE["sm"], SPACE["sm"], SPACE["sm"])
        root.setSpacing(SPACE["md"])
        root.setAlignment(Qt.AlignmentFlag.AlignTop)

        # Header. Month navigation uses its own centered row as in the original
        # one-page Workers layout. Search/filter controls stay with the worker list.
        title = QVBoxLayout()
        title.setSpacing(SPACE["xs"])
        title.addWidget(text_label("WORKERS", "eyebrow"))
        title.addWidget(text_label("Workers", "title"))
        title.addWidget(
            text_label(
                "Manage workers, work, payments and balances.",
                "muted",
            )
        )
        root.addLayout(title)

        month_row = QHBoxLayout()
        month_row.addStretch(1)
        self.previous_month_button = button("‹")
        self.previous_month_button.setFixedWidth(42)
        self.month_label = text_label("", "heading")
        self.month_label.setMinimumWidth(180)
        self.month_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.next_month_button = button("›")
        self.next_month_button.setFixedWidth(42)
        month_row.addWidget(self.previous_month_button)
        month_row.addWidget(self.month_label)
        month_row.addWidget(self.next_month_button)
        month_row.addStretch(1)
        root.addLayout(month_row)

        # Four compact month summary cards.
        cards = QHBoxLayout()
        cards.setSpacing(SPACE["sm"])
        self.active_card = Card("Active Workers")
        self.active_value = text_label("0", "metric")
        self.active_card.body.addWidget(self.active_value)
        self.earnings_card = Card("Worker Cost")
        self.earnings_value = text_label("—", "metric")
        self.earnings_card.body.addWidget(self.earnings_value)
        self.given_card = Card("Money Given")
        self.given_value = text_label("—", "metric")
        self.given_card.body.addWidget(self.given_value)
        self.due_card = Card("Remaining Due")
        self.due_value = text_label("—", "metric")
        self.due_card.body.addWidget(self.due_value)
        for card in (self.active_card, self.earnings_card, self.given_card, self.due_card):
            cards.addWidget(card, 1)
        root.addLayout(cards)

        # Worker-management actions stay above the lists rather than inside the detail pane.
        worker_actions = QHBoxLayout()
        worker_actions.setSpacing(SPACE["sm"])
        self.add_worker_button = button("+ Add Worker", "primary")
        self.edit_worker_button = button("Edit")
        self.active_worker_button = button("Deactivate")
        self.delete_worker_button = button("Delete Permanently")
        # Worker-profile Undo appears only during the 10-second permanent-delete window.
        self.undo_button = button("Undo Delete")
        self.undo_button.setVisible(False)
        self.undo_button.setEnabled(False)
        worker_actions.addWidget(self.add_worker_button)
        worker_actions.addWidget(self.edit_worker_button)
        worker_actions.addWidget(self.active_worker_button)
        worker_actions.addWidget(self.delete_worker_button)
        worker_actions.addWidget(self.undo_button)
        worker_actions.addStretch(1)
        root.addLayout(worker_actions)

        # Main workspace: one worker browser on the left, selected worker on the right.
        workspace = QGridLayout()
        workspace.setHorizontalSpacing(SPACE["md"])
        workspace.setVerticalSpacing(SPACE["md"])
        workspace.setColumnStretch(0, 2)
        workspace.setColumnStretch(1, 5)
        # Never crush either side of the worker workspace into an unusable sliver.
        # MainWindow already supplies a horizontal page scrollbar when needed.
        workspace.setColumnMinimumWidth(0, 300)
        workspace.setColumnMinimumWidth(1, 620)
        self.setMinimumWidth(980)

        browser = Card("Workers")
        browser.setMinimumWidth(300)
        filters = QHBoxLayout()
        filters.setSpacing(SPACE["xs"])
        self.status_filter = QComboBox()
        self.status_filter.addItem("Active", "active")
        self.status_filter.addItem("Inactive", "inactive")
        self.status_filter.addItem("All", "all")
        self.type_filter = QComboBox()
        self.type_filter.addItem("All types", "all")
        self.type_filter.addItem("Permanent", "permanent")
        self.type_filter.addItem("Temporary", "temporary")
        filters.addWidget(self.status_filter)
        filters.addWidget(self.type_filter)
        browser.body.addLayout(filters)
        self.search_edit = QLineEdit()
        # Keep the worker lookup readable at narrow widths.  The placeholder and
        # accessible name intentionally avoid the Step 23 generic search-height
        # override, which clipped QLineEdit text with the normal theme padding.
        self.search_edit.setPlaceholderText("Name or phone…")
        self.search_edit.setAccessibleName("Worker name or phone filter")
        self.search_edit.setToolTip("Search worker name or phone number")
        self.search_edit.setClearButtonEnabled(True)
        self.search_edit.setMinimumWidth(0)
        self.search_edit.setMinimumHeight(42)
        browser.body.addWidget(self.search_edit)
        self.worker_table = QTableWidget(0, 2)
        self.worker_table.setHorizontalHeaderLabels(("Worker", "Type"))
        self.worker_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.worker_table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.worker_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.worker_table.verticalHeader().setVisible(False)
        self.worker_table.setMinimumHeight(310)
        wh = self.worker_table.horizontalHeader()
        wh.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        wh.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        browser.body.addWidget(self.worker_table)
        workspace.addWidget(browser, 0, 0)

        detail = Card("Selected Worker")
        detail.setMinimumWidth(620)
        detail_header = QHBoxLayout()
        name_box = QVBoxLayout()
        name_box.setSpacing(2)
        self.worker_name = text_label("Select a worker", "heading")
        self.worker_meta = text_label("Choose a worker from the list.", "muted")
        name_box.addWidget(self.worker_name)
        name_box.addWidget(self.worker_meta)
        detail_header.addLayout(name_box, 1)
        self.worker_details_toggle = QToolButton()
        self.worker_details_toggle.setArrowType(Qt.ArrowType.DownArrow)
        self.worker_details_toggle.setToolTip("Show all worker profile details")
        self.worker_details_toggle.setAccessibleName("Show worker details")
        self.worker_details_toggle.setCursor(Qt.CursorShape.PointingHandCursor)
        self.worker_details_toggle.setEnabled(False)
        detail_header.addWidget(self.worker_details_toggle, 0, Qt.AlignmentFlag.AlignTop)
        detail.body.addLayout(detail_header)

        self.worker_details_panel = QFrame()
        self.worker_details_panel.setProperty("role", "glass")
        details_form = QFormLayout(self.worker_details_panel)
        details_form.setContentsMargins(SPACE["md"], SPACE["sm"], SPACE["md"], SPACE["sm"])
        details_form.setHorizontalSpacing(SPACE["md"])
        details_form.setVerticalSpacing(SPACE["xs"])
        self.detail_type = text_label("—")
        self.detail_status = text_label("—")
        self.detail_phone = text_label("—")
        self.detail_address = text_label("—")
        self.detail_notes = text_label("—")
        self.detail_payment_method = text_label("—")
        self.detail_rate = text_label("—")
        self.detail_date_added = text_label("—")
        self.detail_created = text_label("—")
        self.detail_updated = text_label("—")
        self.detail_address.setWordWrap(True)
        self.detail_notes.setWordWrap(True)
        for caption, value in (
            ("Worker type", self.detail_type),
            ("Status", self.detail_status),
            ("Phone", self.detail_phone),
            ("Address", self.detail_address),
            ("Notes", self.detail_notes),
            ("Default payment", self.detail_payment_method),
            ("Normal rate", self.detail_rate),
            ("Date added", self.detail_date_added),
            ("Created", self.detail_created),
            ("Last updated", self.detail_updated),
        ):
            caption_label = text_label(caption, "muted")
            details_form.addRow(caption_label, value)
        self.worker_details_panel.setVisible(False)
        detail.body.addWidget(self.worker_details_panel)

        metrics = QGridLayout()
        metrics.setHorizontalSpacing(SPACE["sm"])
        self.selected_earnings = text_label("—", "metric")
        self.selected_advances = text_label("—", "metric")
        self.selected_payments = text_label("—", "metric")
        self.selected_due = text_label("—", "metric")
        for col, (caption, value) in enumerate((
            ("Earnings", self.selected_earnings),
            ("Advances", self.selected_advances),
            ("Payments", self.selected_payments),
            ("Due", self.selected_due),
        )):
            box = Card(caption)
            box.body.addWidget(value)
            metrics.addWidget(box, 0, col)
        detail.body.addLayout(metrics)

        action_row = QHBoxLayout()
        action_row.setSpacing(SPACE["sm"])
        self.add_work_button = button("+ Work", "primary")
        self.add_earning_button = button("+ Other Earning")
        self.add_payment_button = button("+ Payment")
        self.add_advance_button = button("+ Advance")
        for widget in (
            self.add_work_button,
            self.add_earning_button,
            self.add_payment_button,
            self.add_advance_button,
        ):
            action_row.addWidget(widget)
        action_row.addStretch(1)
        detail.body.addLayout(action_row)

        self.carry_checkbox = QCheckBox("Carry remaining balance to next month")
        self.carry_checkbox.setToolTip(
            "Applies to the selected worker and selected month only."
        )
        detail.body.addWidget(self.carry_checkbox)

        self.activity_table = QTableWidget(0, 5)
        self.activity_table.setHorizontalHeaderLabels(("Date", "Record", "Type", "Note", "Amount"))
        self.activity_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.activity_table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.activity_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.activity_table.verticalHeader().setVisible(False)
        self.activity_table.setMinimumHeight(245)
        ah = self.activity_table.horizontalHeader()
        ah.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        ah.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        ah.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        ah.setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
        ah.setSectionResizeMode(4, QHeaderView.ResizeMode.ResizeToContents)
        detail.body.addWidget(self.activity_table)

        activity_actions = QHBoxLayout()
        activity_actions.addStretch(1)
        self.edit_activity_button = button("Edit")
        self.delete_activity_button = button("Delete")
        self.activity_undo_button = button("Undo")
        self.activity_undo_button.setVisible(False)
        self.activity_undo_button.setEnabled(False)
        activity_actions.addWidget(self.edit_activity_button)
        activity_actions.addWidget(self.delete_activity_button)
        activity_actions.addWidget(self.activity_undo_button)
        detail.body.addLayout(activity_actions)
        self.feedback = text_label("", "muted")
        self.feedback.setVisible(False)
        detail.body.addWidget(self.feedback)
        workspace.addWidget(detail, 0, 1)
        root.addLayout(workspace)

        # One compact all-worker payroll overview at the bottom.
        payroll = Card("Monthly Payroll Overview")
        payroll_top = QHBoxLayout()
        payroll_top.addWidget(
            text_label("Select workers with the checkbox to generate salary slips.", "muted"), 1
        )
        self.check_all_slips = QCheckBox("Check all")
        self.check_all_slips.setToolTip("Select or clear every worker currently shown in the payroll overview.")
        self.payroll_collapse_button = button("Collapse ▲")
        self.generate_slips_button = button("Generate Salary Slips")
        payroll_top.addWidget(self.check_all_slips)
        payroll_top.addWidget(self.payroll_collapse_button)
        payroll_top.addWidget(self.generate_slips_button)
        payroll.body.addLayout(payroll_top)
        self.payroll_feedback = text_label("", "muted")
        self.payroll_feedback.setVisible(False)
        payroll.body.addWidget(self.payroll_feedback)
        self.payroll_table = QTableWidget(0, 8)
        self.payroll_table.setObjectName("workersPayrollTable")
        self.payroll_table.setHorizontalHeaderLabels(
            ("Worker", "Type", "Earnings", "Advances", "Payments", "Previous", "Due", "Status")
        )
        self.payroll_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.payroll_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.payroll_table.verticalHeader().setVisible(False)
        self.payroll_table.setMinimumHeight(220)
        ph = self.payroll_table.horizontalHeader()
        ph.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        for column in range(1, 8):
            ph.setSectionResizeMode(column, QHeaderView.ResizeMode.ResizeToContents)
        payroll.body.addWidget(self.payroll_table)
        root.addWidget(payroll)

        # Wiring.
        self.add_worker_button.clicked.connect(self.add_worker)
        self.previous_month_button.clicked.connect(self._previous_month)
        self.next_month_button.clicked.connect(self._next_month)
        self.status_filter.currentIndexChanged.connect(lambda *_: self.refresh())
        self.type_filter.currentIndexChanged.connect(lambda *_: self.refresh())
        self.search_edit.textChanged.connect(lambda *_: self.refresh())
        self.worker_table.itemSelectionChanged.connect(self._worker_selection_changed)
        self.worker_details_toggle.clicked.connect(self._toggle_worker_details)
        self.edit_worker_button.clicked.connect(self.edit_worker)
        self.active_worker_button.clicked.connect(self.toggle_active)
        self.delete_worker_button.clicked.connect(self.delete_worker_permanently)
        self.add_work_button.clicked.connect(self.add_work)
        self.add_earning_button.clicked.connect(self.add_earning)
        self.add_payment_button.clicked.connect(lambda: self.add_payment(False))
        self.add_advance_button.clicked.connect(lambda: self.add_payment(True))
        self.carry_checkbox.toggled.connect(self._carry_changed)
        self.check_all_slips.toggled.connect(self._toggle_all_slips)
        self.activity_table.itemSelectionChanged.connect(self._activity_selection_changed)
        self.activity_table.itemDoubleClicked.connect(lambda *_: self.edit_activity())
        self.edit_activity_button.clicked.connect(self.edit_activity)
        self.delete_activity_button.clicked.connect(self.delete_activity)
        self.undo_button.clicked.connect(self.undo_worker_delete)
        self.activity_undo_button.clicked.connect(self.undo_delete)
        self.payroll_table.itemChanged.connect(self._payroll_item_changed)
        self.generate_slips_button.clicked.connect(self.generate_salary_slips)
        self.payroll_collapse_button.clicked.connect(self._toggle_payroll_overview)

        self._update_month_navigation()
        self.refresh()

    def _month_bounds(self) -> tuple[str, str]:
        start = self.selected_month
        end = start.addMonths(1).addDays(-1)
        return start.toString("yyyy-MM-dd"), end.toString("yyyy-MM-dd")

    def _month_start_text(self) -> str:
        return self.selected_month.toString("yyyy-MM-dd")

    def _suggested_date(self) -> QDate:
        today = QDate.currentDate()
        if (self.selected_month.year(), self.selected_month.month()) == (today.year(), today.month()):
            return today
        return QDate(
            self.selected_month.year(),
            self.selected_month.month(),
            min(today.day(), self.selected_month.daysInMonth()),
        )

    def _update_month_navigation(self) -> None:
        self.month_label.setText(self.selected_month.toString("MMMM yyyy"))
        today = QDate.currentDate()
        current = QDate(today.year(), today.month(), 1)
        self.next_month_button.setEnabled(self.selected_month < current)

    def _previous_month(self) -> None:
        self.selected_month = self.selected_month.addMonths(-1)
        self._update_month_navigation()
        self.refresh()

    def _next_month(self) -> None:
        today = QDate.currentDate()
        current = QDate(today.year(), today.month(), 1)
        candidate = self.selected_month.addMonths(1)
        if candidate <= current:
            self.selected_month = candidate
            self._update_month_navigation()
            self.refresh()

    def _selected_worker(self):
        return self.service.get_worker(self._selected_id) if self._selected_id else None

    def _worker_selection_changed(self) -> None:
        previous_worker = self._selected_id
        rows = self.worker_table.selectionModel().selectedRows()
        if rows:
            item = self.worker_table.item(rows[0].row(), 0)
            self._selected_id = int(item.data(Qt.ItemDataRole.UserRole)) if item else None
        else:
            self._selected_id = None
        if self._selected_id != previous_worker:
            self._selected_activity = None
            self._activity_fallback_row = None
        self._refresh_selected_worker()

    def _activity_key(self) -> tuple[str, int] | None:
        rows = self.activity_table.selectionModel().selectedRows()
        if not rows:
            return None
        item = self.activity_table.item(rows[0].row(), 0)
        value = item.data(Qt.ItemDataRole.UserRole) if item else None
        if isinstance(value, tuple) and len(value) == 2:
            return str(value[0]), int(value[1])
        return None

    def _activity_selection_changed(self) -> None:
        key = self._activity_key()
        if key is not None:
            self._selected_activity = key
        enabled = key is not None
        self.edit_activity_button.setEnabled(enabled)
        self.delete_activity_button.setEnabled(enabled)

    def _show_feedback(self, message: str) -> None:
        self.feedback.setText(message)
        self.feedback.setVisible(bool(message))

    def refresh(self) -> None:
        previous = self._selected_id
        workers = self.service.list_workers(
            status=str(self.status_filter.currentData()),
            worker_type=str(self.type_filter.currentData()),
            search=self.search_edit.text(),
        )
        pending_id = self._pending_worker_delete[0] if self._pending_worker_delete is not None else None
        if pending_id is not None:
            workers = [worker for worker in workers if worker.id != pending_id]
        counts = self.service.counts()
        pending_active = bool(self._pending_worker_delete and self._pending_worker_delete[2])
        self.active_value.setText(str(max(0, counts.active - (1 if pending_active else 0))))

        self.worker_table.blockSignals(True)
        self.worker_table.setRowCount(len(workers))
        selected_row = -1
        for row, worker in enumerate(workers):
            name = QTableWidgetItem(worker.name)
            name.setData(Qt.ItemDataRole.UserRole, worker.id)
            name.setIcon(_status_dot_icon(worker.is_active))
            name.setToolTip("Active worker" if worker.is_active else "Inactive worker")
            worker_type = QTableWidgetItem(
                WORKER_TYPE_LABELS.get(worker.worker_type, worker.worker_type.title())
            )
            worker_type.setToolTip("Active worker" if worker.is_active else "Inactive worker")
            self.worker_table.setItem(row, 0, name)
            self.worker_table.setItem(row, 1, worker_type)
            if worker.id == previous:
                selected_row = row
        # Restore the worker selection while signals are blocked, then refresh the
        # selected-worker panel explicitly. Qt may not emit itemSelectionChanged
        # when the same row remains selected after the table is rebuilt; relying on
        # that signal left the activity list stale after adding work or payments.
        if selected_row >= 0:
            self.worker_table.selectRow(selected_row)
        else:
            if previous is not None:
                self._selected_id = None
                self._selected_activity = None
            self.worker_table.clearSelection()
        self.worker_table.blockSignals(False)
        self._refresh_selected_worker()

        self._refresh_payroll_overview()

    def _toggle_worker_details(self) -> None:
        if self._selected_worker() is None:
            return
        show = not self.worker_details_panel.isVisible()
        self.worker_details_panel.setVisible(show)
        self.worker_details_toggle.setArrowType(
            Qt.ArrowType.UpArrow if show else Qt.ArrowType.DownArrow
        )
        self.worker_details_toggle.setToolTip(
            "Hide worker profile details" if show else "Show all worker profile details"
        )
        self.worker_details_toggle.setAccessibleName(
            "Hide worker details" if show else "Show worker details"
        )

    def _update_worker_details(self, worker) -> None:
        if worker is None:
            for label in (
                self.detail_type, self.detail_status, self.detail_phone, self.detail_address,
                self.detail_notes, self.detail_payment_method, self.detail_rate,
                self.detail_date_added, self.detail_created, self.detail_updated,
            ):
                label.setText("—")
            self.worker_details_toggle.setEnabled(False)
            self.worker_details_panel.setVisible(False)
            self.worker_details_toggle.setArrowType(Qt.ArrowType.DownArrow)
            return

        method = PAYMENT_LABELS.get(worker.payment_method, worker.payment_method.title())
        rate = (
            format_minor(worker.normal_rate_minor, self.currency_code, self.currency_symbol)
            if worker.normal_rate_minor is not None
            else "—"
        )
        self.detail_type.setText(
            WORKER_TYPE_LABELS.get(worker.worker_type, worker.worker_type.title())
        )
        self.detail_status.setText("Active" if worker.is_active else "Inactive")
        self.detail_phone.setText(_display_value(worker.phone))
        self.detail_address.setText(_display_value(worker.address))
        self.detail_notes.setText(_display_value(worker.notes))
        self.detail_payment_method.setText(method)
        self.detail_rate.setText(rate)
        self.detail_date_added.setText(_display_value(worker.date_added))
        self.detail_created.setText(_display_value(worker.created_at))
        self.detail_updated.setText(_display_value(worker.updated_at))
        self.worker_details_toggle.setEnabled(True)

    def _refresh_selected_worker(self) -> None:
        worker = self._selected_worker()
        enabled = worker is not None
        for control in (
            self.edit_worker_button, self.active_worker_button, self.delete_worker_button,
            self.add_work_button, self.add_earning_button, self.add_payment_button,
            self.add_advance_button, self.carry_checkbox,
        ):
            control.setEnabled(enabled)

        if worker is None:
            self.worker_name.setText("Select a worker")
            self.worker_meta.setText("Choose a worker from the list.")
            self._update_worker_details(None)
            for label in (self.selected_earnings, self.selected_advances, self.selected_payments, self.selected_due):
                label.setText("—")
            self.activity_table.setRowCount(0)
            self._activity_selection_changed()
            return

        self.worker_name.setText(worker.name)
        self._update_worker_details(worker)
        method = PAYMENT_LABELS.get(worker.payment_method, worker.payment_method.title())
        status = "Active" if worker.is_active else "Inactive"
        rate = ""
        if worker.normal_rate_minor is not None:
            rate = " • " + format_minor(worker.normal_rate_minor, self.currency_code, self.currency_symbol)
        self.worker_meta.setText(
            f"{WORKER_TYPE_LABELS.get(worker.worker_type, worker.worker_type.title())} • {method}{rate} • {status}"
        )
        self.active_worker_button.setText("Deactivate" if worker.is_active else "Reactivate")
        for control in (self.add_work_button, self.add_earning_button, self.add_payment_button, self.add_advance_button):
            control.setEnabled(worker.is_active)

        if self.payroll_service is not None:
            summary = self.payroll_service.summary_for_worker(worker.id, self._month_start_text())
            self.selected_earnings.setText(format_minor(summary.earnings_minor, self.currency_code, self.currency_symbol))
            self.selected_advances.setText(format_minor(summary.advances_minor, self.currency_code, self.currency_symbol))
            self.selected_payments.setText(format_minor(summary.payments_minor, self.currency_code, self.currency_symbol))
            self.selected_due.setText(format_minor(summary.remaining_due_minor, self.currency_code, self.currency_symbol))
            self.carry_checkbox.blockSignals(True)
            self.carry_checkbox.setChecked(
                self.payroll_service.carry_forward_for_worker(worker.id, self._month_start_text())
            )
            self.carry_checkbox.blockSignals(False)
        self._refresh_activity()

    def _activity_palette(self, kind: str) -> tuple[QBrush, QBrush, QBrush]:
        """Theme-aware row and record-label brushes for Work vs Payment."""
        resolved = resolve_theme(_theme_name_from_widget(self))
        theme = THEMES[resolved]
        is_payment = kind == "payment"

        # Soft row tint keeps readability while the compact Record cell provides
        # the stronger visual distinction requested for the combined activity list.
        row_color = QColor(SAPPHIRE if is_payment else SCOOTER)
        row_color.setAlpha(34 if resolved == "light" else 52)
        badge_color = QColor(SAPPHIRE if is_payment else BLUE_LAGOON)
        badge_text = QColor(ALABASTER)
        return QBrush(row_color), QBrush(badge_color), QBrush(badge_text)

    def _refresh_activity(self) -> None:
        worker = self._selected_worker()
        if worker is None or self.work_service is None or self.payment_service is None:
            self.activity_table.setRowCount(0)
            return
        start, end = self._month_bounds()
        rows: list[tuple[str, str, int, str, str, int, bool]] = []
        for record in self.work_service.list_attendance_month(worker.id, start, end):
            rows.append((record.work_date, "attendance", record.id, attendance_duration_label(record), record.note or "—", record.amount_minor, False))
        for record in self.work_service.list_for_worker_month(worker.id, start, end):
            rows.append((record.start_date, "work", record.id, WORK_TYPE_LABELS.get(record.earning_type, record.earning_type.title()), record.description or "—", record.amount_minor, False))
        for record in self.payment_service.list_for_worker_month(worker.id, start, end):
            label = PAYMENT_TYPE_LABELS.get(record.payment_type, record.payment_type.title())
            rows.append((record.payment_date, "payment", record.id, label, record.note or "—", record.amount_minor, True))
        rows.sort(key=lambda value: (value[0], value[2]), reverse=True)
        previous = self._selected_activity
        self.activity_table.blockSignals(True)
        self.activity_table.setRowCount(len(rows))
        selected_row = -1
        for row, (date_text, kind, rid, label, note, amount_minor, outgoing) in enumerate(rows):
            date_item = QTableWidgetItem(date_text)
            date_item.setData(Qt.ItemDataRole.UserRole, (kind, rid))
            record_label = "Payment" if kind == "payment" else "Work"
            record_item = QTableWidgetItem(record_label)
            type_item = QTableWidgetItem(label)
            note_item = QTableWidgetItem(note)
            text = format_minor(amount_minor, self.currency_code, self.currency_symbol)
            if outgoing:
                text = "− " + text
            amount_item = QTableWidgetItem(text)
            amount_item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)

            row_brush, badge_brush, badge_text = self._activity_palette(kind)
            for item in (date_item, record_item, type_item, note_item, amount_item):
                item.setBackground(row_brush)
            record_item.setBackground(badge_brush)
            record_item.setForeground(badge_text)
            record_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)

            self.activity_table.setItem(row, 0, date_item)
            self.activity_table.setItem(row, 1, record_item)
            self.activity_table.setItem(row, 2, type_item)
            self.activity_table.setItem(row, 3, note_item)
            self.activity_table.setItem(row, 4, amount_item)
            if previous == (kind, rid):
                selected_row = row
        self.activity_table.blockSignals(False)

        if selected_row < 0 and rows and self._activity_fallback_row is not None:
            selected_row = min(self._activity_fallback_row, len(rows) - 1)
        self._activity_fallback_row = None

        if selected_row >= 0:
            self.activity_table.selectRow(selected_row)
        else:
            self._selected_activity = None
            self.activity_table.clearSelection()
        self._activity_selection_changed()

    def _refresh_payroll_overview(self) -> None:
        if self.payroll_service is None:
            self.payroll_table.setRowCount(0)
            return
        month_end = self.selected_month.addMonths(1).addDays(-1).toString("yyyy-MM-dd")
        workers = [w for w in self.service.list_workers(status="all", worker_type="all", search="") if w.date_added <= month_end and (self._pending_worker_delete is None or w.id != self._pending_worker_delete[0])]
        earnings = advances = payments = due = 0
        visible_ids = {w.id for w in workers}
        self._slip_worker_ids.intersection_update(visible_ids)
        self.payroll_table.blockSignals(True)
        self.payroll_table.setRowCount(len(workers))
        for row, worker in enumerate(workers):
            summary = self.payroll_service.summary_for_worker(worker.id, self._month_start_text())
            earnings += summary.earnings_minor
            advances += summary.advances_minor
            payments += summary.payments_minor
            due += summary.remaining_due_minor
            name = QTableWidgetItem(worker.name)
            name.setData(Qt.ItemDataRole.UserRole, worker.id)
            name.setFlags(name.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            name.setCheckState(Qt.CheckState.Checked if worker.id in self._slip_worker_ids else Qt.CheckState.Unchecked)
            self.payroll_table.setItem(row, 0, name)
            values = (
                WORKER_TYPE_LABELS.get(worker.worker_type, worker.worker_type.title()),
                format_minor(summary.earnings_minor, self.currency_code, self.currency_symbol),
                format_minor(summary.advances_minor, self.currency_code, self.currency_symbol),
                format_minor(summary.payments_minor, self.currency_code, self.currency_symbol),
                format_minor(summary.previous_unpaid_minor, self.currency_code, self.currency_symbol),
                format_minor(summary.remaining_due_minor, self.currency_code, self.currency_symbol),
                summary.status,
            )
            for col, value in enumerate(values, start=1):
                item = QTableWidgetItem(value)
                if 2 <= col <= 6:
                    item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
                self.payroll_table.setItem(row, col, item)
        self.payroll_table.blockSignals(False)
        self.earnings_value.setText(format_minor(earnings, self.currency_code, self.currency_symbol))
        self.given_value.setText(format_minor(advances + payments, self.currency_code, self.currency_symbol))
        self.due_value.setText(format_minor(due, self.currency_code, self.currency_symbol))
        self.generate_slips_button.setEnabled(self.salary_slip_service is not None and bool(workers))
        self._sync_check_all_slips()

    def _toggle_payroll_overview(self) -> None:
        visible = not self.payroll_table.isVisible()
        self.payroll_table.setVisible(visible)
        self.payroll_collapse_button.setText("Collapse ▲" if visible else "Expand ▼")

    def _payroll_item_changed(self, item: QTableWidgetItem) -> None:
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
        self._sync_check_all_slips()
        self.payroll_feedback.setVisible(False)

    def _visible_payroll_worker_ids(self) -> set[int]:
        worker_ids: set[int] = set()
        for row in range(self.payroll_table.rowCount()):
            item = self.payroll_table.item(row, 0)
            worker_id = item.data(Qt.ItemDataRole.UserRole) if item else None
            if worker_id is not None:
                worker_ids.add(int(worker_id))
        return worker_ids

    def _sync_check_all_slips(self) -> None:
        visible_ids = self._visible_payroll_worker_ids()
        all_checked = bool(visible_ids) and visible_ids.issubset(self._slip_worker_ids)
        self.check_all_slips.blockSignals(True)
        self.check_all_slips.setEnabled(bool(visible_ids))
        self.check_all_slips.setChecked(all_checked)
        self.check_all_slips.blockSignals(False)

    def _toggle_all_slips(self, checked: bool) -> None:
        visible_ids = self._visible_payroll_worker_ids()
        if checked:
            self._slip_worker_ids.update(visible_ids)
        else:
            self._slip_worker_ids.difference_update(visible_ids)
        self.payroll_table.blockSignals(True)
        for row in range(self.payroll_table.rowCount()):
            item = self.payroll_table.item(row, 0)
            if item is not None:
                item.setCheckState(Qt.CheckState.Checked if checked else Qt.CheckState.Unchecked)
        self.payroll_table.blockSignals(False)
        self.payroll_feedback.setVisible(False)

    def add_worker(self) -> None:
        dialog = WorkerDialog(self.service, self.currency_code, parent=self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self._show_feedback("Worker saved.")
            self.refresh()

    def edit_worker(self) -> None:
        worker = self._selected_worker()
        if worker is None:
            return
        dialog = WorkerDialog(self.service, self.currency_code, worker.id, self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            # Linked transaction descriptions include the worker name. Reconcile
            # immediately after profile edits so Transactions never keeps an old
            # worker name until the next restart/payment change.
            if self.payment_service is not None:
                try:
                    self.payment_service.reconcile_transaction_expenses()
                except ValueError as error:
                    self._show_feedback(
                        f"Worker updated, but linked expenses could not be refreshed: {error}"
                    )
                    self.refresh()
                    return
                self.linked_expenses_changed.emit()
            self._show_feedback("Worker updated.")
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
                self._show_feedback("Worker deactivated.")
            else:
                self.service.reactivate_worker(worker.id)
                self._show_feedback("Worker reactivated.")
        except WorkerError as error:
            self._show_feedback(str(error))
        self.refresh()

    def delete_worker_permanently(self) -> None:
        worker = self._selected_worker()
        if worker is None:
            return
        if self._pending_worker_delete is not None:
            self._show_feedback("Finish or undo the current worker deletion first.")
            return

        status = self.service.permanent_delete_status(worker.id)
        if status == "missing":
            self._show_feedback("That worker no longer exists.")
            self.refresh()
            return
        if status == "history":
            if _permanent_delete_blocked(self, worker.name, worker.is_active):
                try:
                    self.service.deactivate_worker(worker.id)
                except WorkerError as deactivate_error:
                    self._show_feedback(str(deactivate_error))
                    return
                self._show_feedback("Worker deactivated. Financial history was kept safely.")
                self.refresh()
            return

        if not _confirm_permanent_delete(self, worker.name):
            return

        # Delay the irreversible database delete for the normal ChitLog undo
        # window. The worker is hidden from this page immediately, but remains
        # intact in the database until the timer expires. Closing ChitLog during
        # the window therefore also leaves the worker safely undeleted.
        self._pending_worker_delete = (worker.id, worker.name, worker.is_active)
        self._selected_id = None
        self._selected_activity = None
        self.undo_button.setVisible(True)
        self.undo_button.setEnabled(True)
        self.worker_delete_timer.start(self.UNDO_MS)
        self._show_feedback("Worker removed — Undo Delete is available for 10 seconds.")
        self.refresh()

    def undo_worker_delete(self) -> None:
        if self._pending_worker_delete is None:
            return
        worker_name = self._pending_worker_delete[1]
        self.worker_delete_timer.stop()
        self._pending_worker_delete = None
        self.undo_button.setEnabled(False)
        self.undo_button.setVisible(False)
        self._show_feedback(f"Permanent deletion of {worker_name} was undone.")
        self.refresh()

    def _finalize_pending_worker_delete(self) -> None:
        pending = self._pending_worker_delete
        if pending is None:
            return
        worker_id, worker_name, _was_active = pending
        self._pending_worker_delete = None
        self.undo_button.setEnabled(False)
        self.undo_button.setVisible(False)
        try:
            self.service.delete_worker_permanently(worker_id)
        except WorkerError as error:
            self._show_feedback(str(error))
            self.refresh()
            return
        self._show_feedback(f"{worker_name} permanently deleted.")
        self.refresh()

    def add_work(self) -> None:
        worker = self._selected_worker()
        if worker is None or not worker.is_active or self.work_service is None:
            return
        dialog = WorkDayDialog(self.work_service, worker, self.currency_code, initial_date=self._suggested_date(), parent=self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self._show_feedback("Work record saved.")
            self.refresh()

    def add_earning(self) -> None:
        worker = self._selected_worker()
        if worker is None or not worker.is_active or self.work_service is None:
            return
        dialog = WorkRecordDialog(self.work_service, worker, self.currency_code, initial_date=self._suggested_date(), parent=self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self._show_feedback("Earning record saved.")
            self.refresh()

    def add_payment(self, advance: bool = False) -> None:
        worker = self._selected_worker()
        if worker is None or not worker.is_active or self.payment_service is None:
            return
        dialog = WorkerPaymentDialog(
            self.payment_service,
            worker,
            self.currency_code,
            initial_date=self._suggested_date(),
            force_type="advance" if advance else None,
            parent=self,
        )
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self._show_feedback("Advance saved." if advance else "Payment saved.")
            self.linked_expenses_changed.emit()
            self.refresh()

    def edit_activity(self) -> None:
        worker = self._selected_worker()
        key = self._activity_key()
        if worker is None or key is None:
            return
        kind, record_id = key
        if kind == "attendance":
            dialog = WorkDayDialog(self.work_service, worker, self.currency_code, attendance_id=record_id, parent=self)
        elif kind == "work":
            dialog = WorkRecordDialog(self.work_service, worker, self.currency_code, record_id=record_id, parent=self)
        else:
            dialog = WorkerPaymentDialog(self.payment_service, worker, self.currency_code, payment_id=record_id, parent=self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self._show_feedback("Record updated.")
            if kind == "payment":
                self.linked_expenses_changed.emit()
            self.refresh()

    def delete_activity(self) -> None:
        key = self._activity_key()
        if key is None:
            return
        kind, record_id = key
        dialog = QDialog(self)
        dialog.setWindowTitle("Delete Worker Record")
        dialog.setModal(True)
        _apply_dialog_theme(dialog, self)
        layout = QVBoxLayout(dialog)
        layout.setContentsMargins(SPACE["lg"], SPACE["lg"], SPACE["lg"], SPACE["lg"])
        layout.setSpacing(SPACE["md"])
        layout.addWidget(text_label("Delete this worker activity?", "heading"))
        layout.addWidget(text_label("The record will be removed from normal history. You can undo for 10 seconds."))
        actions = QHBoxLayout()
        actions.addStretch(1)
        cancel = button("Cancel")
        delete = button("Delete", "danger")
        actions.addWidget(cancel)
        actions.addWidget(delete)
        layout.addLayout(actions)
        cancel.clicked.connect(dialog.reject)
        delete.clicked.connect(dialog.accept)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        selected_rows = self.activity_table.selectionModel().selectedRows()
        self._activity_fallback_row = selected_rows[0].row() if selected_rows else None
        if kind == "attendance":
            changed = self.work_service.delete_attendance(record_id)
        elif kind == "work":
            changed = self.work_service.delete(record_id)
        else:
            changed = self.payment_service.delete(record_id)
        if changed:
            self._last_deleted = (kind, record_id)
            if kind == "payment":
                self.linked_expenses_changed.emit()
            self.activity_undo_button.setVisible(True)
            self.activity_undo_button.setEnabled(True)
            self.undo_timer.start(self.UNDO_MS)
            self._show_feedback("Record deleted — Undo available for 10 seconds.")
            self.refresh()

    def undo_delete(self) -> None:
        if self._last_deleted is None:
            return
        kind, record_id = self._last_deleted
        if kind == "attendance":
            changed = self.work_service.restore_attendance(record_id)
        elif kind == "work":
            changed = self.work_service.restore(record_id)
        else:
            changed = self.payment_service.restore(record_id)
        if changed and kind == "payment":
            self.linked_expenses_changed.emit()
        self._last_deleted = None
        self.undo_timer.stop()
        self.activity_undo_button.setEnabled(False)
        self.activity_undo_button.setVisible(False)
        self._show_feedback("Record restored." if changed else "Record could not be restored.")
        self.refresh()

    def _expire_undo(self) -> None:
        self._last_deleted = None
        self.activity_undo_button.setEnabled(False)
        self.activity_undo_button.setVisible(False)

    def _carry_changed(self, checked: bool) -> None:
        worker = self._selected_worker()
        if worker is None or self.payroll_service is None:
            return
        self.payroll_service.set_carry_forward(worker.id, self._month_start_text(), checked)
        self._show_feedback("Carry-forward setting updated.")
        self.refresh()

    def generate_salary_slips(self) -> None:
        if self.salary_slip_service is None:
            return
        if not self._slip_worker_ids:
            self.payroll_feedback.setProperty("role", "error")
            self.payroll_feedback.setText(
                "Select at least one worker using the checkbox (or Check all) before generating salary slips."
            )
            self.payroll_feedback.setVisible(True)
            self.payroll_feedback.style().unpolish(self.payroll_feedback)
            self.payroll_feedback.style().polish(self.payroll_feedback)
            return
        self.payroll_feedback.setVisible(False)
        default_name = f"ChitLog-Salary-Slips-{self.selected_month.toString('MMMM-yyyy')}.pdf"
        path, _ = QFileDialog.getSaveFileName(self, "Save Salary Slip PDF", default_name, "PDF files (*.pdf)")
        if not path:
            return
        if not path.lower().endswith(".pdf"):
            path += ".pdf"
        try:
            count = self.salary_slip_service.generate(path, sorted(self._slip_worker_ids), self._month_start_text())
        except SalarySlipError as error:
            self._show_feedback(str(error))
            return
        self._show_feedback(f"Saved {count} salary slip{'s' if count != 1 else ''}: {path}")
