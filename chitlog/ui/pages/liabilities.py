"""Step 10 liabilities and simple loan-payment UI."""
from __future__ import annotations

from PySide6.QtCore import QDate, QTimer, Qt, Signal
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
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
    QTableWidget,
    QTableWidgetItem,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from chitlog.core.money import amount_text_from_minor, format_minor, minor_digits
from chitlog.services.liability_service import (
    LiabilityError,
    LiabilityInput,
    LiabilityPaymentInput,
    LiabilityService,
)
from chitlog.ui.theme import SPACE, stylesheet
from chitlog.ui.widgets import Card, button, text_label


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


def _confirm_delete(parent, liability_name: str) -> str | None:
    """Ask how linked Transaction expense history should be handled."""
    dialog = QDialog(parent)
    dialog.setWindowTitle("Delete Liability")
    dialog.setModal(True)
    _apply_dialog_theme(dialog, parent)
    dialog.setMinimumWidth(590)

    layout = QVBoxLayout(dialog)
    layout.setContentsMargins(SPACE["lg"], SPACE["lg"], SPACE["lg"], SPACE["lg"])
    layout.setSpacing(SPACE["md"])
    layout.addWidget(text_label("Delete liability?", "heading"))
    message = text_label(
        f'“{liability_name}” will be removed from the Liabilities list and totals. '
        "Choose what should happen to the linked liability-payment expenses in Transactions. "
        "The liability and payment records are retained internally so this deletion can be undone for 10 seconds."
    )
    message.setWordWrap(True)
    layout.addWidget(message)

    keep_note = text_label(
        "Keep Transaction History — linked payment expenses stay visible in Transactions.",
        "muted",
    )
    keep_note.setWordWrap(True)
    layout.addWidget(keep_note)
    delete_note = text_label(
        "Delete Transaction History — linked payment expenses are removed from normal Transaction history.",
        "muted",
    )
    delete_note.setWordWrap(True)
    layout.addWidget(delete_note)

    choice = {"value": None}
    actions = QHBoxLayout()
    actions.addStretch(1)
    cancel = button("Cancel")
    keep = button("Keep Transaction History")
    delete_history = button("Delete Transaction History", "danger")
    actions.addWidget(cancel)
    actions.addWidget(keep)
    actions.addWidget(delete_history)
    layout.addLayout(actions)

    def choose(value: str) -> None:
        choice["value"] = value
        dialog.accept()

    cancel.clicked.connect(dialog.reject)
    keep.clicked.connect(lambda: choose("keep"))
    delete_history.clicked.connect(lambda: choose("delete"))
    cancel.setDefault(True)
    if dialog.exec() != QDialog.DialogCode.Accepted:
        return None
    return str(choice["value"]) if choice["value"] else None


class InlineMessage(QLabel):
    def __init__(self):
        super().__init__("")
        self.setProperty("role", "error")
        self.setWordWrap(True)
        self.setMinimumHeight(24)
        self.setVisible(False)

    def show_message(self, message: str) -> None:
        self.setText(message)
        self.setVisible(True)

    def clear_message(self) -> None:
        self.clear()
        self.setVisible(False)


