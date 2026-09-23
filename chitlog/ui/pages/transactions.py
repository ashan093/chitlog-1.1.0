"""Step 7 transaction and category UI."""
from __future__ import annotations

from datetime import date

from PySide6.QtCore import QDate, QTimer, Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QCheckBox,
    QDateEdit,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QSizePolicy,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from chitlog.core.money import amount_text_from_minor, format_minor, minor_digits
from chitlog.services.transaction_service import (
    TransactionError,
    TransactionInput,
    TransactionService,
)
from chitlog.ui.theme import SPACE, stylesheet
from chitlog.ui.widgets import Card, button, text_label


PAYMENT_METHODS = ("", "Cash", "Bank Transfer", "Card", "Cheque", "Other")


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


def _compact(widget):
    widget.setProperty("compact", True)
    return widget


class InlineMessage(QLabel):
    def __init__(self, role: str = "error"):
        super().__init__("")
        self.setProperty("role", role)
        self.setWordWrap(True)
        self.setMinimumHeight(24)
        self.setVisible(False)

    def show_message(self, message: str) -> None:
        self.setText(message)
        self.setVisible(True)

    def clear_message(self) -> None:
        self.clear()
        self.setVisible(False)


class TransactionDialog(QDialog):
    def __init__(
        self,
        service: TransactionService,
        currency_code: str,
        transaction_type: str,
        transaction_id: int | None = None,
        parent=None,
    ):
        super().__init__(parent)
        self.service = service
        self.currency_code = currency_code
        self.transaction_id = transaction_id
        self.transaction_type = transaction_type
        self.setWindowTitle("Edit Transaction" if transaction_id else "Add Transaction")
        self.setModal(True)
        _apply_dialog_theme(self, parent)
        self.resize(520, 470)

        root = QVBoxLayout(self)
        root.setContentsMargins(SPACE["lg"], SPACE["lg"], SPACE["lg"], SPACE["lg"])
        root.setSpacing(SPACE["md"])

        self.heading = text_label("Edit transaction" if transaction_id else "Add transaction", "pageTitle")
        root.addWidget(self.heading)
        self.error = InlineMessage()
        root.addWidget(self.error)

        form = QFormLayout()
        form.setHorizontalSpacing(SPACE["lg"])
        form.setVerticalSpacing(SPACE["md"])

        self.type_combo = QComboBox()
        self.type_combo.addItem("Income", "income")
        self.type_combo.addItem("Expense", "expense")
        self.type_combo.setCurrentIndex(0 if transaction_type == "income" else 1)
        form.addRow("Type", self.type_combo)

        self.date_edit = QDateEdit(QDate.currentDate())
        self.date_edit.setCalendarPopup(True)
        self.date_edit.setDisplayFormat("yyyy-MM-dd")
        form.addRow("Date", self.date_edit)

        self.amount_edit = QLineEdit()
        decimals = minor_digits(currency_code)
        self.amount_edit.setPlaceholderText("0" if decimals == 0 else "0." + ("0" * decimals))
        self.amount_edit.setMaxLength(24)
        form.addRow(f"Amount ({currency_code})", self.amount_edit)

        self.category_combo = QComboBox()
        form.addRow("Category", self.category_combo)

        self.description_edit = QLineEdit()
        self.description_edit.setPlaceholderText("Optional note")
        self.description_edit.setMaxLength(500)
        form.addRow("Description", self.description_edit)

        self.payment_combo = QComboBox()
        for value in PAYMENT_METHODS:
            self.payment_combo.addItem(value or "Not specified", value)
        form.addRow("Payment method", self.payment_combo)
        root.addLayout(form)

        self.buttons = QDialogButtonBox()
        self.save_button = self.buttons.addButton(
            "Save Transaction", QDialogButtonBox.ButtonRole.AcceptRole
        )
        self.cancel_button = self.buttons.addButton(
            "Cancel", QDialogButtonBox.ButtonRole.RejectRole
        )
        self.save_button.setProperty("role", "primary")
        self.buttons.accepted.connect(self.save)
        self.buttons.rejected.connect(self.reject)
        root.addWidget(self.buttons)

        self.type_combo.currentIndexChanged.connect(lambda *_: self._refresh_categories())
        for widget in (
            self.amount_edit,
            self.description_edit,
        ):
            widget.textChanged.connect(lambda *_: self.error.clear_message())
        self.category_combo.currentIndexChanged.connect(lambda *_: self.error.clear_message())
        self._refresh_categories()
        if transaction_id is not None:
            self._load_existing(transaction_id)

    def _refresh_categories(self) -> None:
        selected = self.category_combo.currentData()
        kind = self.type_combo.currentData()
        self.category_combo.blockSignals(True)
        self.category_combo.clear()
        for category in self.service.list_categories(kind):
            self.category_combo.addItem(category.name, category.id)
        index = self.category_combo.findData(selected)
        if index >= 0:
            self.category_combo.setCurrentIndex(index)
        self.category_combo.blockSignals(False)
        self.error.clear_message()

    def _load_existing(self, transaction_id: int) -> None:
        record = self.service.get_transaction(transaction_id)
        if record is None:
            self.error.show_message("This transaction no longer exists.")
            self.save_button.setEnabled(False)
            return
        type_index = self.type_combo.findData(record.transaction_type)
        self.type_combo.setCurrentIndex(type_index)
        parsed_date = QDate.fromString(record.transaction_date, "yyyy-MM-dd")
        if parsed_date.isValid():
            self.date_edit.setDate(parsed_date)
        self.amount_edit.setText(amount_text_from_minor(record.amount_minor, self.currency_code))
        self._refresh_categories()
        category_index = self.category_combo.findData(record.category_id)
        if category_index >= 0:
            self.category_combo.setCurrentIndex(category_index)
        self.description_edit.setText(record.description)
        payment_index = self.payment_combo.findData(record.payment_method or "")
        self.payment_combo.setCurrentIndex(max(payment_index, 0))

    def _input(self) -> TransactionInput:
        category_id = self.category_combo.currentData()
        return TransactionInput(
            transaction_type=self.type_combo.currentData(),
            transaction_date=self.date_edit.date().toString("yyyy-MM-dd"),
            amount_text=self.amount_edit.text(),
            category_id=int(category_id) if category_id is not None else -1,
            description=self.description_edit.text(),
            payment_method=self.payment_combo.currentData(),
        )

    def save(self) -> None:
        self.error.clear_message()
        try:
            if self.transaction_id is None:
                self.service.create_transaction(self._input())
            else:
                self.service.update_transaction(self.transaction_id, self._input())
        except TransactionError as error:
            self.error.show_message(str(error))
            return
        self.accept()


