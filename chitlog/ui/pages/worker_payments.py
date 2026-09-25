"""Worker payment and advance entry panel for Step 13."""
from __future__ import annotations

from PySide6.QtCore import QDate, QTimer, Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QDateEdit,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from chitlog.core.money import amount_text_from_minor, format_minor, minor_digits
from chitlog.services.worker_payment_service import (
    WorkerPaymentError,
    WorkerPaymentInput,
    WorkerPaymentService,
)
from chitlog.services.worker_service import WorkerRecord
from chitlog.ui.theme import SPACE, stylesheet
from chitlog.ui.widgets import button, text_label
from chitlog.ui.date_picker import configure_date_edit


PAYMENT_TYPE_LABELS = {
    "normal": "Normal Payment",
    "end_of_day": "End-of-Day Payment",
    "partial": "Partial Payment",
    "salary": "Salary Payment",
    "advance": "Advance",
}


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


def _confirm_delete(parent) -> bool:
    dialog = QDialog(parent)
    dialog.setWindowTitle("Delete Worker Payment")
    dialog.setModal(True)
    _apply_dialog_theme(dialog, parent)
    dialog.setMinimumWidth(500)
    layout = QVBoxLayout(dialog)
    layout.setContentsMargins(SPACE["lg"], SPACE["lg"], SPACE["lg"], SPACE["lg"])
    layout.setSpacing(SPACE["md"])
    layout.addWidget(text_label("Delete payment record?", "heading"))
    layout.addWidget(
        text_label(
            "This payment or advance will be removed from normal history. "
            "You can undo the deletion for 10 seconds."
        )
    )
    actions = QHBoxLayout()
    actions.addStretch(1)
    cancel = button("Cancel")
    delete = button("Delete Payment", "danger")
    actions.addWidget(cancel)
    actions.addWidget(delete)
    layout.addLayout(actions)
    cancel.clicked.connect(dialog.reject)
    delete.clicked.connect(dialog.accept)
    cancel.setDefault(True)
    return dialog.exec() == QDialog.DialogCode.Accepted


class InlineError(QLabel):
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


