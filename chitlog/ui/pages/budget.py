"""Step 9 monthly and category budget interface."""
from __future__ import annotations

from PySide6.QtCore import QDate, Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QDateEdit,
    QDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QProgressBar,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from chitlog.core.money import amount_text_from_minor, format_minor, minor_digits
from chitlog.services.budget_service import BudgetError, BudgetService
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


def _confirm(parent, title: str, text: str, action_text: str) -> bool:
    dialog = QDialog(parent)
    dialog.setWindowTitle(title)
    dialog.setModal(True)
    dialog.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
    dialog.setAutoFillBackground(True)
    dialog.setStyleSheet(stylesheet(_theme_name_from_widget(parent)))
    dialog.setMinimumWidth(470)

    layout = QVBoxLayout(dialog)
    layout.setContentsMargins(SPACE["lg"], SPACE["lg"], SPACE["lg"], SPACE["lg"])
    layout.setSpacing(SPACE["md"])
    layout.addWidget(text_label(title, "heading"))
    layout.addWidget(text_label(text, "muted"))

    actions = QHBoxLayout()
    actions.addStretch(1)
    cancel = button("Cancel")
    confirm = button(action_text)
    confirm.setProperty("role", "danger")
    actions.addWidget(cancel)
    actions.addWidget(confirm)
    layout.addLayout(actions)
    cancel.clicked.connect(dialog.reject)
    confirm.clicked.connect(dialog.accept)
    cancel.setDefault(True)
    return dialog.exec() == QDialog.DialogCode.Accepted