class CategoryManagerDialog(QDialog):
    def __init__(self, service: TransactionService, parent=None):
        super().__init__(parent)
        self.service = service
        self.setWindowTitle("Manage Categories")
        self.setModal(True)
        _apply_dialog_theme(self, parent)
        self.resize(620, 540)

        root = QVBoxLayout(self)
        root.setContentsMargins(SPACE["lg"], SPACE["lg"], SPACE["lg"], SPACE["lg"])
        root.setSpacing(SPACE["md"])
        root.addWidget(text_label("Manage categories", "pageTitle"))
        root.addWidget(
            text_label(
                "Categories with history are archived instead of permanently deleted.",
                "muted",
            )
        )

        self.error = InlineMessage()
        root.addWidget(self.error)

        controls = QHBoxLayout()
        self.kind_combo = QComboBox()
        self.kind_combo.addItem("Expense categories", "expense")
        self.kind_combo.addItem("Income categories", "income")
        controls.addWidget(self.kind_combo, 1)
        self.show_archived = QPushButton("Show archived")
        self.show_archived.setCheckable(True)
        controls.addWidget(self.show_archived)
        root.addLayout(controls)

        self.list_widget = QListWidget()
        self.list_widget.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        root.addWidget(self.list_widget, 1)

        add_row = QHBoxLayout()
        self.name_edit = QLineEdit()
        self.name_edit.setPlaceholderText("New category name")
        self.name_edit.setMaxLength(80)
        add_row.addWidget(self.name_edit, 1)
        self.add_button = button("Add Category", "primary")
        add_row.addWidget(self.add_button)
        root.addLayout(add_row)

        action_row = QHBoxLayout()
        self.rename_button = button("Rename")
        self.archive_button = button("Archive")
        self.restore_button = button("Restore")
        action_row.addWidget(self.rename_button)
        action_row.addWidget(self.archive_button)
        action_row.addWidget(self.restore_button)
        action_row.addStretch(1)
        close = button("Close")
        action_row.addWidget(close)
        root.addLayout(action_row)

        self.kind_combo.currentIndexChanged.connect(lambda *_: self.refresh())
        self.show_archived.toggled.connect(lambda *_: self.refresh())
        self.list_widget.itemSelectionChanged.connect(self._update_actions)
        self.name_edit.textChanged.connect(lambda *_: self.error.clear_message())
        self.add_button.clicked.connect(self.add_category)
        self.rename_button.clicked.connect(self.rename_category)
        self.archive_button.clicked.connect(lambda: self.set_active(False))
        self.restore_button.clicked.connect(lambda: self.set_active(True))
        close.clicked.connect(self.accept)
        self.refresh()

    def _selected(self):
        items = self.list_widget.selectedItems()
        return items[0].data(Qt.ItemDataRole.UserRole) if items else None

    def refresh(self) -> None:
        self.error.clear_message()
        selected_id = self._selected()
        self.list_widget.clear()
        include_inactive = self.show_archived.isChecked()
        for category in self.service.list_categories(
            self.kind_combo.currentData(), include_inactive=include_inactive
        ):
            label = category.name if category.is_active else f"{category.name}  •  Archived"
            item = QListWidgetItem(label)
            item.setData(Qt.ItemDataRole.UserRole, category)
            self.list_widget.addItem(item)
            if selected_id is not None and getattr(selected_id, "id", None) == category.id:
                self.list_widget.setCurrentItem(item)
        self._update_actions()

    def _update_actions(self) -> None:
        category = self._selected()
        self.rename_button.setEnabled(category is not None)
        self.archive_button.setEnabled(category is not None and category.is_active)
        self.restore_button.setEnabled(category is not None and not category.is_active)

    def add_category(self) -> None:
        try:
            self.service.add_category(self.kind_combo.currentData(), self.name_edit.text())
        except TransactionError as error:
            self.error.show_message(str(error))
            return
        self.name_edit.clear()
        self.refresh()

    def rename_category(self) -> None:
        category = self._selected()
        if category is None:
            return
        new_name, accepted = _simple_text_prompt(
            self,
            "Rename Category",
            "Category name",
            category.name,
        )
        if not accepted:
            return
        try:
            self.service.rename_category(category.id, new_name)
        except TransactionError as error:
            self.error.show_message(str(error))
            return
        self.refresh()

    def set_active(self, active: bool) -> None:
        category = self._selected()
        if category is None:
            return
        if not active:
            answer = _confirm(
                self,
                "Archive Category",
                f'Archive “{category.name}”? Existing transactions will keep this category, '
                "but it will no longer appear for new transactions.",
                "Archive",
            )
            if not answer:
                return
        try:
            self.service.set_category_active(category.id, active)
        except TransactionError as error:
            self.error.show_message(str(error))
            return
        if not active and not self.show_archived.isChecked():
            self.refresh()
        else:
            self.refresh()