class WorkerPaymentDialog(QDialog):
    def __init__(
        self,
        service: WorkerPaymentService,
        worker: WorkerRecord,
        currency_code: str,
        payment_id: int | None = None,
        initial_date: QDate | None = None,
        force_type: str | None = None,
        parent=None,
    ):
        super().__init__(parent)
        self.service = service
        self.worker = worker
        self.currency_code = currency_code
        self.payment_id = payment_id
        self.force_type = force_type
        self.setWindowTitle("Edit Worker Payment" if payment_id else ("Add Advance" if force_type == "advance" else "Add Worker Payment"))
        self.setModal(True)
        _apply_dialog_theme(self, parent)
        self.resize(550, 430)

        root = QVBoxLayout(self)
        root.setContentsMargins(SPACE["lg"], SPACE["lg"], SPACE["lg"], SPACE["lg"])
        root.setSpacing(SPACE["md"])
        title = "Edit payment" if payment_id else ("Add advance" if force_type == "advance" else "Add payment")
        root.addWidget(text_label(title, "pageTitle"))
        root.addWidget(
            text_label(
                f"Worker: {worker.name}. This records money actually given to the worker.",
                "muted",
            )
        )
        self.error = InlineError()
        root.addWidget(self.error)

        minimum = QDate.fromString(worker.date_added, "yyyy-MM-dd")
        if not minimum.isValid():
            minimum = QDate(1900, 1, 1)
        suggested = initial_date if initial_date and initial_date.isValid() else QDate.currentDate()
        if suggested < minimum:
            suggested = minimum
        if suggested > QDate.currentDate():
            suggested = QDate.currentDate()

        form = QFormLayout()
        form.setHorizontalSpacing(SPACE["lg"])
        form.setVerticalSpacing(SPACE["md"])

        self.payment_date = QDateEdit(suggested)
        configure_date_edit(
            self.payment_date,
            minimum=minimum,
            maximum=QDate.currentDate(),
        )
        form.addRow("Payment date", self.payment_date)

        self.type_combo = QComboBox()
        if force_type == "advance":
            self.type_combo.addItem(PAYMENT_TYPE_LABELS["advance"], "advance")
            self.type_combo.setEnabled(False)
        else:
            self.type_combo.addItem(PAYMENT_TYPE_LABELS["normal"], "normal")
            self.type_combo.addItem(PAYMENT_TYPE_LABELS["end_of_day"], "end_of_day")
            self.type_combo.addItem(PAYMENT_TYPE_LABELS["partial"], "partial")
            self.type_combo.addItem(PAYMENT_TYPE_LABELS["salary"], "salary")
            self.type_combo.addItem(PAYMENT_TYPE_LABELS["advance"], "advance")
            if payment_id is None:
                preferred = "salary" if worker.payment_method == "monthly" else (
                    "end_of_day" if worker.payment_method == "daily" else "normal"
                )
                index = self.type_combo.findData(preferred)
                if index >= 0:
                    self.type_combo.setCurrentIndex(index)
        form.addRow("Payment type", self.type_combo)

        self.amount_edit = QLineEdit()
        digits = minor_digits(currency_code)
        self.amount_edit.setPlaceholderText("0" if digits == 0 else "0." + "0" * digits)
        self.amount_edit.setMaxLength(24)
        form.addRow(f"Amount ({currency_code})", self.amount_edit)

        self.note_edit = QLineEdit()
        self.note_edit.setPlaceholderText("Optional payment note")
        self.note_edit.setMaxLength(500)
        form.addRow("Note", self.note_edit)
        root.addLayout(form)

        root.addWidget(
            text_label(
                f"Available dates: {minimum.toString('yyyy-MM-dd')} through "
                f"{QDate.currentDate().toString('yyyy-MM-dd')}. Future dates are disabled. "
                "If an earlier payment is needed, edit the worker's Date Added first.",
                "muted",
            )
        )
        root.addWidget(
            text_label(
                "Advances are stored as one payment type and are not also counted as normal payments.",
                "muted",
            )
        )

        buttons = QDialogButtonBox()
        self.save_button = buttons.addButton("Save Payment", QDialogButtonBox.ButtonRole.AcceptRole)
        self.save_button.setProperty("role", "primary")
        buttons.addButton("Cancel", QDialogButtonBox.ButtonRole.RejectRole)
        buttons.accepted.connect(self.save)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)

        self.payment_date.dateChanged.connect(lambda *_: self.error.clear_message())
        self.type_combo.currentIndexChanged.connect(lambda *_: self.error.clear_message())
        self.amount_edit.textChanged.connect(lambda *_: self.error.clear_message())
        self.note_edit.textChanged.connect(lambda *_: self.error.clear_message())
        if payment_id is not None:
            self._load(payment_id)

    def _load(self, payment_id: int) -> None:
        record = self.service.get(payment_id)
        if record is None:
            self.error.show_message("That payment record no longer exists.")
            self.save_button.setEnabled(False)
            return
        value = QDate.fromString(record.payment_date, "yyyy-MM-dd")
        if value.isValid():
            self.payment_date.setDate(value)
        index = self.type_combo.findData(record.payment_type)
        if index >= 0:
            self.type_combo.setCurrentIndex(index)
        self.amount_edit.setText(amount_text_from_minor(record.amount_minor, self.currency_code))
        self.note_edit.setText(record.note)

    def save(self) -> None:
        self.error.clear_message()
        item = WorkerPaymentInput(
            payment_date=self.payment_date.date().toString("yyyy-MM-dd"),
            amount_text=self.amount_edit.text(),
            payment_type=self.type_combo.currentData(),
            note=self.note_edit.text(),
        )
        try:
            if self.payment_id is None:
                self.service.create(self.worker.id, item)
            else:
                self.service.update(self.payment_id, item)
        except WorkerPaymentError as error:
            self.error.show_message(str(error))
            return
        self.accept()


