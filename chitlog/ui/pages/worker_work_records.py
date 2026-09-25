"""Monthly worker attendance and earning records for Step 12."""
from __future__ import annotations

from PySide6.QtCore import QDate, QTimer, Qt, Signal
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
from chitlog.services.worker_service import WorkerRecord
from chitlog.services.worker_work_service import (
    WorkerAttendanceInput,
    WorkerWorkError,
    WorkerWorkInput,
    WorkerWorkService,
    attendance_duration_label,
    format_hours_minutes,
)
from chitlog.ui.theme import SPACE, stylesheet
from chitlog.ui.widgets import button, text_label
from chitlog.ui.date_picker import configure_date_edit


WORK_TYPE_LABELS = {
    "job": "Per Job",
    "period": "Custom Period",
    "monthly": "Monthly Salary",
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


def _confirm_delete(parent, label: str) -> bool:
    dialog = QDialog(parent)
    dialog.setWindowTitle(f"Delete {label}")
    dialog.setModal(True)
    _apply_dialog_theme(dialog, parent)
    dialog.setMinimumWidth(500)
    layout = QVBoxLayout(dialog)
    layout.setContentsMargins(SPACE["lg"], SPACE["lg"], SPACE["lg"], SPACE["lg"])
    layout.setSpacing(SPACE["md"])
    layout.addWidget(text_label(f"Delete {label.lower()}?", "heading"))
    layout.addWidget(
        text_label(
            "This record will be removed from normal worker history. "
            "You can undo the deletion for 10 seconds."
        )
    )
    actions = QHBoxLayout()
    actions.addStretch(1)
    cancel = button("Cancel")
    delete = button(f"Delete {label}", "danger")
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


class WorkDayDialog(QDialog):
    """Fast attendance entry. Daily-paid workers also get their rate prefilled."""

    def __init__(
        self,
        service: WorkerWorkService,
        worker: WorkerRecord,
        currency_code: str,
        attendance_id: int | None = None,
        initial_date: QDate | None = None,
        parent=None,
    ):
        super().__init__(parent)
        self.service = service
        self.worker = worker
        self.currency_code = currency_code
        self.attendance_id = attendance_id
        self.setWindowTitle("Edit Work Record" if attendance_id else "Add Work Record")
        self.setModal(True)
        _apply_dialog_theme(self, parent)
        self.resize(540, 500)

        root = QVBoxLayout(self)
        root.setContentsMargins(SPACE["lg"], SPACE["lg"], SPACE["lg"], SPACE["lg"])
        root.setSpacing(SPACE["md"])
        root.addWidget(text_label("Edit work record" if attendance_id else "Add work record", "pageTitle"))
        root.addWidget(
            text_label(
                f"Worker: {worker.name}. Each date is one attendance/worked-day record.",
                "muted",
            )
        )
        self.error = InlineError()
        root.addWidget(self.error)

        minimum = QDate.fromString(worker.date_added, "yyyy-MM-dd")
        if not minimum.isValid():
            minimum = QDate(1900, 1, 1)

        form = QFormLayout()
        form.setHorizontalSpacing(SPACE["lg"])
        form.setVerticalSpacing(SPACE["md"])

        suggested = initial_date if initial_date and initial_date.isValid() else QDate.currentDate()
        if suggested < minimum:
            suggested = minimum
        if suggested > QDate.currentDate():
            suggested = QDate.currentDate()
        self.work_date = QDateEdit(suggested)
        configure_date_edit(
            self.work_date,
            minimum=minimum,
            maximum=QDate.currentDate(),
        )
        form.addRow("Worked date", self.work_date)

        self.duration_combo = QComboBox()
        self.duration_combo.addItem("Full day", "full_day")
        self.duration_combo.addItem("Half day", "half_day")
        self.duration_combo.addItem("Hours", "hours")
        form.addRow("Work duration", self.duration_combo)

        self.hours_edit = QLineEdit()
        self.hours_edit.setPlaceholderText("Example: 3.5")
        self.hours_edit.setMaxLength(6)
        form.addRow("Hours worked", self.hours_edit)
        self.hours_label = form.labelForField(self.hours_edit)

        self.amount_edit = QLineEdit()
        digits = minor_digits(currency_code)
        self.amount_edit.setPlaceholderText(
            "Optional — " + ("0" if digits == 0 else "0." + "0" * digits)
        )
        self.amount_edit.setMaxLength(24)
        form.addRow(f"Amount for this work record ({currency_code})", self.amount_edit)

        self.note_edit = QLineEdit()
        self.note_edit.setPlaceholderText("Optional attendance/work note")
        self.note_edit.setMaxLength(500)
        form.addRow("Note", self.note_edit)
        root.addLayout(form)
        root.addWidget(
            text_label(
                f"Available dates: {minimum.toString('yyyy-MM-dd')} through "
                f"{QDate.currentDate().toString('yyyy-MM-dd')}. Future dates are disabled. "
                "If earlier work is needed, edit the worker's Date Added first.",
                "muted",
            )
        )

        if worker.payment_method == "daily":
            hint = (
                "Full day suggests the normal daily rate. Half day suggests 50%. "
                "For Hours, enter the actual hours and amount; ChitLog does not assume "
                "how many hours make a normal day. You can edit any suggested amount."
            )
        else:
            hint = (
                "Duration records attendance detail. Leave the amount blank when this is "
                "attendance only; monthly/job/period earnings remain separate."
            )
        root.addWidget(text_label(hint, "muted"))

        buttons = QDialogButtonBox()
        self.save_button = buttons.addButton("Save Work Record", QDialogButtonBox.ButtonRole.AcceptRole)
        self.save_button.setProperty("role", "primary")
        buttons.addButton("Cancel", QDialogButtonBox.ButtonRole.RejectRole)
        buttons.accepted.connect(self.save)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)

        self._amount_suggestion_active = (
            attendance_id is None
            and worker.payment_method == "daily"
            and worker.normal_rate_minor is not None
        )
        self.work_date.dateChanged.connect(lambda *_: self.error.clear_message())
        self.duration_combo.currentIndexChanged.connect(self._duration_changed)
        self.hours_edit.textChanged.connect(lambda *_: self.error.clear_message())
        self.amount_edit.textEdited.connect(self._amount_manually_edited)
        self.amount_edit.textChanged.connect(lambda *_: self.error.clear_message())
        self.note_edit.textChanged.connect(lambda *_: self.error.clear_message())
        if attendance_id is not None:
            self._load(attendance_id)
        self._duration_changed()

    def _amount_manually_edited(self, *_args) -> None:
        self._amount_suggestion_active = False

    def _duration_changed(self, *_args) -> None:
        duration = self.duration_combo.currentData()
        hours_mode = duration == "hours"
        self.hours_edit.setVisible(hours_mode)
        if self.hours_label is not None:
            self.hours_label.setVisible(hours_mode)

        if (
            self._amount_suggestion_active
            and self.worker.payment_method == "daily"
            and self.worker.normal_rate_minor is not None
        ):
            if duration == "full_day":
                amount = int(self.worker.normal_rate_minor)
                self.amount_edit.setText(amount_text_from_minor(amount, self.currency_code))
            elif duration == "half_day":
                amount = (int(self.worker.normal_rate_minor) + 1) // 2
                self.amount_edit.setText(amount_text_from_minor(amount, self.currency_code))
            else:
                self.amount_edit.clear()
        self.error.clear_message()

    def _load(self, attendance_id: int) -> None:
        record = self.service.get_attendance(attendance_id)
        if record is None:
            self.error.show_message("That worked-day record no longer exists.")
            self.save_button.setEnabled(False)
            return
        value = QDate.fromString(record.work_date, "yyyy-MM-dd")
        if value.isValid():
            self.work_date.setDate(value)
        self._amount_suggestion_active = False
        duration_index = self.duration_combo.findData(record.duration_type)
        if duration_index >= 0:
            self.duration_combo.setCurrentIndex(duration_index)
        if record.hours_minutes:
            hours_value = record.hours_minutes / 60
            self.hours_edit.setText(f"{hours_value:g}")
        else:
            self.hours_edit.clear()
        if record.amount_minor:
            self.amount_edit.setText(amount_text_from_minor(record.amount_minor, self.currency_code))
        else:
            self.amount_edit.clear()
        self.note_edit.setText(record.note)

    def save(self) -> None:
        self.error.clear_message()
        item = WorkerAttendanceInput(
            self.work_date.date().toString("yyyy-MM-dd"),
            self.amount_edit.text(),
            self.note_edit.text(),
            self.duration_combo.currentData(),
            self.hours_edit.text(),
        )
        try:
            if self.attendance_id is None:
                self.service.create_attendance(self.worker.id, item)
            else:
                self.service.update_attendance(self.attendance_id, item)
        except WorkerWorkError as error:
            self.error.show_message(str(error))
            return
        self.accept()