def _simple_text_prompt(parent, title: str, label: str, initial: str) -> tuple[str, bool]:
    dialog = QDialog(parent)
    dialog.setWindowTitle(title)
    dialog.setModal(True)
    _apply_dialog_theme(dialog, parent)
    dialog.setMinimumWidth(430)

    layout = QVBoxLayout(dialog)
    layout.setContentsMargins(SPACE["lg"], SPACE["lg"], SPACE["lg"], SPACE["lg"])
    layout.setSpacing(SPACE["md"])
    layout.addWidget(text_label(title, "heading"))
    layout.addWidget(text_label(label, "muted"))

    edit = QLineEdit(initial)
    edit.setMaxLength(80)
    edit.selectAll()
    layout.addWidget(edit)

    actions = QHBoxLayout()
    actions.addStretch(1)
    cancel = button("Cancel")
    save = button("Save", "primary")
    actions.addWidget(cancel)
    actions.addWidget(save)
    layout.addLayout(actions)

    cancel.clicked.connect(dialog.reject)
    save.clicked.connect(dialog.accept)
    edit.returnPressed.connect(dialog.accept)

    accepted = dialog.exec() == QDialog.DialogCode.Accepted
    return edit.text(), accepted


def _confirm(parent, title: str, text: str, action_text: str) -> bool:
    """Theme-safe confirmation dialog; avoids native QMessageBox palette conflicts."""
    dialog = QDialog(parent)
    dialog.setWindowTitle(title)
    dialog.setModal(True)
    _apply_dialog_theme(dialog, parent)
    dialog.setMinimumWidth(480)

    layout = QVBoxLayout(dialog)
    layout.setContentsMargins(SPACE["lg"], SPACE["lg"], SPACE["lg"], SPACE["lg"])
    layout.setSpacing(SPACE["md"])
    layout.addWidget(text_label(title, "heading"))
    layout.addWidget(text_label(text))

    actions = QHBoxLayout()
    actions.addStretch(1)
    cancel = button("Cancel")
    action = button(action_text)
    action.setProperty("role", "danger")
    actions.addWidget(cancel)
    actions.addWidget(action)
    layout.addLayout(actions)

    cancel.clicked.connect(dialog.reject)
    action.clicked.connect(dialog.accept)
    cancel.setDefault(True)

    return dialog.exec() == QDialog.DialogCode.Accepted


