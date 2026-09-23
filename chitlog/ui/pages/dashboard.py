"""Step 8 dashboard: transaction summaries and non-destructive recent activity."""
from __future__ import annotations

from PySide6.QtCore import QTimer, Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QDialog,
    QGridLayout,
    QHeaderView,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from chitlog.core.money import format_minor
from chitlog.services.dashboard_service import DashboardService
from chitlog.ui.theme import SPACE
from chitlog.ui.widgets import Card, button, text_label


def _confirm_hide_recent(parent) -> bool:
    """Ask before hiding a Dashboard-only recent item.

    This is intentionally a ChitLog-themed dialog rather than a native
    QMessageBox so Light/Dark/System remain readable and consistent.
    """
    dialog = QDialog(parent)
    dialog.setWindowTitle("Hide from Recent")
    dialog.setModal(True)
    dialog.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
    dialog.setAutoFillBackground(True)
    # Reuse the active application's theme without coupling Dashboard to the
    # Transactions page's private dialog helper.
    dialog.setStyleSheet(parent.window().styleSheet())
    dialog.setMinimumWidth(500)

    layout = QVBoxLayout(dialog)
    layout.setContentsMargins(SPACE["lg"], SPACE["lg"], SPACE["lg"], SPACE["lg"])
    layout.setSpacing(SPACE["md"])
    layout.addWidget(text_label("Hide from Recent?", "heading"))
    layout.addWidget(
        text_label(
            "This removes the selected item only from Dashboard Recent Activity. "
            "The transaction remains saved in Transactions and still counts in totals.",
            "muted",
        )
    )

    actions = QHBoxLayout()
    actions.addStretch(1)
    cancel = button("Cancel")
    hide = button("Hide from Recent")
    hide.setProperty("role", "danger")
    actions.addWidget(cancel)
    actions.addWidget(hide)
    layout.addLayout(actions)

    cancel.clicked.connect(dialog.reject)
    hide.clicked.connect(dialog.accept)
    cancel.setDefault(True)
    return dialog.exec() == QDialog.DialogCode.Accepted