class WorkRecordDialog(QDialog):
    """Non-attendance earning entry: job, custom period, or monthly salary."""

    def __init__(
        self,
        service: WorkerWorkService,
        worker: WorkerRecord,
        currency_code: str,
        record_id: int | None = None,
        initial_date: QDate | None = None,
        parent=None,
    ):
        super().__init__(parent)
        self.service = service
        self.worker = worker
        self.currency_code = currency_code
        self.record_id = record_id
        self.setWindowTitle("Edit Earning Record" if record_id else "Add Other Earning")
        self.setModal(True)
        _apply_dialog_theme(self, parent)
        self.resize(560, 470)

        root = QVBoxLayout(self)
        root.setContentsMargins(SPACE["lg"], SPACE["lg"], SPACE["lg"], SPACE["lg"])
        root.setSpacing(SPACE["md"])
        root.addWidget(text_label("Edit earning record" if record_id else "Add other earning", "pageTitle"))
        root.addWidget(
            text_label(
                f"Worker: {worker.name}. Use this for job, custom-period, or monthly salary earnings.",
                "muted",
            )
        )
        self.error = InlineError()
        root.addWidget(self.error)

        form = QFormLayout()
        form.setHorizontalSpacing(SPACE["lg"])
        form.setVerticalSpacing(SPACE["md"])

        self.type_combo = QComboBox()
        self.type_combo.addItem("Per job / work completed", "job")
        self.type_combo.addItem("Custom period earnings", "period")
        # Monthly workers get their fixed salary automatically from the worker
        # profile. Keep the monthly type only when editing a legacy explicit
        # monthly record so old data remains editable without double-counting.
        existing = self.service.get(record_id) if record_id is not None else None
        if existing is not None and existing.earning_type == "monthly":
            self.type_combo.addItem("Monthly salary override", "monthly")
        if worker.payment_method in {"job", "period"}:
            default_index = self.type_combo.findData(worker.payment_method)
            if default_index >= 0:
                self.type_combo.setCurrentIndex(default_index)
        form.addRow("Earning type", self.type_combo)

        minimum = QDate.fromString(worker.date_added, "yyyy-MM-dd")
        if not minimum.isValid():
            minimum = QDate(1900, 1, 1)
        suggested = initial_date if initial_date and initial_date.isValid() else QDate.currentDate()
        if suggested < minimum:
            suggested = minimum

        self.start_date = QDateEdit(suggested)
        configure_date_edit(
            self.start_date,
            minimum=minimum,
            maximum=QDate.currentDate(),
        )
        self.start_label = QLabel("Date")
        form.addRow(self.start_label, self.start_date)

        self.end_date = QDateEdit(suggested)
        configure_date_edit(
            self.end_date,
            minimum=minimum,
            maximum=QDate.currentDate(),
        )
        self.end_label = QLabel("End date")
        form.addRow(self.end_label, self.end_date)

        self.amount_edit = QLineEdit()
        digits = minor_digits(currency_code)
        self.amount_edit.setPlaceholderText("0" if digits == 0 else "0." + "0" * digits)
        self.amount_edit.setMaxLength(24)
        if record_id is None and worker.payment_method in {"job", "period"} and worker.normal_rate_minor is not None:
            self.amount_edit.setText(amount_text_from_minor(worker.normal_rate_minor, currency_code))
        form.addRow(f"Earnings ({currency_code})", self.amount_edit)

        self.description_edit = QLineEdit()
        self.description_edit.setPlaceholderText("Optional job/period/salary note")
        self.description_edit.setMaxLength(500)
        form.addRow("Description", self.description_edit)
        root.addLayout(form)
        root.addWidget(
            text_label(
                f"Available dates begin on {minimum.toString('yyyy-MM-dd')} (worker Date Added). "
                f"Future dates after {QDate.currentDate().toString('yyyy-MM-dd')} are disabled.",
                "muted",
            )
        )

        buttons = QDialogButtonBox()
        self.save_button = buttons.addButton("Save Earning", QDialogButtonBox.ButtonRole.AcceptRole)
        self.save_button.setProperty("role", "primary")
        buttons.addButton("Cancel", QDialogButtonBox.ButtonRole.RejectRole)
        buttons.accepted.connect(self.save)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)

        self.type_combo.currentIndexChanged.connect(self._sync_type_fields)
        self.start_date.dateChanged.connect(self._start_changed)
        self.amount_edit.textChanged.connect(lambda *_: self.error.clear_message())
        self.description_edit.textChanged.connect(lambda *_: self.error.clear_message())
        if record_id is not None:
            self._load(record_id)
        self._sync_type_fields()

    def _sync_type_fields(self) -> None:
        kind = self.type_combo.currentData()
        period = kind == "period"
        monthly = kind == "monthly"
        self.end_label.setVisible(period)
        self.end_date.setVisible(period)
        self.start_label.setText("Month" if monthly else ("Start date" if period else "Date"))
        self.start_date.setDisplayFormat("MMMM yyyy" if monthly else "yyyy-MM-dd")
        if not period:
            self.end_date.setDate(self.start_date.date())
        self.error.clear_message()

    def _start_changed(self, value: QDate) -> None:
        if self.end_date.date() < value:
            self.end_date.setDate(value)
        if self.type_combo.currentData() != "period":
            self.end_date.setDate(value)
        self.error.clear_message()

    def _load(self, record_id: int) -> None:
        record = self.service.get(record_id)
        if record is None:
            self.error.show_message("That earning record no longer exists.")
            self.save_button.setEnabled(False)
            return
        index = self.type_combo.findData(record.earning_type)
        if index >= 0:
            self.type_combo.setCurrentIndex(index)
        start = QDate.fromString(record.start_date, "yyyy-MM-dd")
        end = QDate.fromString(record.end_date, "yyyy-MM-dd")
        if start.isValid():
            self.start_date.setDate(start)
        if end.isValid():
            self.end_date.setDate(end)
        self.amount_edit.setText(amount_text_from_minor(record.amount_minor, self.currency_code))
        self.description_edit.setText(record.description)

    def save(self) -> None:
        self.error.clear_message()
        item = WorkerWorkInput(
            earning_type=self.type_combo.currentData(),
            start_date=self.start_date.date().toString("yyyy-MM-dd"),
            end_date=self.end_date.date().toString("yyyy-MM-dd"),
            amount_text=self.amount_edit.text(),
            description=self.description_edit.text(),
        )
        try:
            if self.record_id is None:
                self.service.create(self.worker.id, item)
            else:
                self.service.update(self.record_id, item)
        except WorkerWorkError as error:
            self.error.show_message(str(error))
            return
        self.accept()