class LiabilityDialog(QDialog):
    def __init__(
        self,
        service: LiabilityService,
        currency_code: str,
        liability_id: int | None = None,
        parent=None,
    ):
        super().__init__(parent)
        self.service = service
        self.currency_code = currency_code
        self.liability_id = liability_id
        self.setWindowTitle("Edit Liability" if liability_id else "Add Liability")
        self.setModal(True)
        _apply_dialog_theme(self, parent)
        self.resize(560, 580)

        root = QVBoxLayout(self)
        root.setContentsMargins(SPACE["lg"], SPACE["lg"], SPACE["lg"], SPACE["lg"])
        root.setSpacing(SPACE["md"])
        root.addWidget(text_label("Edit liability" if liability_id else "Add liability", "pageTitle"))
        root.addWidget(
            text_label(
                "Track a simple debt or loan. Interest schedules are intentionally outside V1.",
                "muted",
            )
        )
        self.error = InlineMessage()
        root.addWidget(self.error)

        form = QFormLayout()
        form.setHorizontalSpacing(SPACE["lg"])
        form.setVerticalSpacing(SPACE["md"])

        self.name_edit = QLineEdit()
        self.name_edit.setPlaceholderText("Example: Vehicle loan")
        self.name_edit.setMaxLength(120)
        form.addRow("Name", self.name_edit)

        self.lender_edit = QLineEdit()
        self.lender_edit.setPlaceholderText("Optional lender or person")
        self.lender_edit.setMaxLength(120)
        form.addRow("Lender", self.lender_edit)

        self.amount_edit = QLineEdit()
        digits = minor_digits(currency_code)
        self.amount_edit.setPlaceholderText("0" if digits == 0 else "0." + "0" * digits)
        self.amount_edit.setMaxLength(24)
        form.addRow(f"Original amount ({currency_code})", self.amount_edit)

        self.start_date = QDateEdit(QDate.currentDate())
        self.start_date.setCalendarPopup(True)
        self.start_date.setDisplayFormat("yyyy-MM-dd")
        self.start_date.setMinimumWidth(150)
        form.addRow("Start date", self.start_date)

        due_row = QWidget()
        due_layout = QHBoxLayout(due_row)
        due_layout.setContentsMargins(0, 0, 0, 0)
        due_layout.setSpacing(SPACE["sm"])
        self.has_due_date = QCheckBox("Set due date")
        self.due_date = QDateEdit(QDate.currentDate())
        self.due_date.setCalendarPopup(True)
        self.due_date.setDisplayFormat("yyyy-MM-dd")
        self.due_date.setMinimumWidth(150)
        self.due_date.setEnabled(False)
        due_layout.addWidget(self.has_due_date)
        due_layout.addWidget(self.due_date)
        due_layout.addStretch(1)
        form.addRow("Due", due_row)

        self.notes_edit = QTextEdit()
        self.notes_edit.setPlaceholderText("Optional notes")
        self.notes_edit.setMaximumHeight(110)
        form.addRow("Notes", self.notes_edit)
        root.addLayout(form)

        self.buttons = QDialogButtonBox()
        self.save_button = self.buttons.addButton(
            "Save Liability", QDialogButtonBox.ButtonRole.AcceptRole
        )
        self.save_button.setProperty("role", "primary")
        self.buttons.addButton("Cancel", QDialogButtonBox.ButtonRole.RejectRole)
        self.buttons.accepted.connect(self.save)
        self.buttons.rejected.connect(self.reject)
        root.addWidget(self.buttons)

        self.has_due_date.toggled.connect(self.due_date.setEnabled)
        self.name_edit.textChanged.connect(lambda *_: self.error.clear_message())
        self.amount_edit.textChanged.connect(lambda *_: self.error.clear_message())
        self.start_date.dateChanged.connect(lambda *_: self.error.clear_message())
        self.due_date.dateChanged.connect(lambda *_: self.error.clear_message())
        if liability_id is not None:
            self._load_existing(liability_id)

    def _load_existing(self, liability_id: int) -> None:
        item = self.service.get_summary(liability_id)
        if item is None:
            self.error.show_message("This liability no longer exists.")
            self.save_button.setEnabled(False)
            return
        self.name_edit.setText(item.name)
        self.lender_edit.setText(item.lender)
        self.amount_edit.setText(amount_text_from_minor(item.original_amount_minor, self.currency_code))
        start = QDate.fromString(item.start_date, "yyyy-MM-dd")
        if start.isValid():
            self.start_date.setDate(start)
        if item.due_date:
            due = QDate.fromString(item.due_date, "yyyy-MM-dd")
            self.has_due_date.setChecked(True)
            if due.isValid():
                self.due_date.setDate(due)
        self.notes_edit.setPlainText(item.notes)

    def _input(self) -> LiabilityInput:
        return LiabilityInput(
            name=self.name_edit.text(),
            lender=self.lender_edit.text(),
            original_amount=self.amount_edit.text(),
            start_date=self.start_date.date().toString("yyyy-MM-dd"),
            due_date=self.due_date.date().toString("yyyy-MM-dd") if self.has_due_date.isChecked() else None,
            notes=self.notes_edit.toPlainText(),
        )

    def save(self) -> None:
        self.error.clear_message()
        try:
            if self.liability_id is None:
                self.service.create_liability(self._input())
            else:
                self.service.update_liability(self.liability_id, self._input())
        except LiabilityError as error:
            self.error.show_message(str(error))
            return
        self.accept()