class BudgetPage(QWidget):
    def __init__(
        self,
        service: BudgetService,
        currency_code: str,
        currency_symbol: str,
        parent=None,
    ):
        super().__init__(parent)
        self.service = service
        self.currency_code = currency_code or "LKR"
        self.currency_symbol = currency_symbol or self.currency_code
        self._category_ids: list[int] = []
        self.setObjectName("content")
        self.setMinimumSize(0, 0)

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(SPACE["md"])

        top = QHBoxLayout()
        top.addWidget(
            text_label(
                "Set a monthly budget, optional category budgets, and carry unused total budget forward.",
                "muted",
            ),
            1,
        )
        top.addWidget(text_label("Month", "muted"))
        self.month_edit = QDateEdit(QDate.currentDate())
        self.month_edit.setCalendarPopup(True)
        self.month_edit.setDisplayFormat("MMMM yyyy")
        self.month_edit.setMinimumWidth(165)
        self.month_edit.setProperty("compact", True)
        top.addWidget(self.month_edit)
        self.refresh_button = button("Refresh")
        self.refresh_button.setProperty("compact", True)
        top.addWidget(self.refresh_button)
        root.addLayout(top)

        summary_row = QHBoxLayout()
        summary_row.setSpacing(SPACE["md"])
        self.available_card = Card("Available Budget")
        self.available_value = text_label("—", "metric")
        self.available_value.setWordWrap(False)
        self.available_detail = text_label("", "muted")
        self.available_card.body.addWidget(self.available_value)
        self.available_card.body.addWidget(self.available_detail)

        self.spent_card = Card("Spent")
        self.spent_value = text_label("—", "metric")
        self.spent_value.setWordWrap(False)
        self.spent_card.body.addWidget(self.spent_value)
        self.spent_card.body.addWidget(text_label("Expenses in this month", "muted"))

        self.remaining_card = Card("Remaining")
        self.remaining_value = text_label("—", "metric")
        self.remaining_value.setWordWrap(False)
        self.remaining_card.body.addWidget(self.remaining_value)
        self.remaining_card.body.addWidget(text_label("Available budget minus spending", "muted"))

        for card in (self.available_card, self.spent_card, self.remaining_card):
            card.body.setContentsMargins(18, 14, 18, 14)
            card.body.setSpacing(5)
            summary_row.addWidget(card, 1)
        root.addLayout(summary_row)

        progress_card = Card("Monthly Budget Progress", glass=True)
        self.progress = QProgressBar()
        self.progress.setRange(0, 100)
        self.progress.setTextVisible(False)
        self.progress.setMinimumHeight(10)
        self.progress_label = text_label("", "muted")
        progress_card.body.addWidget(self.progress)
        progress_card.body.addWidget(self.progress_label)
        root.addWidget(progress_card)

        settings_card = Card("Monthly Budget Settings")
        settings_row = QHBoxLayout()
        self.monthly_amount = QLineEdit()
        decimals = minor_digits(self.currency_code)
        self.monthly_amount.setPlaceholderText("0" if decimals == 0 else "0." + "0" * decimals)
        self.monthly_amount.setMaxLength(24)
        self.monthly_amount.setMinimumWidth(180)
        settings_row.addWidget(text_label(f"Budget ({self.currency_code})", "muted"))
        settings_row.addWidget(self.monthly_amount)
        self.carry_enabled = QCheckBox("Carry unused total budget into next month")
        settings_row.addWidget(self.carry_enabled, 1)
        self.save_monthly = button("Save Monthly Budget", "primary")
        settings_row.addWidget(self.save_monthly)
        settings_card.body.addLayout(settings_row)
        settings_card.body.addWidget(
            text_label(
                "Carry-forward rule: only a positive unused total budget moves forward. "
                "Overspending does not create a negative carry. Category budgets do not carry forward in V1.",
                "muted",
            )
        )
        root.addWidget(settings_card)

        category_card = Card(
            "Category Budgets",
            "Optional planning limits for expense categories. Existing archived categories remain visible when already budgeted.",
        )
        self.category_table = QTableWidget(0, 5)
        self.category_table.setHorizontalHeaderLabels(
            ("Category", "Budget", "Spent", "Remaining", "Used")
        )
        self.category_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.category_table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.category_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.category_table.verticalHeader().setVisible(False)
        header = self.category_table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        for column in range(1, 5):
            header.setSectionResizeMode(column, QHeaderView.ResizeMode.ResizeToContents)
        self.category_table.setMinimumHeight(150)
        self.category_table.setMaximumHeight(265)
        category_card.body.addWidget(self.category_table)

        editor = QHBoxLayout()
        self.category_combo = QComboBox()
        self.category_combo.setMinimumWidth(180)
        editor.addWidget(self.category_combo)
        self.category_amount = QLineEdit()
        self.category_amount.setPlaceholderText("Category budget amount")
        self.category_amount.setMaxLength(24)
        editor.addWidget(self.category_amount, 1)
        self.set_category_button = button("Set Category Budget", "primary")
        self.remove_category_button = button("Remove Budget")
        self.remove_category_button.setEnabled(False)
        editor.addWidget(self.set_category_button)
        editor.addWidget(self.remove_category_button)
        category_card.body.addLayout(editor)
        root.addWidget(category_card)

        self.feedback = text_label("", "muted")
        root.addWidget(self.feedback)
        root.addStretch(1)

        self.refresh_button.clicked.connect(self.refresh)
        self.month_edit.dateChanged.connect(lambda *_: self.refresh())
        self.save_monthly.clicked.connect(self._save_monthly)
        self.set_category_button.clicked.connect(self._set_category)
        self.remove_category_button.clicked.connect(self._remove_category)
        self.category_table.itemSelectionChanged.connect(self._category_selection_changed)
        self.category_combo.currentIndexChanged.connect(self._category_combo_changed)
        self.refresh()

    def _month(self) -> str:
        value = self.month_edit.date()
        return f"{value.year():04d}-{value.month():02d}"

    def _format(self, value: int) -> str:
        return format_minor(value, self.currency_code, self.currency_symbol)

    def _refresh_category_combo(self) -> None:
        selected = self.category_combo.currentData()
        self.category_combo.blockSignals(True)
        self.category_combo.clear()
        for category in self.service.list_expense_categories():
            self.category_combo.addItem(category.name, category.id)
        index = self.category_combo.findData(selected)
        if index >= 0:
            self.category_combo.setCurrentIndex(index)
        self.category_combo.blockSignals(False)

    def refresh(self) -> None:
        try:
            status = self.service.status(self._month())
        except BudgetError as error:
            self.feedback.setText(str(error))
            return

        self._refresh_category_combo()
        self.available_value.setText(self._format(status.effective_budget_minor))
        self.available_detail.setText(
            f"Base {self._format(status.base_budget_minor)}  +  Carry in {self._format(status.carry_in_minor)}"
        )
        self.spent_value.setText(self._format(status.spent_minor))
        self.remaining_value.setText(self._format(status.remaining_minor))
        self.progress.setValue(min(status.used_percent, 100))
        if status.effective_budget_minor <= 0:
            self.progress_label.setText("No monthly budget has been set for this month.")
        elif status.remaining_minor >= 0:
            self.progress_label.setText(
                f"{status.used_percent}% used • {self._format(status.remaining_minor)} remaining"
            )
        else:
            self.progress_label.setText(
                f"{status.used_percent}% used • Over budget by {self._format(abs(status.remaining_minor))}"
            )

        self.monthly_amount.setText(
            amount_text_from_minor(status.base_budget_minor, self.currency_code)
            if status.base_budget_minor > 0 else ""
        )
        self.carry_enabled.setChecked(status.carry_forward_enabled)

        self._category_ids = [item.category_id for item in status.category_budgets]
        self.category_table.setRowCount(len(status.category_budgets))
        for row, item in enumerate(status.category_budgets):
            category_text = item.category_name + (" (archived)" if not item.category_active else "")
            values = (
                category_text,
                self._format(item.budget_minor),
                self._format(item.spent_minor),
                self._format(item.remaining_minor),
                f"{item.used_percent}%",
            )
            for column, value in enumerate(values):
                cell = QTableWidgetItem(value)
                if column in {1, 2, 3, 4}:
                    cell.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
                self.category_table.setItem(row, column, cell)
        self.remove_category_button.setEnabled(False)

    def _save_monthly(self) -> None:
        try:
            self.service.set_monthly_budget(
                self._month(), self.monthly_amount.text(), self.carry_enabled.isChecked()
            )
        except BudgetError as error:
            self.feedback.setText(str(error))
            return
        self.feedback.setText("Monthly budget saved. Carry-forward was recalculated safely.")
        self.refresh()

    def _set_category(self) -> None:
        category_id = self.category_combo.currentData()
        if category_id is None:
            self.feedback.setText("Choose an expense category.")
            return
        try:
            self.service.set_category_budget(
                self._month(), int(category_id), self.category_amount.text()
            )
        except BudgetError as error:
            self.feedback.setText(str(error))
            return
        self.feedback.setText("Category budget saved.")
        self.category_amount.clear()
        self.refresh()

    def _category_selection_changed(self) -> None:
        row = self.category_table.currentRow()
        valid = 0 <= row < len(self._category_ids)
        self.remove_category_button.setEnabled(valid)
        if not valid:
            return
        category_id = self._category_ids[row]
        index = self.category_combo.findData(category_id)
        if index >= 0:
            self.category_combo.setCurrentIndex(index)
        # Populate the amount only for active categories that can be edited.
        item = self.service.status(self._month()).category_budgets[row]
        if item.category_active:
            self.category_amount.setText(
                amount_text_from_minor(item.budget_minor, self.currency_code)
            )

    def _category_combo_changed(self) -> None:
        category_id = self.category_combo.currentData()
        if category_id is None:
            return
        status = self.service.status(self._month())
        for item in status.category_budgets:
            if item.category_id == category_id:
                self.category_amount.setText(
                    amount_text_from_minor(item.budget_minor, self.currency_code)
                )
                return

    def _remove_category(self) -> None:
        row = self.category_table.currentRow()
        if row < 0 or row >= len(self._category_ids):
            self.feedback.setText("Select a category budget first.")
            return
        category_id = self._category_ids[row]
        category_name = self.category_table.item(row, 0).text()
        if not _confirm(
            self,
            "Remove Category Budget",
            f"Remove the budget allocation for {category_name}? Transactions are not changed.",
            "Remove Budget",
        ):
            return
        if self.service.remove_category_budget(self._month(), category_id):
            self.feedback.setText("Category budget removed. Transactions were not changed.")
        else:
            self.feedback.setText("That category budget is no longer available.")
        self.category_amount.clear()
        self.refresh()