class WorkerPaymentsPanel(QWidget):
    UNDO_MS = 10_000

    def __init__(
        self,
        service: WorkerPaymentService,
        currency_code: str,
        currency_symbol: str,
        parent=None,
    ):
        super().__init__(parent)
        self.service = service
        self.currency_code = currency_code
        self.currency_symbol = currency_symbol
        self.worker: WorkerRecord | None = None
        today = QDate.currentDate()
        self.selected_month = QDate(today.year(), today.month(), 1)
        self.last_deleted_id: int | None = None
        self.undo_timer = QTimer(self)
        self.undo_timer.setSingleShot(True)
        self.undo_timer.timeout.connect(self._expire_undo)

        root = QVBoxLayout(self)
        root.setContentsMargins(0, SPACE["sm"], 0, 0)
        root.setSpacing(SPACE["sm"])

        header = QHBoxLayout()
        titles = QVBoxLayout()
        titles.setSpacing(SPACE["xs"])
        titles.addWidget(text_label("PAYMENTS & ADVANCES", "eyebrow"))
        self.title = text_label("Select a worker", "heading")
        titles.addWidget(self.title)
        self.summary = text_label("Payments: —   •   Advances: —   •   Total money given: —", "muted")
        titles.addWidget(self.summary)
        header.addLayout(titles, 1)

        self.add_payment_button = button("+ Payment", "primary")
        self.add_advance_button = button("+ Advance")
        self.edit_button = button("Edit Payment")
        self.delete_button = button("Delete Payment")
        self.undo_button = button("Undo Delete")
        for control in (self.add_payment_button, self.add_advance_button, self.edit_button, self.delete_button):
            control.setEnabled(False)
        self.undo_button.setVisible(False)
        header.addWidget(self.add_payment_button)
        header.addWidget(self.add_advance_button)
        header.addWidget(self.edit_button)
        header.addWidget(self.delete_button)
        header.addWidget(self.undo_button)
        root.addLayout(header)

        month_row = QHBoxLayout()
        month_row.setSpacing(SPACE["sm"])
        month_row.addStretch(1)
        self.previous_month_button = button("‹")
        self.previous_month_button.setFixedWidth(42)
        self.previous_month_button.setToolTip("Previous month")
        self.month_label = text_label("", "heading")
        self.month_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.month_label.setMinimumWidth(175)
        self.month_label.setWordWrap(False)
        self.next_month_button = button("›")
        self.next_month_button.setFixedWidth(42)
        self.next_month_button.setToolTip("Next month")
        month_row.addWidget(self.previous_month_button)
        month_row.addWidget(self.month_label)
        month_row.addWidget(self.next_month_button)
        month_row.addStretch(1)
        root.addLayout(month_row)

        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(("Date", "Payment Type", "Note", "Amount"))
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)
        head = self.table.horizontalHeader()
        head.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        head.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        head.setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        head.setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        self.table.setMinimumHeight(170)
        self.table.setMaximumHeight(300)
        root.addWidget(self.table)

        self.feedback = text_label(
            "Select a worker to view actual payments and advances for the selected month.",
            "muted",
        )
        root.addWidget(self.feedback)

        self.add_payment_button.clicked.connect(self.add_payment)
        self.add_advance_button.clicked.connect(self.add_advance)
        self.edit_button.clicked.connect(self.edit_payment)
        self.delete_button.clicked.connect(self.delete_payment)
        self.undo_button.clicked.connect(self.undo_delete)
        self.previous_month_button.clicked.connect(self._previous_month)
        self.next_month_button.clicked.connect(self._next_month)
        self.table.itemSelectionChanged.connect(self._selection_changed)
        self.table.itemDoubleClicked.connect(lambda *_: self.edit_payment())
        self._update_month_navigation()

    def set_worker(self, worker: WorkerRecord | None) -> None:
        changed = (self.worker.id if self.worker else None) != (worker.id if worker else None)
        self.worker = worker
        if changed:
            self.table.clearSelection()
        self.refresh()

    def set_month(self, month: QDate) -> None:
        if month.isValid():
            self.selected_month = QDate(month.year(), month.month(), 1)
            self._update_month_navigation()
            self.refresh()

    def _update_month_navigation(self) -> None:
        self.month_label.setText(self.selected_month.toString("MMMM yyyy"))
        today = QDate.currentDate()
        current_month = QDate(today.year(), today.month(), 1)
        self.previous_month_button.setEnabled(True)
        self.next_month_button.setEnabled(self.selected_month < current_month)

    def _previous_month(self) -> None:
        self.selected_month = self.selected_month.addMonths(-1)
        self._update_month_navigation()
        self.refresh()

    def _next_month(self) -> None:
        today = QDate.currentDate()
        current_month = QDate(today.year(), today.month(), 1)
        candidate = self.selected_month.addMonths(1)
        if candidate > current_month:
            return
        self.selected_month = candidate
        self._update_month_navigation()
        self.refresh()

    def _month_bounds(self) -> tuple[str, str]:
        start = self.selected_month
        end = start.addMonths(1).addDays(-1)
        return start.toString("yyyy-MM-dd"), end.toString("yyyy-MM-dd")

    def _suggested_date(self) -> QDate:
        today = QDate.currentDate()
        if self.selected_month.year() == today.year() and self.selected_month.month() == today.month():
            return today
        day = min(today.day(), self.selected_month.daysInMonth())
        return QDate(self.selected_month.year(), self.selected_month.month(), day)

    def _selected_id(self) -> int | None:
        rows = self.table.selectionModel().selectedRows()
        if not rows:
            return None
        item = self.table.item(rows[0].row(), 0)
        value = item.data(Qt.ItemDataRole.UserRole) if item else None
        return int(value) if value is not None else None

    def _selection_changed(self) -> None:
        selected = self._selected_id() is not None
        self.edit_button.setEnabled(selected)
        self.delete_button.setEnabled(selected)

    def refresh(self) -> None:
        self._update_month_navigation()
        worker = self.worker
        if worker is None:
            self.title.setText("Select a worker")
            self.summary.setText("Payments: —   •   Advances: —   •   Total money given: —")
            self.table.setRowCount(0)
            self.add_payment_button.setEnabled(False)
            self.add_advance_button.setEnabled(False)
            self._selection_changed()
            return

        month_text = self.selected_month.toString("MMMM yyyy")
        self.title.setText(f"{worker.name} — {month_text} payments")
        self.add_payment_button.setEnabled(True)
        self.add_advance_button.setEnabled(True)
        start_date, end_date = self._month_bounds()
        totals = self.service.month_totals(worker.id, start_date, end_date)
        self.summary.setText(
            "Payments: "
            + format_minor(totals.regular_payments_minor, self.currency_code, self.currency_symbol)
            + "   •   Advances: "
            + format_minor(totals.advances_minor, self.currency_code, self.currency_symbol)
            + "   •   Total money given: "
            + format_minor(totals.total_money_given_minor, self.currency_code, self.currency_symbol)
        )

        records = self.service.list_for_worker_month(worker.id, start_date, end_date)
        previous_id = self._selected_id()
        self.table.setRowCount(len(records))
        selected_row = -1
        for row, record in enumerate(records):
            date_item = QTableWidgetItem(record.payment_date)
            date_item.setData(Qt.ItemDataRole.UserRole, record.id)
            self.table.setItem(row, 0, date_item)
            self.table.setItem(row, 1, QTableWidgetItem(PAYMENT_TYPE_LABELS.get(record.payment_type, record.payment_type.title())))
            self.table.setItem(row, 2, QTableWidgetItem(record.note or "—"))
            amount = QTableWidgetItem(format_minor(record.amount_minor, self.currency_code, self.currency_symbol))
            amount.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            self.table.setItem(row, 3, amount)
            if previous_id == record.id:
                selected_row = row
        if selected_row >= 0:
            self.table.selectRow(selected_row)
        else:
            self.table.clearSelection()
        self._selection_changed()
        if records:
            self.feedback.setText(
                "Actual money given is recorded here. Advances are counted once, separately from other payments. Remaining due is added in Step 14."
            )
        else:
            self.feedback.setText(f"No payments or advances for {month_text}.")

    def add_payment(self) -> None:
        if self.worker is None:
            return
        dialog = WorkerPaymentDialog(
            self.service,
            self.worker,
            self.currency_code,
            initial_date=self._suggested_date(),
            parent=self,
        )
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self.feedback.setText("Worker payment saved.")
            self.refresh()

    def add_advance(self) -> None:
        if self.worker is None:
            return
        dialog = WorkerPaymentDialog(
            self.service,
            self.worker,
            self.currency_code,
            initial_date=self._suggested_date(),
            force_type="advance",
            parent=self,
        )
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self.feedback.setText("Worker advance saved.")
            self.refresh()

    def edit_payment(self) -> None:
        if self.worker is None:
            return
        payment_id = self._selected_id()
        if payment_id is None:
            return
        dialog = WorkerPaymentDialog(
            self.service,
            self.worker,
            self.currency_code,
            payment_id=payment_id,
            parent=self,
        )
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self.feedback.setText("Worker payment updated.")
            self.refresh()

    def delete_payment(self) -> None:
        payment_id = self._selected_id()
        if payment_id is None or not _confirm_delete(self):
            return
        if not self.service.delete(payment_id):
            self.feedback.setText("The worker payment could not be deleted.")
            self.refresh()
            return
        self.last_deleted_id = payment_id
        self.undo_timer.start(self.UNDO_MS)
        self.undo_button.setVisible(True)
        self.feedback.setText("Worker payment deleted. Undo is available for 10 seconds.")
        self.refresh()

    def undo_delete(self) -> None:
        if self.last_deleted_id is None:
            return
        payment_id = self.last_deleted_id
        if self.service.restore(payment_id):
            self.last_deleted_id = None
            self.undo_timer.stop()
            self.undo_button.setVisible(False)
            self.feedback.setText("Worker payment restored.")
            self.refresh()
        else:
            self.feedback.setText("The worker payment could not be restored.")

    def _expire_undo(self) -> None:
        self.last_deleted_id = None
        self.undo_button.setVisible(False)