class LiabilityPaymentDialog(QDialog):
    def __init__(
        self,
        service: LiabilityService,
        liability_id: int,
        currency_code: str,
        currency_symbol: str,
        payment_id: int | None = None,
        parent=None,
    ):
        super().__init__(parent)
        self.service = service
        self.liability_id = liability_id
        self.payment_id = payment_id
        self.currency_code = currency_code
        self.currency_symbol = currency_symbol
        summary = service.get_summary(liability_id)
        self.setWindowTitle("Edit Liability Payment" if payment_id is not None else "Record Liability Payment")
        self.setModal(True)
        _apply_dialog_theme(self, parent)
        self.resize(500, 390)

        root = QVBoxLayout(self)
        root.setContentsMargins(SPACE["lg"], SPACE["lg"], SPACE["lg"], SPACE["lg"])
        root.setSpacing(SPACE["md"])
        root.addWidget(text_label("Edit payment" if payment_id is not None else "Record payment", "pageTitle"))
        if summary is not None:
            root.addWidget(text_label(summary.name, "heading"))
            root.addWidget(
                text_label(
                    f"Remaining balance: {format_minor(summary.remaining_minor, currency_code, currency_symbol)}",
                    "muted",
                )
            )
        self.error = InlineMessage()
        root.addWidget(self.error)

        form = QFormLayout()
        form.setHorizontalSpacing(SPACE["lg"])
        form.setVerticalSpacing(SPACE["md"])
        self.payment_date = QDateEdit(QDate.currentDate())
        self.payment_date.setCalendarPopup(True)
        self.payment_date.setDisplayFormat("yyyy-MM-dd")
        self.payment_date.setMinimumWidth(150)
        if summary is not None:
            start = QDate.fromString(summary.start_date, "yyyy-MM-dd")
            if start.isValid():
                self.payment_date.setMinimumDate(start)
                if self.payment_date.date() < start:
                    self.payment_date.setDate(start)
        form.addRow("Payment date", self.payment_date)

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

        buttons = QDialogButtonBox()
        save = buttons.addButton(
            "Save Changes" if payment_id is not None else "Save Payment",
            QDialogButtonBox.ButtonRole.AcceptRole,
        )
        save.setProperty("role", "primary")
        buttons.addButton("Cancel", QDialogButtonBox.ButtonRole.RejectRole)
        buttons.accepted.connect(self.save)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)

        self.amount_edit.textChanged.connect(lambda *_: self.error.clear_message())
        if payment_id is not None:
            self._load_existing(payment_id)

    def _load_existing(self, payment_id: int) -> None:
        payment = self.service.get_payment(payment_id)
        if payment is None or payment.liability_id != self.liability_id:
            self.error.show_message("This liability payment no longer exists.")
            return
        payment_date = QDate.fromString(payment.payment_date, "yyyy-MM-dd")
        if payment_date.isValid():
            self.payment_date.setDate(payment_date)
        self.amount_edit.setText(amount_text_from_minor(payment.amount_minor, self.currency_code))
        self.note_edit.setText(payment.note)

    def _input(self) -> LiabilityPaymentInput:
        return LiabilityPaymentInput(
            payment_date=self.payment_date.date().toString("yyyy-MM-dd"),
            amount=self.amount_edit.text(),
            note=self.note_edit.text(),
        )

    def save(self) -> None:
        self.error.clear_message()
        try:
            if self.payment_id is None:
                self.service.add_payment(self.liability_id, self._input())
            else:
                self.service.update_payment(self.payment_id, self._input())
        except LiabilityError as error:
            self.error.show_message(str(error))
            return
        self.accept()