class TransactionsPage(QWidget):
    UNDO_MS = 10_000

    def __init__(
        self,
        service: TransactionService,
        currency_code: str,
        currency_symbol: str,
        parent=None,
    ):
        super().__init__(parent)
        self.service = service
        self.currency_code = currency_code or "LKR"
        self.currency_symbol = currency_symbol or self.currency_code
        self.last_deleted_id: int | None = None
        today = QDate.currentDate()
        self.selected_month = QDate(today.year(), today.month(), 1)
        self.undo_timer = QTimer(self)
        self.undo_timer.setSingleShot(True)
        self.undo_timer.timeout.connect(self._expire_undo)

        # The transaction page itself never scrolls. The record table owns its
        # vertical scrollbar, so a maximized desktop window keeps the page shell
        # stable while long transaction histories remain usable.
        self.setMinimumSize(0, 0)
        self.setObjectName("content")
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(SPACE["sm"] + 2)

        header = QHBoxLayout()
        header.setSpacing(SPACE["sm"])
        header.addWidget(
            text_label(
                "Add, edit, categorize, archive categories, and safely delete records.",
                "muted",
            ),
            1,
        )
        self.add_income = button("+ Income", "primary")
        self.add_expense = button("+ Expense", "primary")
        self.manage_categories = button("Manage Categories")
        header.addWidget(self.add_income)
        header.addWidget(self.add_expense)
        header.addWidget(self.manage_categories)
        root.addLayout(header)

        summary = QHBoxLayout()
        self.income_card = Card("Total Income")
        self.income_value = text_label("—", "metric")
        self.income_value.setWordWrap(False)
        self.income_card.body.addWidget(self.income_value)
        self.expense_card = Card("Total Expenses")
        self.expense_value = text_label("—", "metric")
        self.expense_value.setWordWrap(False)
        self.expense_card.body.addWidget(self.expense_value)
        self.net_card = Card("Net")
        self.net_value = text_label("—", "metric")
        self.net_value.setWordWrap(False)
        self.net_card.body.addWidget(self.net_value)
        self._summary_cards = (self.income_card, self.expense_card, self.net_card)
        self._summary_values = (self.income_value, self.expense_value, self.net_value)
        for summary_card in self._summary_cards:
            summary_card.body.setContentsMargins(18, 12, 18, 12)
            summary_card.body.setSpacing(4)
            summary_card.setMinimumHeight(108)
            summary_card.setMaximumHeight(122)
        summary.addWidget(self.income_card, 1)
        summary.addWidget(self.expense_card, 1)
        summary.addWidget(self.net_card, 1)
        root.addLayout(summary)

        filters = QHBoxLayout()
        filters.setSpacing(SPACE["sm"])
        self.type_filter = _compact(QComboBox())
        self.type_filter.setMinimumWidth(115)
        self.type_filter.setMaximumWidth(150)
        self.type_filter.addItem("All types", None)
        self.type_filter.addItem("Income", "income")
        self.type_filter.addItem("Expense", "expense")
        filters.addWidget(self.type_filter)

        self.category_filter = _compact(QComboBox())
        self.category_filter.setMinimumWidth(130)
        self.category_filter.setMaximumWidth(190)
        self.category_filter.addItem("All categories", None)
        filters.addWidget(self.category_filter)

        self.search = _compact(QLineEdit())
        self.search.setPlaceholderText("Search description, category, or payment method")
        self.search.setMaxLength(120)
        filters.addWidget(self.search, 1)
        self.refresh_button = _compact(button("Refresh"))
        filters.addWidget(self.refresh_button)

        date_filters = QHBoxLayout()
        date_filters.setSpacing(SPACE["xs"])
        self.use_date_range = _compact(QCheckBox("Date range"))
        date_filters.addWidget(self.use_date_range)
        self.start_date = _compact(QDateEdit(QDate.currentDate().addMonths(-1)))
        self.start_date.setCalendarPopup(True)
        self.start_date.setDisplayFormat("yyyy-MM-dd")
        self.end_date = _compact(QDateEdit(QDate.currentDate()))
        self.end_date.setCalendarPopup(True)
        self.end_date.setDisplayFormat("yyyy-MM-dd")
        self.start_date.setEnabled(False)
        self.end_date.setEnabled(False)
        # Enough room for yyyy-MM-dd plus the calendar drop-down button.
        # Do not allow the compact layout to clip the date text.
        self.start_date.setMinimumWidth(150)
        self.start_date.setMaximumWidth(165)
        self.end_date.setMinimumWidth(150)
        self.end_date.setMaximumWidth(165)
        from_label = _compact(text_label("From", "muted"))
        to_label = _compact(text_label("To", "muted"))
        date_filters.addWidget(from_label)
        date_filters.addWidget(self.start_date)
        date_filters.addWidget(to_label)
        date_filters.addWidget(self.end_date)
        date_filters.addStretch(1)

        filter_block = QVBoxLayout()
        # Small breathing room below the summary cards while keeping the
        # filter and date-range rows visually grouped.
        filter_block.setContentsMargins(0, SPACE["sm"], 0, 0)
        filter_block.setSpacing(SPACE["xs"])
        filter_block.addLayout(filters)
        filter_block.addLayout(date_filters)
        root.addLayout(filter_block)
        self.filter_block_layout = filter_block

        root.addSpacing(SPACE["sm"])

        # Month browser controls only the records shown in the table.
        # Summary cards intentionally remain overall transaction totals.
        month_navigation = QHBoxLayout()
        month_navigation.setSpacing(SPACE["sm"])
        month_navigation.addStretch(1)
        self.previous_month_button = _compact(button("‹"))
        self.previous_month_button.setFixedWidth(42)
        self.previous_month_button.setToolTip("Previous month")
        self.previous_month_button.setAccessibleName("Previous month")
        self.month_label = text_label("", "heading")
        self.month_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.month_label.setMinimumWidth(175)
        self.month_label.setWordWrap(False)
        self.next_month_button = _compact(button("›"))
        self.next_month_button.setFixedWidth(42)
        self.next_month_button.setToolTip("Next month")
        self.next_month_button.setAccessibleName("Next month")
        month_navigation.addWidget(self.previous_month_button)
        month_navigation.addWidget(self.month_label)
        month_navigation.addWidget(self.next_month_button)
        month_navigation.addStretch(1)
        self.month_navigation_layout = month_navigation

        self.table = QTableWidget(0, 6)
        self.table.setHorizontalHeaderLabels(
            ("Date", "Type", "Category", "Description", "Payment", "Amount")
        )
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setSortingEnabled(False)
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
        self.table.setMinimumHeight(140)
        # Let the record list use spare vertical room instead of leaving a large
        # empty area below it. The table keeps its normal minimum height and its
        # own internal scrolling for longer histories.
        self.table.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding
        )

        # Keep month navigation, transaction actions, and the record list grouped
        # together with compact spacing. Extra page height should remain below the
        # record area rather than opening large gaps between these related controls.
        actions = QHBoxLayout()
        actions.setSpacing(SPACE["sm"])
        self.edit_button = button("Edit Transaction")
        self.delete_button = button("Delete Transaction")
        self.undo_button = button("Undo Delete")
        self.undo_button.setVisible(False)
        self.edit_button.setEnabled(False)
        self.delete_button.setEnabled(False)
        actions.addWidget(self.edit_button)
        actions.addWidget(self.delete_button)
        actions.addWidget(self.undo_button)
        actions.addStretch(1)
        self.transaction_actions_layout = actions

        records_section = QVBoxLayout()
        records_section.setContentsMargins(0, 0, 0, 0)
        records_section.setSpacing(SPACE["xs"])
        records_section.addLayout(month_navigation)
        records_section.addLayout(actions)
        records_section.addWidget(self.table, 1)
        root.addLayout(records_section, 1)
        self.records_section_layout = records_section

        self.feedback_bar = QFrame()
        self.feedback_bar.setProperty("role", "glass")
        # This is a compact status/toast row, not a content card.  A fixed
        # vertical policy prevents spare page height from stretching it into
        # the large empty panel previously seen after deleting a transaction.
        self.feedback_bar.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed
        )
        self.feedback_bar.setFixedHeight(46)
        feedback_layout = QHBoxLayout(self.feedback_bar)
        feedback_layout.setContentsMargins(
            SPACE["md"], SPACE["xs"], SPACE["md"], SPACE["xs"]
        )
        self.feedback_text = text_label("", "muted")
        self.feedback_text.setWordWrap(False)
        feedback_layout.addWidget(self.feedback_text, 1)
        self.feedback_bar.setVisible(False)
        root.addWidget(self.feedback_bar)

        self.add_income.clicked.connect(lambda: self.open_add("income"))
        self.add_expense.clicked.connect(lambda: self.open_add("expense"))
        self.manage_categories.clicked.connect(self.open_categories)
        self.type_filter.currentIndexChanged.connect(self._type_filter_changed)
        self.category_filter.currentIndexChanged.connect(lambda *_: self.refresh())
        self.search.textChanged.connect(lambda *_: self.refresh())
        self.refresh_button.clicked.connect(lambda *_: self.refresh())
        self.use_date_range.toggled.connect(self._toggle_date_range)
        self.start_date.dateChanged.connect(self._start_date_changed)
        self.end_date.dateChanged.connect(self._end_date_changed)
        self.previous_month_button.clicked.connect(self._show_previous_month)
        self.next_month_button.clicked.connect(self._show_next_month)
        self.table.itemSelectionChanged.connect(self._selection_changed)
        self.table.itemDoubleClicked.connect(lambda *_: self.edit_selected())
        self.edit_button.clicked.connect(self.edit_selected)
        self.delete_button.clicked.connect(self.delete_selected)
        self.undo_button.clicked.connect(self.undo_delete)
        self._refresh_category_filter()
        self._update_month_navigation()
        self.refresh()
        self._update_summary_density()

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._update_summary_density()

    def _update_summary_density(self) -> None:
        """Apply the summary-card density appropriate for the current page width."""
        if not hasattr(self, "_summary_cards"):
            return
        self._set_summary_compact(self.width() < 820)

    def _set_summary_compact(self, compact: bool) -> None:
        """Apply compact/normal summary styling.

        Keeping this as a separate deterministic helper makes the responsive behavior
        testable without depending on Qt's offscreen layout engine, which may ignore
        manual child-widget resize requests while a layout owns the widget geometry.
        """
        margins = (12, 10, 12, 10) if compact else (18, 12, 18, 12)
        min_height, max_height = ((102, 116) if compact else (108, 122))
        for card in self._summary_cards:
            card.body.setContentsMargins(*margins)
            card.setMinimumHeight(min_height)
            card.setMaximumHeight(max_height)
        # Step 23 owns metric typography by actual card width. An inline font
        # here would outrank the responsive stylesheet and can cause overlap.
        for value in self._summary_values:
            value.setStyleSheet("")

    def _selected_id(self) -> int | None:
        rows = self.table.selectionModel().selectedRows()
        if not rows:
            return None
        item = self.table.item(rows[0].row(), 0)
        return int(item.data(Qt.ItemDataRole.UserRole)) if item else None

    def _selection_changed(self) -> None:
        enabled = self._selected_id() is not None
        self.edit_button.setEnabled(enabled)
        self.delete_button.setEnabled(enabled)

    def _refresh_category_filter(self) -> None:
        selected = self.category_filter.currentData()
        self.category_filter.blockSignals(True)
        self.category_filter.clear()
        self.category_filter.addItem("All categories", None)
        kind = self.type_filter.currentData()
        for category in self.service.list_categories(kind, include_inactive=True):
            label = category.name if category.is_active else f"{category.name} • Archived"
            self.category_filter.addItem(label, category.id)
        index = self.category_filter.findData(selected)
        if index >= 0:
            self.category_filter.setCurrentIndex(index)
        self.category_filter.blockSignals(False)

    def _type_filter_changed(self, *_args) -> None:
        self._refresh_category_filter()
        self.refresh()

    def _toggle_date_range(self, checked: bool) -> None:
        self.start_date.setEnabled(checked)
        self.end_date.setEnabled(checked)
        self._update_month_navigation()
        self.refresh()

    def _month_bounds(self) -> tuple[str, str]:
        start = self.selected_month
        end = start.addMonths(1).addDays(-1)
        return start.toString("yyyy-MM-dd"), end.toString("yyyy-MM-dd")

    def _update_month_navigation(self) -> None:
        custom_range = self.use_date_range.isChecked()
        if custom_range:
            self.month_label.setText("Custom date range")
            self.previous_month_button.setToolTip("Turn off Date range to browse months.")
            self.next_month_button.setToolTip("Turn off Date range to browse months.")
            self.previous_month_button.setEnabled(False)
            self.next_month_button.setEnabled(False)
            return

        self.month_label.setText(self.selected_month.toString("MMMM yyyy"))
        self.previous_month_button.setToolTip("Previous month")
        self.next_month_button.setToolTip("Next month")
        self.previous_month_button.setEnabled(True)
        today = QDate.currentDate()
        current_month = QDate(today.year(), today.month(), 1)
        # Historical browsing stops at the current month.
        self.next_month_button.setEnabled(self.selected_month < current_month)

    def _show_previous_month(self) -> None:
        if self.use_date_range.isChecked():
            return
        self.selected_month = self.selected_month.addMonths(-1)
        self._update_month_navigation()
        self.refresh()

    def _show_next_month(self) -> None:
        if self.use_date_range.isChecked():
            return
        today = QDate.currentDate()
        current_month = QDate(today.year(), today.month(), 1)
        candidate = self.selected_month.addMonths(1)
        if candidate > current_month:
            return
        self.selected_month = candidate
        self._update_month_navigation()
        self.refresh()

    def _start_date_changed(self, value: QDate) -> None:
        # Keep a valid range without forcing the user through an error dialog.
        # Moving the start beyond the end moves the end forward to match.
        if value > self.end_date.date():
            self.end_date.blockSignals(True)
            self.end_date.setDate(value)
            self.end_date.blockSignals(False)
        self.refresh()

    def _end_date_changed(self, value: QDate) -> None:
        # Likewise, moving the end before the start moves the start back.
        if value < self.start_date.date():
            self.start_date.blockSignals(True)
            self.start_date.setDate(value)
            self.start_date.blockSignals(False)
        self.refresh()

    def refresh(self) -> None:
        try:
            if self.use_date_range.isChecked():
                start_date = self.start_date.date().toString("yyyy-MM-dd")
                end_date = self.end_date.date().toString("yyyy-MM-dd")
            else:
                start_date, end_date = self._month_bounds()

            records = self.service.list_transactions(
                transaction_type=self.type_filter.currentData(),
                search=self.search.text(),
                category_id=self.category_filter.currentData(),
                start_date=start_date,
                end_date=end_date,
            )
        except TransactionError as error:
            self._show_feedback(str(error))
            return
        self.table.setRowCount(len(records))
        for row, record in enumerate(records):
            values = (
                record.transaction_date,
                record.transaction_type.title(),
                record.category_name,
                record.description or "—",
                record.payment_method or "—",
                format_minor(record.amount_minor, self.currency_code, self.currency_symbol),
            )
            for column, value in enumerate(values):
                item = QTableWidgetItem(value)
                if column == 0:
                    item.setData(Qt.ItemDataRole.UserRole, record.id)
                if column == 5:
                    item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
                self.table.setItem(row, column, item)
        self._selection_changed()
        income, expense, net = self.service.totals()
        self.income_value.setText(format_minor(income, self.currency_code, self.currency_symbol))
        self.expense_value.setText(format_minor(expense, self.currency_code, self.currency_symbol))
        sign = "-" if net < 0 else ""
        self.net_value.setText(sign + format_minor(abs(net), self.currency_code, self.currency_symbol))

    def open_add(self, kind: str) -> None:
        dialog = TransactionDialog(self.service, self.currency_code, kind, parent=self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self._show_feedback("Transaction saved.")
            self.refresh()

    def edit_selected(self) -> None:
        transaction_id = self._selected_id()
        if transaction_id is None:
            return
        record = self.service.get_transaction(transaction_id)
        if record is None:
            self._show_feedback("The selected transaction is no longer available.")
            self.refresh()
            return
        dialog = TransactionDialog(
            self.service,
            self.currency_code,
            record.transaction_type,
            transaction_id,
            self,
        )
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self._show_feedback("Transaction updated.")
            self.refresh()

    def delete_selected(self) -> None:
        transaction_id = self._selected_id()
        if transaction_id is None:
            return
        record = self.service.get_transaction(transaction_id)
        if record is None:
            self.refresh()
            return
        confirmed = _confirm(
            self,
            "Delete Transaction",
            "Delete this transaction? It will be removed from normal records. "
            "You can undo for a short time after deletion.",
            "Delete",
        )
        if not confirmed:
            return
        if not self.service.delete_transaction(transaction_id):
            self._show_feedback("The transaction could not be deleted.")
            self.refresh()
            return
        self.last_deleted_id = transaction_id
        self.undo_timer.start(self.UNDO_MS)
        self._show_feedback("Transaction deleted.", show_undo=True)
        self.refresh()

    def undo_delete(self) -> None:
        if self.last_deleted_id is None:
            return
        transaction_id = self.last_deleted_id
        self.last_deleted_id = None
        self.undo_timer.stop()
        if self.service.undo_delete(transaction_id):
            self._show_feedback("Transaction restored.")
        else:
            self._show_feedback("The transaction could not be restored.")
        self.refresh()

    def _expire_undo(self) -> None:
        self.last_deleted_id = None
        self.undo_button.setVisible(False)
        if self.feedback_bar.isVisible() and self.feedback_text.text() == "Transaction deleted.":
            self.feedback_bar.setVisible(False)

    def _show_feedback(self, message: str, *, show_undo: bool = False) -> None:
        self.feedback_text.setText(message)
        self.undo_button.setVisible(show_undo)
        self.feedback_bar.setVisible(True)
        if not show_undo:
            QTimer.singleShot(3500, self._hide_feedback_if_safe)

    def _hide_feedback_if_safe(self) -> None:
        if not self.undo_button.isVisible():
            self.feedback_bar.setVisible(False)

    def open_categories(self) -> None:
        dialog = CategoryManagerDialog(self.service, self)
        dialog.exec()
        self._refresh_category_filter()
        self.refresh()