class DashboardPage(QWidget):
    """Useful overview without turning the dashboard into an accounting screen."""

    def __init__(
        self,
        service: DashboardService,
        currency_code: str,
        currency_symbol: str,
    ):
        super().__init__()
        self.service = service
        self.currency_code = currency_code
        self.currency_symbol = currency_symbol
        self._recent_ids: list[int] = []
        self._summary_cards = []
        self._metric_labels = []
        self._last_hidden_id: int | None = None
        self._undo_hide_timer = QTimer(self)
        self._undo_hide_timer.setSingleShot(True)
        self._undo_hide_timer.timeout.connect(self._expire_hide_undo)

        # The main shell now owns scrolling. A modest content minimum prevents
        # Qt from crushing dashboard cards when the desktop window is made
        # short, while still fitting a typical maximized 1366x768 workspace.
        self.setMinimumSize(0, 540)
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(SPACE["md"])

        intro = QHBoxLayout()
        intro.setSpacing(SPACE["md"])
        text = QVBoxLayout()
        text.setSpacing(2)
        text.addWidget(text_label("OVERVIEW", "eyebrow"))
        text.addWidget(text_label("Your money at a glance", "title"))
        self.period_label = text_label("", "muted")
        text.addWidget(self.period_label)
        intro.addLayout(text, 1)
        self.refresh_button = button("Refresh")
        self.refresh_button.setProperty("compact", True)
        self.refresh_button.clicked.connect(self.refresh)
        intro.addWidget(self.refresh_button, 0, Qt.AlignmentFlag.AlignBottom)
        root.addLayout(intro)

        self.summary_grid = QGridLayout()
        self.summary_grid.setHorizontalSpacing(SPACE["md"])
        self.summary_grid.setVerticalSpacing(SPACE["md"])
        self.summary_grid.setColumnStretch(0, 1)
        self.summary_grid.setColumnStretch(1, 1)

        self.balance_value = self._summary_card(
            0, 0, "Current Balance", "Income minus expenses across active records."
        )
        self.income_value = self._summary_card(
            0, 1, "This Month Income", "Income recorded in the current month."
        )
        self.expense_value = self._summary_card(
            1, 0, "This Month Expenses", "Expenses recorded in the current month."
        )
        self.net_value = self._summary_card(
            1, 1, "This Month Net", "This month income minus expenses."
        )
        root.addLayout(self.summary_grid)

        recent_card = Card(
            "Recent Activity",
            "Latest transactions. Hide from Recent removes an item only from this Dashboard list.",
            glass=True,
        )
        recent_card.setMinimumSize(0, 0)

        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels(
            ["Date", "Type", "Category", "Description", "Amount"]
        )
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setAlternatingRowColors(False)
        self.table.verticalHeader().setVisible(False)
        self.table.setMinimumHeight(125)
        self.table.setSizeAdjustPolicy(QAbstractItemView.SizeAdjustPolicy.AdjustIgnored)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(4, QHeaderView.ResizeMode.ResizeToContents)
        self.table.itemSelectionChanged.connect(self._selection_changed)

        # Recent Activity actions belong above the table at the upper-right.
        # Preserve the original confirmation + 10-second Undo behavior.
        actions = QHBoxLayout()
        actions.setContentsMargins(0, 0, 0, 0)
        actions.addStretch(1)

        self.hide_recent_button = button("Hide from Recent")
        self.hide_recent_button.setProperty("compact", True)
        self.hide_recent_button.setEnabled(False)
        self.hide_recent_button.setToolTip(
            "Remove the selected item from this Dashboard list without deleting the transaction."
        )
        self.hide_recent_button.clicked.connect(self.hide_selected_recent)
        actions.addWidget(self.hide_recent_button)

        self.undo_hide_button = button("Undo Hide")
        self.undo_hide_button.setProperty("compact", True)
        self.undo_hide_button.setVisible(False)
        self.undo_hide_button.setToolTip(
            "Put the most recently hidden item back in Dashboard Recent Activity."
        )
        self.undo_hide_button.clicked.connect(self.undo_hide_recent)
        actions.addWidget(self.undo_hide_button)
        recent_card.body.addLayout(actions)

        recent_card.body.addWidget(self.table, 1)

        self.empty_label = text_label(
            "No recent activity yet. Add an income or expense from Transactions.",
            "muted",
        )
        self.empty_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        recent_card.body.addWidget(self.empty_label)

        self.feedback = text_label("", "muted")
        recent_card.body.addWidget(self.feedback)
        root.addWidget(recent_card, 1)

        self._apply_summary_density(self.width())
        self.refresh()

    def _summary_card(self, row: int, column: int, title: str, helper: str) -> QLabel:
        card = Card(title)
        card.setMinimumSize(0, 0)
        value = text_label("—", "metric")
        value.setWordWrap(False)
        value.setMinimumHeight(46)
        value.setTextInteractionFlags(Qt.TextInteractionFlag.NoTextInteraction)
        card.body.addWidget(value)
        card.body.addWidget(text_label(helper, "muted"))
        self.summary_grid.addWidget(card, row, column)
        self._summary_cards.append(card)
        self._metric_labels.append(value)
        return value

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._apply_summary_density(self.width())

    def _apply_summary_density(self, width: int) -> None:
        """Keep money values readable when the sidebar leaves less width."""
        compact = width < 760
        margins = 14 if compact else SPACE["lg"]
        spacing = SPACE["sm"] if compact else SPACE["md"]
        # Step 23 owns the responsive metric font size. Keep Dashboard from
        # pinning an inline 20 pt font, because inline QSS overrides the card-
        # width responsive rules and can make value/helper text overlap.
        metric_height = 30 if compact else 34
        for card in self._summary_cards:
            card.body.setContentsMargins(margins, margins, margins, margins)
            card.body.setSpacing(spacing)
        for value in self._metric_labels:
            value.setStyleSheet("")
            value.setMinimumHeight(metric_height)

    def refresh(self) -> None:
        summary = self.service.summary()
        self.balance_value.setText(
            format_minor(summary.current_balance_minor, self.currency_code, self.currency_symbol)
        )
        self.income_value.setText(
            format_minor(summary.month_income_minor, self.currency_code, self.currency_symbol)
        )
        self.expense_value.setText(
            format_minor(summary.month_expense_minor, self.currency_code, self.currency_symbol)
        )
        self.net_value.setText(
            format_minor(summary.month_net_minor, self.currency_code, self.currency_symbol)
        )
        self.period_label.setText(f"Summary for {summary.month_label}")
        self._load_recent()

    def _load_recent(self) -> None:
        records = self.service.recent_activity(limit=8)
        self._recent_ids = [record.id for record in records]
        self.table.setRowCount(len(records))

        for row, record in enumerate(records):
            values = (
                record.transaction_date,
                record.transaction_type.title(),
                record.category_name,
                record.description or "—",
                format_minor(
                    record.amount_minor,
                    self.currency_code,
                    self.currency_symbol,
                ),
            )
            for column, value in enumerate(values):
                item = QTableWidgetItem(value)
                if column == 4:
                    item.setTextAlignment(
                        Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
                    )
                self.table.setItem(row, column, item)

        self.empty_label.setVisible(not records)
        self.table.setVisible(bool(records))
        self.hide_recent_button.setEnabled(False)

    def _selection_changed(self) -> None:
        self.hide_recent_button.setEnabled(self.table.currentRow() >= 0)

    def hide_selected_recent(self) -> None:
        row = self.table.currentRow()
        if row < 0 or row >= len(self._recent_ids):
            self.feedback.setText("Select a recent item first.")
            return

        transaction_id = self._recent_ids[row]
        if not _confirm_hide_recent(self):
            return

        if self.service.hide_from_recent(transaction_id):
            self._last_hidden_id = transaction_id
            self._undo_hide_timer.start(10_000)
            self.undo_hide_button.setVisible(True)
            self.feedback.setText(
                "Hidden from Recent. The transaction is still saved in Transactions."
            )
            self._load_recent()
        else:
            self.feedback.setText(
                "That recent item could not be hidden because it is no longer available."
            )

    def undo_hide_recent(self) -> None:
        """Restore the latest Dashboard-only dismissal during the undo window."""
        if self._last_hidden_id is None:
            return
        transaction_id = self._last_hidden_id
        self._last_hidden_id = None
        self._undo_hide_timer.stop()
        self.undo_hide_button.setVisible(False)
        if self.service.restore_to_recent(transaction_id):
            self.feedback.setText("Recent item restored.")
        else:
            self.feedback.setText("That recent item could not be restored.")
        self._load_recent()

    def _expire_hide_undo(self) -> None:
        self._last_hidden_id = None
        self.undo_hide_button.setVisible(False)