class LiabilitiesPage(QWidget):
    open_count_changed = Signal(int)
    linked_expenses_changed = Signal()

    def __init__(
        self,
        service: LiabilityService,
        currency_code: str,
        currency_symbol: str,
        parent=None,
    ):
        super().__init__(parent)
        self.service = service
        self.currency_code = currency_code
        self.currency_symbol = currency_symbol
        self._liability_ids: list[int] = []
        self._payment_ids: list[int] = []
        self._last_deleted_id: int | None = None
        self._undo_delete_timer = QTimer(self)
        self._undo_delete_timer.setSingleShot(True)
        self._undo_delete_timer.setInterval(10_000)
        self._undo_delete_timer.timeout.connect(self._expire_delete_undo)
        self._last_deleted_payment_id: int | None = None
        self._payment_undo_timer = QTimer(self)
        self._payment_undo_timer.setSingleShot(True)
        self._payment_undo_timer.setInterval(10_000)
        self._payment_undo_timer.timeout.connect(self._expire_payment_undo)

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(SPACE["md"])

        # Page identity stays clean and uncluttered. Record actions belong with
        # the liabilities table they operate on rather than beside the title.
        intro_text_widget = QWidget()
        intro_text_widget.setMinimumWidth(0)
        intro_text = QVBoxLayout(intro_text_widget)
        intro_text.setContentsMargins(0, 0, 0, 0)
        intro_text.setSpacing(SPACE["xs"])
        intro_text.addWidget(text_label("LIABILITIES", "eyebrow"))
        intro_text.addWidget(text_label("Loans and debts", "pageTitle"))
        intro_text.addWidget(
            text_label(
                "Track original amounts, payments, and remaining balances without complex interest calculations.",
                "muted",
            )
        )
        root.addWidget(intro_text_widget)

        # Compact summary strip. These keep the existing typography/colors but
        # reduce padding and vertical footprint to match the denser ChitLog UI.
        summary_grid = QGridLayout()
        summary_grid.setContentsMargins(0, SPACE["xs"], 0, SPACE["xs"])
        summary_grid.setHorizontalSpacing(SPACE["md"])
        summary_grid.setVerticalSpacing(SPACE["sm"])

        outstanding = Card("Outstanding")
        self.outstanding_value = text_label("—", "metric")
        outstanding.body.addWidget(self.outstanding_value)
        outstanding.body.addWidget(
            text_label("Remaining across all liabilities.", "muted")
        )

        paid = Card("Total Paid")
        self.paid_value = text_label("—", "metric")
        paid.body.addWidget(self.paid_value)
        paid.body.addWidget(
            text_label("Payments recorded against liabilities.", "muted")
        )

        open_card = Card("Open Liabilities")
        self.open_value = text_label("—", "metric")
        open_card.body.addWidget(self.open_value)
        open_card.body.addWidget(
            text_label("Liabilities with a remaining balance.", "muted")
        )

        for summary_card in (outstanding, paid, open_card):
            summary_card.body.setContentsMargins(
                SPACE["md"],
                SPACE["sm"] + SPACE["xs"],
                SPACE["md"],
                SPACE["sm"] + SPACE["xs"],
            )
            summary_card.body.setSpacing(SPACE["sm"])
            summary_card.setMaximumHeight(132)

        summary_grid.addWidget(outstanding, 0, 0)
        summary_grid.addWidget(paid, 0, 1)
        summary_grid.addWidget(open_card, 0, 2)
        root.addLayout(summary_grid)

        # Table toolbar: filters on the left, record actions on the right.
        # Everything remains above the list so the controls read as one unit.
        self.table_toolbar = QGridLayout()
        self.table_toolbar.setContentsMargins(0, SPACE["xs"], 0, 0)
        self.table_toolbar.setHorizontalSpacing(SPACE["md"])
        self.table_toolbar.setVerticalSpacing(SPACE["sm"])
        self.table_toolbar.setColumnStretch(0, 1)

        self.filter_widget = QWidget()
        self.filter_layout = QHBoxLayout(self.filter_widget)
        self.filter_layout.setContentsMargins(0, 0, 0, 0)
        self.filter_layout.setSpacing(SPACE["sm"])

        self.filter_label = text_label("Show", "muted")
        self.filter_label.setProperty("compact", True)
        self.filter_layout.addWidget(self.filter_label)

        self.status_filter = QComboBox()
        self.status_filter.addItem("All liabilities", "all")
        self.status_filter.addItem("Open", "open")
        self.status_filter.addItem("Paid", "paid")
        self.status_filter.setProperty("compact", True)
        self.status_filter.setMinimumWidth(126)
        self.status_filter.setMaximumWidth(148)
        self.filter_layout.addWidget(self.status_filter)

        self.refresh_button = button("Refresh")
        self.refresh_button.setProperty("compact", True)
        self.refresh_button.setMaximumWidth(88)
        self.filter_layout.addWidget(self.refresh_button)
        self.filter_layout.addStretch(1)

        self.actions_widget = QWidget()
        self.actions_layout = QHBoxLayout(self.actions_widget)
        self.actions_layout.setContentsMargins(0, 0, 0, 0)
        self.actions_layout.setSpacing(SPACE["sm"])

        self.add_button = button("+ Liability", "primary")
        self.edit_button = button("Edit Liability")
        self.delete_button = button("Delete Liability", "primary")
        self.payment_button = button("Record Payment", "primary")
        self.undo_delete_button = button("Undo Delete")
        self.undo_delete_button.setVisible(False)

        self.edit_button.setEnabled(False)
        self.delete_button.setEnabled(False)
        self.payment_button.setEnabled(False)

        for action_button in (
            self.add_button,
            self.edit_button,
            self.delete_button,
            self.payment_button,
            self.undo_delete_button,
        ):
            action_button.setProperty("compact", True)
            self.actions_layout.addWidget(action_button)

        self.table_toolbar.addWidget(
            self.filter_widget,
            0,
            0,
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
        )
        self.table_toolbar.addWidget(
            self.actions_widget,
            0,
            1,
            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
        )
        root.addLayout(self.table_toolbar)
        self._header_compact = False

        self.table = QTableWidget(0, 7)
        self.table.setHorizontalHeaderLabels(
            ("Name", "Lender", "Original", "Paid", "Remaining", "Due", "Status")
        )
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        for column in range(2, 7):
            header.setSectionResizeMode(column, QHeaderView.ResizeMode.ResizeToContents)
        self.table.setMinimumHeight(170)
        self.table.setMaximumHeight(300)
        root.addWidget(self.table)

        root.addSpacing(SPACE["xs"])

        payments_card = Card(
            "Payment History",
            "Select a liability to see its recorded payments.",
        )
        payment_top = QHBoxLayout()
        self.payment_context = text_label("No liability selected.", "muted")
        payment_top.addWidget(self.payment_context, 1)
        self.payment_edit_button = button("Edit")
        self.payment_delete_button = button("Delete")
        self.payment_undo_button = button("Undo")
        # Edit/Delete stay visible and use the normal theme disabled state until
        # a payment row is selected. Undo appears only during its restore window.
        self.payment_edit_button.setEnabled(False)
        self.payment_delete_button.setEnabled(False)
        self.payment_undo_button.setVisible(False)
        self.payment_undo_button.setEnabled(False)
        payment_top.addWidget(self.payment_edit_button)
        payment_top.addWidget(self.payment_delete_button)
        payment_top.addWidget(self.payment_undo_button)
        payments_card.body.addLayout(payment_top)

        self.payments_table = QTableWidget(0, 3)
        self.payments_table.setHorizontalHeaderLabels(("Date", "Amount", "Note"))
        self.payments_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.payments_table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.payments_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.payments_table.verticalHeader().setVisible(False)
        payment_header = self.payments_table.horizontalHeader()
        payment_header.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        payment_header.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        payment_header.setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        self.payments_table.setMinimumHeight(100)
        self.payments_table.setMaximumHeight(190)
        payments_card.body.addWidget(self.payments_table)
        root.addWidget(payments_card)

        self.feedback = text_label("", "muted")
        root.addWidget(self.feedback)
        root.addStretch(1)

        self.add_button.clicked.connect(self._add_liability)
        self.edit_button.clicked.connect(self._edit_liability)
        self.delete_button.clicked.connect(self._delete_liability)
        self.undo_delete_button.clicked.connect(self._undo_delete_liability)
        self.payment_button.clicked.connect(self._record_payment)
        self.payment_edit_button.clicked.connect(self._edit_payment)
        self.payment_delete_button.clicked.connect(self._delete_payment)
        self.payment_undo_button.clicked.connect(self._undo_delete_payment)
        self.refresh_button.clicked.connect(self.refresh)
        self.status_filter.currentIndexChanged.connect(lambda *_: self.refresh())
        self.table.itemSelectionChanged.connect(self._selection_changed)
        self.payments_table.itemSelectionChanged.connect(self._payment_selection_changed)
        self.refresh()
        QTimer.singleShot(0, lambda: self._set_header_compact(self.width() < 900))

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        compact = self.width() < 900
        if compact != self._header_compact:
            self._set_header_compact(compact)

    def _set_header_compact(self, compact: bool) -> None:
        """Keep both filter and record actions above the liabilities list.

        Wide layouts use one toolbar row. Narrow layouts keep the filters on the
        first row and move the action group to a right-aligned second row so
        controls never collide or disappear.
        """
        self._header_compact = compact

        self.table_toolbar.removeWidget(self.filter_widget)
        self.table_toolbar.removeWidget(self.actions_widget)

        if compact:
            self.table_toolbar.addWidget(
                self.filter_widget,
                0,
                0,
                1,
                2,
                Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
            )
            self.table_toolbar.addWidget(
                self.actions_widget,
                1,
                0,
                1,
                2,
                Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
            )
        else:
            self.table_toolbar.addWidget(
                self.filter_widget,
                0,
                0,
                Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
            )
            self.table_toolbar.addWidget(
                self.actions_widget,
                0,
                1,
                Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
            )

        self.filter_widget.updateGeometry()
        self.actions_widget.updateGeometry()

    def _format(self, amount_minor: int) -> str:
        return format_minor(amount_minor, self.currency_code, self.currency_symbol)

    def _selected_id(self) -> int | None:
        # Use the real selection, not currentRow(). Qt can keep a stale current
        # index after clearSelection(), which previously made the row below a
        # deleted liability appear selected after Undo restored the record.
        rows = self.table.selectionModel().selectedRows()
        if len(rows) != 1:
            return None
        row = rows[0].row()
        if row < 0 or row >= len(self._liability_ids):
            return None
        return self._liability_ids[row]

    def _clear_table_selection(self) -> None:
        """Clear both the selected row and Qt's current-row index."""
        model = self.table.selectionModel()
        if model is not None:
            model.clear()
        self._selection_changed()

    def refresh(self) -> None:
        try:
            items = self.service.list_liabilities(self.status_filter.currentData())
            totals = self.service.totals()
        except LiabilityError as error:
            self.feedback.setText(str(error))
            return

        self.outstanding_value.setText(self._format(totals.outstanding_minor))
        self.paid_value.setText(self._format(totals.paid_minor))
        self.open_value.setText(str(totals.open_count))
        self.open_count_changed.emit(totals.open_count)

        selected_id = self._selected_id()
        self._liability_ids = [item.id for item in items]
        self.table.setRowCount(len(items))
        for row, item in enumerate(items):
            values = (
                item.name,
                item.lender or "—",
                self._format(item.original_amount_minor),
                self._format(item.paid_minor),
                self._format(item.remaining_minor),
                item.due_date or "—",
                item.status,
            )
            for column, value in enumerate(values):
                cell = QTableWidgetItem(value)
                if column in {2, 3, 4}:
                    cell.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
                self.table.setItem(row, column, cell)

        if selected_id in self._liability_ids:
            row = self._liability_ids.index(selected_id)
            self.table.selectRow(row)
            # Refresh action state even when Qt keeps the same row selected.
            # itemSelectionChanged is not guaranteed to fire when selectRow()
            # re-selects an already-selected row after the model contents change.
            self._selection_changed()
        else:
            self._clear_table_selection()

    def _selection_changed(self) -> None:
        liability_id = self._selected_id()
        valid = liability_id is not None
        self.edit_button.setEnabled(valid)
        self.delete_button.setEnabled(valid)
        if not valid:
            self.payment_button.setEnabled(False)
            self._load_payments(None)
            return
        summary = self.service.get_summary(liability_id)
        self.payment_button.setEnabled(summary is not None and summary.remaining_minor > 0)
        self._load_payments(liability_id)

    def _selected_payment_id(self) -> int | None:
        rows = self.payments_table.selectionModel().selectedRows()
        if len(rows) != 1:
            return None
        row = rows[0].row()
        if row < 0 or row >= len(self._payment_ids):
            return None
        return self._payment_ids[row]

    def _payment_selection_changed(self) -> None:
        selected = self._selected_payment_id() is not None
        self.payment_edit_button.setEnabled(selected)
        self.payment_delete_button.setEnabled(selected)
        # Undo is a temporary action: hidden normally, visible/enabled only while
        # a deleted payment is still inside the 10-second restore window.
        has_undo = self._last_deleted_payment_id is not None
        self.payment_undo_button.setVisible(has_undo)
        self.payment_undo_button.setEnabled(has_undo)

    def _load_payments(self, liability_id: int | None) -> None:
        selected_payment_id = self._selected_payment_id()
        self._payment_ids = []
        if liability_id is None:
            self.payment_context.setText("No liability selected.")
            self.payments_table.setRowCount(0)
            self._payment_selection_changed()
            return
        summary = self.service.get_summary(liability_id)
        if summary is None:
            self.payment_context.setText("This liability is no longer available.")
            self.payments_table.setRowCount(0)
            self._payment_selection_changed()
            return
        self.payment_context.setText(
            f"{summary.name} • {summary.status} • Remaining {self._format(summary.remaining_minor)}"
        )
        payments = self.service.list_payments(liability_id)
        self._payment_ids = [payment.id for payment in payments]
        self.payments_table.setRowCount(len(payments))
        for row, payment in enumerate(payments):
            values = (payment.payment_date, self._format(payment.amount_minor), payment.note or "—")
            for column, value in enumerate(values):
                cell = QTableWidgetItem(value)
                if column == 1:
                    cell.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
                self.payments_table.setItem(row, column, cell)
        if selected_payment_id in self._payment_ids:
            self.payments_table.selectRow(self._payment_ids.index(selected_payment_id))
        else:
            self.payments_table.clearSelection()
            self._payment_selection_changed()

    def _add_liability(self) -> None:
        dialog = LiabilityDialog(self.service, self.currency_code, parent=self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self.feedback.setText("Liability saved.")
            self.refresh()

    def _edit_liability(self) -> None:
        liability_id = self._selected_id()
        if liability_id is None:
            self.feedback.setText("Select a liability first.")
            return
        dialog = LiabilityDialog(
            self.service,
            self.currency_code,
            liability_id=liability_id,
            parent=self,
        )
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self.feedback.setText("Liability updated.")
            self.refresh()
            self.linked_expenses_changed.emit()

    def _delete_liability(self) -> None:
        liability_id = self._selected_id()
        if liability_id is None:
            self.feedback.setText("Select a liability first.")
            return
        summary = self.service.get_summary(liability_id)
        if summary is None:
            self.feedback.setText("That liability no longer exists.")
            self.refresh()
            return
        history_choice = _confirm_delete(self, summary.name)
        if history_choice is None:
            return
        try:
            self.service.delete_liability(
                liability_id,
                keep_transaction_history=history_choice == "keep",
            )
        except LiabilityError as error:
            self.feedback.setText(str(error))
            self.refresh()
            return
        self._last_deleted_id = liability_id
        self.undo_delete_button.setVisible(True)
        self._undo_delete_timer.start()
        if history_choice == "keep":
            self.feedback.setText(
                "Liability deleted. Linked Transaction history was kept. Undo is available for 10 seconds."
            )
        else:
            self.feedback.setText(
                "Liability and linked Transaction history deleted. Undo is available for 10 seconds."
            )
        self.refresh()
        self._clear_table_selection()
        self.linked_expenses_changed.emit()

    def _undo_delete_liability(self) -> None:
        liability_id = self._last_deleted_id
        if liability_id is None:
            self.undo_delete_button.setVisible(False)
            return
        try:
            self.service.restore_liability(liability_id)
        except LiabilityError as error:
            self.feedback.setText(str(error))
            self._expire_delete_undo()
            self.refresh()
            return
        self._undo_delete_timer.stop()
        self._last_deleted_id = None
        self.undo_delete_button.setVisible(False)
        self.feedback.setText("Liability restored.")
        self.refresh()
        self._clear_table_selection()
        self.linked_expenses_changed.emit()

    def _expire_delete_undo(self) -> None:
        self._last_deleted_id = None
        self.undo_delete_button.setVisible(False)

    def _record_payment(self) -> None:
        liability_id = self._selected_id()
        if liability_id is None:
            self.feedback.setText("Select a liability first.")
            return
        summary = self.service.get_summary(liability_id)
        if summary is None:
            self.feedback.setText("That liability no longer exists.")
            self.refresh()
            return
        if summary.remaining_minor <= 0:
            self.feedback.setText("This liability is already fully paid.")
            return
        dialog = LiabilityPaymentDialog(
            self.service,
            liability_id,
            self.currency_code,
            self.currency_symbol,
            parent=self,
        )
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self.feedback.setText("Liability payment recorded.")
            self.refresh()
            self.linked_expenses_changed.emit()

    def _edit_payment(self) -> None:
        payment_id = self._selected_payment_id()
        liability_id = self._selected_id()
        if payment_id is None or liability_id is None:
            self.feedback.setText("Select a payment record first.")
            return
        dialog = LiabilityPaymentDialog(
            self.service,
            liability_id,
            self.currency_code,
            self.currency_symbol,
            payment_id=payment_id,
            parent=self,
        )
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self.feedback.setText("Liability payment updated.")
            self.refresh()
            self.linked_expenses_changed.emit()

    def _delete_payment(self) -> None:
        payment_id = self._selected_payment_id()
        if payment_id is None:
            self.feedback.setText("Select a payment record first.")
            return
        payment = self.service.get_payment(payment_id)
        if payment is None:
            self.feedback.setText("That liability payment no longer exists.")
            self.refresh()
            return

        dialog = QDialog(self)
        dialog.setWindowTitle("Delete Liability Payment")
        dialog.setModal(True)
        _apply_dialog_theme(dialog, self)
        dialog.setMinimumWidth(500)
        layout = QVBoxLayout(dialog)
        layout.setContentsMargins(SPACE["lg"], SPACE["lg"], SPACE["lg"], SPACE["lg"])
        layout.setSpacing(SPACE["md"])
        layout.addWidget(text_label("Delete this payment record?", "heading"))
        message = text_label(
            "The payment will be removed from the liability balance and its linked "
            "Transaction expense will also be hidden. You can undo this for 10 seconds."
        )
        message.setWordWrap(True)
        layout.addWidget(message)
        actions = QHBoxLayout()
        actions.addStretch(1)
        cancel = button("Cancel")
        delete = button("Delete Payment", "danger")
        actions.addWidget(cancel)
        actions.addWidget(delete)
        layout.addLayout(actions)
        cancel.clicked.connect(dialog.reject)
        delete.clicked.connect(dialog.accept)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return

        try:
            changed = self.service.delete_payment(payment_id)
        except LiabilityError as error:
            self.feedback.setText(str(error))
            self.refresh()
            return
        if not changed:
            self.feedback.setText("That liability payment could not be deleted.")
            self.refresh()
            return
        self._last_deleted_payment_id = payment_id
        self.payment_undo_button.setVisible(True)
        self.payment_undo_button.setEnabled(True)
        self._payment_undo_timer.start()
        self.feedback.setText("Liability payment deleted — Undo available for 10 seconds.")
        self.refresh()
        self.linked_expenses_changed.emit()

    def _undo_delete_payment(self) -> None:
        payment_id = self._last_deleted_payment_id
        if payment_id is None:
            self.payment_undo_button.setVisible(False)
            self.payment_undo_button.setEnabled(False)
            return
        try:
            changed = self.service.restore_payment(payment_id)
        except LiabilityError as error:
            self.feedback.setText(str(error))
            self._expire_payment_undo()
            self.refresh()
            return
        self._payment_undo_timer.stop()
        self._last_deleted_payment_id = None
        self.payment_undo_button.setVisible(False)
        self.payment_undo_button.setEnabled(False)
        self.feedback.setText("Liability payment restored." if changed else "Payment could not be restored.")
        self.refresh()
        if changed:
            self.linked_expenses_changed.emit()

    def _expire_payment_undo(self) -> None:
        self._last_deleted_payment_id = None
        self.payment_undo_button.setEnabled(False)
        self.payment_undo_button.setVisible(False)