class WorkerWorkPanel(QWidget):
    UNDO_MS = 10_000
    month_changed = Signal(QDate)

    def __init__(
        self,
        service: WorkerWorkService,
        currency_code: str,
        currency_symbol: str,
        parent=None,
    ):
        super().__init__(parent)
        self.service = service
        self.currency_code = currency_code
        self.currency_symbol = currency_symbol
        self.worker: WorkerRecord | None = None
        self.selected_month = QDate(QDate.currentDate().year(), QDate.currentDate().month(), 1)
        self.last_deleted: tuple[str, int] | None = None
        self.undo_timer = QTimer(self)
        self.undo_timer.setSingleShot(True)
        self.undo_timer.timeout.connect(self._expire_undo)

        root = QVBoxLayout(self)
        root.setContentsMargins(0, SPACE["sm"], 0, 0)
        root.setSpacing(SPACE["sm"])

        header = QHBoxLayout()
        titles = QVBoxLayout()
        titles.setSpacing(SPACE["xs"])
        titles.addWidget(text_label("WORK RECORDS", "eyebrow"))
        self.title = text_label("Select a worker", "heading")
        titles.addWidget(self.title)
        self.month_summary = text_label("Worked days: —   •   Amount to pay: —", "muted")
        titles.addWidget(self.month_summary)
        header.addLayout(titles, 1)

        self.add_day_button = button("+ Work Record", "primary")
        self.add_earning_button = button("+ Other Earning")
        self.edit_button = button("Edit Record")
        self.delete_button = button("Delete Record")
        self.undo_button = button("Undo Delete")
        self.add_day_button.setEnabled(False)
        self.add_earning_button.setEnabled(False)
        self.edit_button.setEnabled(False)
        self.delete_button.setEnabled(False)
        self.undo_button.setVisible(False)
        header.addWidget(self.add_day_button)
        header.addWidget(self.add_earning_button)
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
        self.table.setHorizontalHeaderLabels(("Date / Period", "Record", "Description", "Earnings"))
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)
        head = self.table.horizontalHeader()
        head.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        head.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        head.setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        head.setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        self.table.setMinimumHeight(190)
        self.table.setMaximumHeight(330)
        root.addWidget(self.table)

        self.feedback = text_label("Select a worker to view monthly attendance and earnings.", "muted")
        root.addWidget(self.feedback)

        self.add_day_button.clicked.connect(self.add_worked_day)
        self.add_earning_button.clicked.connect(self.add_earning)
        self.edit_button.clicked.connect(self.edit_record)
        self.delete_button.clicked.connect(self.delete_record)
        self.undo_button.clicked.connect(self.undo_delete)
        self.previous_month_button.clicked.connect(self._previous_month)
        self.next_month_button.clicked.connect(self._next_month)
        self.table.itemSelectionChanged.connect(self._selection_changed)
        self.table.itemDoubleClicked.connect(lambda *_: self.edit_record())
        self._update_month_navigation()

    def set_worker(self, worker: WorkerRecord | None) -> None:
        changed = (self.worker.id if self.worker else None) != (worker.id if worker else None)
        self.worker = worker
        if changed:
            self.table.clearSelection()
        self.refresh()

    def _month_bounds(self) -> tuple[str, str]:
        start = self.selected_month
        end = start.addMonths(1).addDays(-1)
        return start.toString("yyyy-MM-dd"), end.toString("yyyy-MM-dd")

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
        self.month_changed.emit(self.selected_month)

    def _next_month(self) -> None:
        today = QDate.currentDate()
        current_month = QDate(today.year(), today.month(), 1)
        candidate = self.selected_month.addMonths(1)
        if candidate > current_month:
            return
        self.selected_month = candidate
        self._update_month_navigation()
        self.refresh()
        self.month_changed.emit(self.selected_month)

    def _suggested_date(self) -> QDate:
        today = QDate.currentDate()
        if self.selected_month.year() == today.year() and self.selected_month.month() == today.month():
            return today
        day = min(today.day(), self.selected_month.daysInMonth())
        return QDate(self.selected_month.year(), self.selected_month.month(), day)

    def _selected_key(self) -> tuple[str, int] | None:
        rows = self.table.selectionModel().selectedRows()
        if not rows:
            return None
        item = self.table.item(rows[0].row(), 0)
        value = item.data(Qt.ItemDataRole.UserRole) if item else None
        if isinstance(value, tuple) and len(value) == 2:
            return str(value[0]), int(value[1])
        return None

    def _selection_changed(self) -> None:
        selected = self._selected_key() is not None
        self.edit_button.setEnabled(selected)
        self.delete_button.setEnabled(selected)

    @staticmethod
    def _period_text(record) -> str:
        if record.earning_type == "monthly":
            value = QDate.fromString(record.start_date, "yyyy-MM-dd")
            return value.toString("MMMM yyyy") if value.isValid() else record.start_date
        if record.start_date == record.end_date:
            return record.start_date
        return f"{record.start_date} → {record.end_date}"

    @staticmethod
    def _attendance_summary_text(summary) -> str:
        parts = []
        if summary.full_days:
            parts.append(
                f"{summary.full_days} full day" + ("" if summary.full_days == 1 else "s")
            )
        if summary.half_days:
            parts.append(
                f"{summary.half_days} half day" + ("" if summary.half_days == 1 else "s")
            )
        if summary.hourly_minutes:
            parts.append(format_hours_minutes(summary.hourly_minutes))
        return " • ".join(parts) if parts else "No attendance"

    def refresh(self) -> None:
        worker = self.worker
        self._update_month_navigation()
        if worker is None:
            self.title.setText("Select a worker")
            self.month_summary.setText("Worked days: —   •   Amount to pay: —")
            self.add_day_button.setEnabled(False)
            self.add_earning_button.setEnabled(False)
            self.table.setRowCount(0)
            self._selection_changed()
            return

        self.title.setText(f"{worker.name} — monthly work")
        start_date, end_date = self._month_bounds()
        summary = self.service.month_summary(worker.id, start_date, end_date)
        attendance_text = self._attendance_summary_text(summary)
        if worker.payment_method == "monthly":
            extras = summary.attendance_amount_minor + summary.other_earnings_minor
            self.month_summary.setText(
                f"Attendance: {attendance_text}   •   Fixed salary: "
                + format_minor(summary.fixed_salary_minor, self.currency_code, self.currency_symbol)
                + "   •   Extra earnings: "
                + format_minor(extras, self.currency_code, self.currency_symbol)
                + "   •   Amount to pay: "
                + format_minor(summary.amount_to_pay_minor, self.currency_code, self.currency_symbol)
            )
        else:
            self.month_summary.setText(
                f"Attendance: {attendance_text}   •   Amount to pay: "
                + format_minor(summary.amount_to_pay_minor, self.currency_code, self.currency_symbol)
            )
        self.add_day_button.setEnabled(worker.is_active)
        self.add_earning_button.setEnabled(worker.is_active)
        inactive_tip = "Reactivate this worker before adding new records."
        self.add_day_button.setToolTip("Add a dated work/attendance record" if worker.is_active else inactive_tip)
        self.add_earning_button.setToolTip("Add other earning" if worker.is_active else inactive_tip)

        attendance = self.service.list_attendance_month(worker.id, start_date, end_date)
        earnings = self.service.list_for_worker_month(worker.id, start_date, end_date)
        rows: list[tuple[str, str, int, str, str, int]] = []
        for record in attendance:
            rows.append(
                (
                    record.work_date,
                    "attendance",
                    record.id,
                    attendance_duration_label(record),
                    record.note or "—",
                    record.amount_minor,
                )
            )
        for record in earnings:
            rows.append(
                (
                    record.start_date,
                    "work",
                    record.id,
                    WORK_TYPE_LABELS.get(record.earning_type, record.earning_type.title()),
                    record.description or "—",
                    record.amount_minor,
                )
            )
        rows.sort(key=lambda value: (value[0], value[2]), reverse=True)

        previous_key = self._selected_key()
        self.table.setRowCount(len(rows))
        selected_row = -1
        attendance_by_id = {record.id: record for record in attendance}
        earnings_by_id = {record.id: record for record in earnings}
        for row, (sort_date, kind, record_id, label, description, amount_minor) in enumerate(rows):
            if kind == "attendance":
                display_period = attendance_by_id[record_id].work_date
            else:
                display_period = self._period_text(earnings_by_id[record_id])
            period = QTableWidgetItem(display_period)
            period.setData(Qt.ItemDataRole.UserRole, (kind, record_id))
            self.table.setItem(row, 0, period)
            self.table.setItem(row, 1, QTableWidgetItem(label))
            self.table.setItem(row, 2, QTableWidgetItem(description))
            amount_text = (
                format_minor(amount_minor, self.currency_code, self.currency_symbol)
                if amount_minor
                else "—"
            )
            amount = QTableWidgetItem(amount_text)
            amount.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            self.table.setItem(row, 3, amount)
            if previous_key == (kind, record_id):
                selected_row = row
        if selected_row >= 0:
            self.table.selectRow(selected_row)
        else:
            self.table.clearSelection()
        self._selection_changed()
        if not rows:
            self.feedback.setText(f"No records for {self.selected_month.toString('MMMM yyyy')}.")
        else:
            self.feedback.setText(
                "Work records track full days, half days, and hourly attendance. Daily workers use the saved/edited work-record amount; monthly workers include fixed salary plus extra earnings."
            )

    def add_worked_day(self) -> None:
        if self.worker is None or not self.worker.is_active:
            return
        dialog = WorkDayDialog(
            self.service,
            self.worker,
            self.currency_code,
            initial_date=self._suggested_date(),
            parent=self,
        )
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self.feedback.setText("Work record saved.")
            self.refresh()

    def add_earning(self) -> None:
        if self.worker is None or not self.worker.is_active:
            return
        dialog = WorkRecordDialog(
            self.service,
            self.worker,
            self.currency_code,
            initial_date=self._suggested_date(),
            parent=self,
        )
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self.feedback.setText("Earning record saved.")
            self.refresh()

    def edit_record(self) -> None:
        if self.worker is None:
            return
        key = self._selected_key()
        if key is None:
            return
        kind, record_id = key
        if kind == "attendance":
            dialog = WorkDayDialog(
                self.service,
                self.worker,
                self.currency_code,
                attendance_id=record_id,
                parent=self,
            )
        else:
            dialog = WorkRecordDialog(
                self.service,
                self.worker,
                self.currency_code,
                record_id=record_id,
                parent=self,
            )
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self.feedback.setText("Worker record updated.")
            self.refresh()

    def delete_record(self) -> None:
        key = self._selected_key()
        if key is None:
            return
        kind, record_id = key
        label = "Work Record" if kind == "attendance" else "Earning Record"
        if not _confirm_delete(self, label):
            return
        deleted = (
            self.service.delete_attendance(record_id)
            if kind == "attendance"
            else self.service.delete(record_id)
        )
        if not deleted:
            self.feedback.setText("The worker record could not be deleted.")
            self.refresh()
            return
        self.last_deleted = (kind, record_id)
        self.undo_timer.start(self.UNDO_MS)
        self.undo_button.setVisible(True)
        self.feedback.setText("Worker record deleted. Undo is available for 10 seconds.")
        self.refresh()

    def undo_delete(self) -> None:
        if self.last_deleted is None:
            return
        kind, record_id = self.last_deleted
        try:
            restored = (
                self.service.restore_attendance(record_id)
                if kind == "attendance"
                else self.service.restore(record_id)
            )
        except WorkerWorkError as error:
            self.feedback.setText(str(error))
            return
        if restored:
            self.last_deleted = None
            self.undo_timer.stop()
            self.undo_button.setVisible(False)
            self.feedback.setText("Worker record restored.")
            self.refresh()
        else:
            self.feedback.setText("The worker record could not be restored.")

    def _expire_undo(self) -> None:
        self.last_deleted = None
        self.undo_button.setVisible(False)
