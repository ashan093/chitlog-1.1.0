"""Step 16 essential monthly financial reports."""
from __future__ import annotations

from PySide6.QtCore import QDate, QRectF, Qt
from PySide6.QtGui import QColor, QFontMetrics, QPainter, QPen
from PySide6.QtWidgets import (
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from chitlog.core.money import format_minor, minor_digits
from chitlog.services.report_service import (
    ExpenseCategoryReport,
    MonthlyTrendPoint,
    ReportService,
)
from chitlog.ui.theme import (
    BLUE_LAGOON,
    HEATHER,
    SCOOTER,
    SPACE,
    THEMES,
    resolve_theme,
)
from chitlog.ui.widgets import Card, button, text_label


def _theme_for(widget: QWidget):
    current = widget
    while current is not None:
        name = getattr(current, "theme_name", None)
        if name:
            return THEMES[resolve_theme(name)]
        current = current.parentWidget()
    return THEMES[resolve_theme("system")]


def _compact_money(amount_minor: int, currency_code: str, currency_symbol: str) -> str:
    digits = minor_digits(currency_code)
    value = amount_minor / (10 ** digits)
    absolute = abs(value)
    sign = "-" if value < 0 else ""
    if absolute >= 1_000_000:
        shown = f"{absolute / 1_000_000:.1f}M"
    elif absolute >= 1_000:
        shown = f"{absolute / 1_000:.1f}K"
    else:
        shown = f"{absolute:.0f}"
    return f"{sign}{currency_symbol} {shown}"


class MonthlyTrendChart(QWidget):
    """Small dependency-free grouped bar chart for six-month cash flow."""

    def __init__(self, currency_code: str, currency_symbol: str, parent=None):
        super().__init__(parent)
        self.currency_code = currency_code
        self.currency_symbol = currency_symbol
        self.points: list[MonthlyTrendPoint] = []
        self.setMinimumHeight(250)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

    def set_points(self, points: list[MonthlyTrendPoint]) -> None:
        self.points = list(points)
        self.update()

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        theme = _theme_for(self)
        text = QColor(theme.text)
        muted = QColor(theme.muted)
        border = QColor(theme.border)

        rect = self.rect()
        left, right, top, bottom = 68, 18, 42, 42
        chart = QRectF(
            left,
            top,
            max(1, rect.width() - left - right),
            max(1, rect.height() - top - bottom),
        )

        values = [
            value
            for point in self.points
            for value in (point.income_minor, point.expense_minor)
        ]
        maximum = max(values, default=0)
        maximum = max(maximum, 1)

        painter.setPen(QPen(border, 1))
        for line in range(5):
            ratio = line / 4
            y = chart.bottom() - chart.height() * ratio
            painter.drawLine(int(chart.left()), int(y), int(chart.right()), int(y))
            value = int(maximum * ratio)
            painter.setPen(muted)
            label = _compact_money(value, self.currency_code, self.currency_symbol)
            painter.drawText(
                QRectF(0, y - 9, left - 8, 18),
                Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
                label,
            )
            painter.setPen(QPen(border, 1))

        if not self.points:
            painter.setPen(muted)
            painter.drawText(chart, Qt.AlignmentFlag.AlignCenter, "No transaction data")
            return

        group_width = chart.width() / len(self.points)
        bar_width = max(7.0, min(24.0, group_width * 0.24))
        income_color = QColor(SCOOTER)
        expense_color = QColor(BLUE_LAGOON if resolve_theme(getattr(self.window(), "theme_name", "system")) == "light" else HEATHER)

        for index, point in enumerate(self.points):
            center = chart.left() + group_width * (index + 0.5)
            for offset, amount, color in (
                (-bar_width * 0.58, point.income_minor, income_color),
                (bar_width * 0.58, point.expense_minor, expense_color),
            ):
                bar_height = chart.height() * amount / maximum
                bar = QRectF(
                    center + offset - bar_width / 2,
                    chart.bottom() - bar_height,
                    bar_width,
                    bar_height,
                )
                painter.setPen(Qt.PenStyle.NoPen)
                painter.setBrush(color)
                painter.drawRoundedRect(bar, 3, 3)

            painter.setPen(text)
            painter.drawText(
                QRectF(
                    chart.left() + group_width * index,
                    chart.bottom() + 8,
                    group_width,
                    24,
                ),
                Qt.AlignmentFlag.AlignCenter,
                point.label,
            )

        # Legend.
        legend_y = 12
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(income_color)
        painter.drawRoundedRect(QRectF(chart.right() - 164, legend_y, 11, 11), 2, 2)
        painter.setPen(text)
        painter.drawText(QRectF(chart.right() - 148, 5, 62, 24), Qt.AlignmentFlag.AlignVCenter, "Income")
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(expense_color)
        painter.drawRoundedRect(QRectF(chart.right() - 82, legend_y, 11, 11), 2, 2)
        painter.setPen(text)
        painter.drawText(QRectF(chart.right() - 66, 5, 66, 24), Qt.AlignmentFlag.AlignVCenter, "Expenses")


class ExpenseCategoryChart(QWidget):
    """Horizontal bars for the selected month's largest expense categories."""

    def __init__(self, currency_code: str, currency_symbol: str, parent=None):
        super().__init__(parent)
        self.currency_code = currency_code
        self.currency_symbol = currency_symbol
        self.categories: list[ExpenseCategoryReport] = []
        self.setMinimumHeight(250)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

    def set_categories(self, categories: list[ExpenseCategoryReport]) -> None:
        values = list(categories)
        if len(values) > 6:
            other = sum(item.amount_minor for item in values[5:])
            values = values[:5] + [ExpenseCategoryReport("Other", other)]
        self.categories = values
        self.update()

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        theme = _theme_for(self)
        text = QColor(theme.text)
        muted = QColor(theme.muted)
        border = QColor(theme.border)
        accent = QColor(SCOOTER)

        if not self.categories:
            painter.setPen(muted)
            painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, "No expenses in this month")
            return

        maximum = max(item.amount_minor for item in self.categories) or 1
        rect = self.rect()
        top = 20
        bottom = 14
        row_height = max(28.0, (rect.height() - top - bottom) / len(self.categories))
        label_width = min(145.0, rect.width() * 0.30)
        amount_width = min(115.0, rect.width() * 0.26)
        bar_left = label_width + 10
        bar_right = rect.width() - amount_width - 12
        bar_width = max(35.0, bar_right - bar_left)
        metrics = QFontMetrics(painter.font())

        for index, item in enumerate(self.categories):
            center_y = top + row_height * (index + 0.5)
            category_rect = QRectF(0, center_y - row_height / 2, label_width - 8, row_height)
            elided = metrics.elidedText(
                item.category_name,
                Qt.TextElideMode.ElideRight,
                int(category_rect.width()),
            )
            painter.setPen(text)
            painter.drawText(
                category_rect,
                Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                elided,
            )

            background = QRectF(bar_left, center_y - 7, bar_width, 14)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(border)
            painter.drawRoundedRect(background, 7, 7)

            fill_width = bar_width * item.amount_minor / maximum
            painter.setBrush(accent)
            painter.drawRoundedRect(
                QRectF(bar_left, center_y - 7, max(2.0, fill_width), 14),
                7,
                7,
            )

            painter.setPen(text)
            painter.drawText(
                QRectF(bar_right + 8, center_y - row_height / 2, amount_width - 8, row_height),
                Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
                _compact_money(item.amount_minor, self.currency_code, self.currency_symbol),
            )


class ReportsPage(QWidget):
    """Essential monthly financial summaries and charts."""

    def __init__(
        self,
        service: ReportService,
        currency_code: str,
        currency_symbol: str,
        parent=None,
    ):
        super().__init__(parent)
        self.service = service
        self.currency_code = currency_code or "LKR"
        self.currency_symbol = currency_symbol or self.currency_code
        today = QDate.currentDate()
        self.selected_month = QDate(today.year(), today.month(), 1)
        self._summary_mode: str | None = None
        self._charts_mode: str | None = None

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(SPACE["md"])
        root.setAlignment(Qt.AlignmentFlag.AlignTop)

        intro = QVBoxLayout()
        intro.setSpacing(SPACE["xs"])
        intro.addWidget(text_label("MONTHLY FINANCIAL REPORT", "eyebrow"))
        intro.addWidget(
            text_label(
                "Income, expenses, net result, category spending, and recent monthly trend.",
                "muted",
            )
        )
        root.addLayout(intro)

        month_row = QHBoxLayout()
        month_row.setSpacing(SPACE["sm"])
        month_row.addStretch(1)
        self.previous_month_button = button("‹")
        self.previous_month_button.setFixedWidth(42)
        self.previous_month_button.setToolTip("Previous month")
        self.month_label = text_label("", "heading")
        self.month_label.setMinimumWidth(175)
        self.month_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.next_month_button = button("›")
        self.next_month_button.setFixedWidth(42)
        self.next_month_button.setToolTip("Next month")
        month_row.addWidget(self.previous_month_button)
        month_row.addWidget(self.month_label)
        month_row.addWidget(self.next_month_button)
        month_row.addStretch(1)
        root.addLayout(month_row)

        self.summary_grid = QGridLayout()
        self.summary_grid.setContentsMargins(0, 0, 0, 0)
        self.summary_grid.setHorizontalSpacing(SPACE["sm"])
        self.summary_grid.setVerticalSpacing(SPACE["sm"])

        self.income_card, self.income_value = self._metric_card("Income")
        self.expense_card, self.expense_value = self._metric_card("Expenses")
        self.net_card, self.net_value = self._metric_card("Net")
        self.count_card, self.count_value = self._metric_card("Transactions")
        self.summary_cards = (
            self.income_card,
            self.expense_card,
            self.net_card,
            self.count_card,
        )
        root.addLayout(self.summary_grid)

        self.charts_grid = QGridLayout()
        self.charts_grid.setContentsMargins(0, 0, 0, 0)
        self.charts_grid.setHorizontalSpacing(SPACE["md"])
        self.charts_grid.setVerticalSpacing(SPACE["md"])

        self.trend_card = Card("6-Month Income vs Expenses")
        self.trend_chart = MonthlyTrendChart(self.currency_code, self.currency_symbol)
        self.trend_card.body.addWidget(self.trend_chart)

        self.category_card = Card("Expense Categories")
        self.category_chart = ExpenseCategoryChart(self.currency_code, self.currency_symbol)
        self.category_card.body.addWidget(self.category_chart)

        root.addLayout(self.charts_grid)

        self.report_note = QLabel(
            "Reports use active transaction records only. Soft-deleted transactions are excluded."
        )
        self.report_note.setProperty("role", "muted")
        self.report_note.setWordWrap(True)
        root.addWidget(self.report_note)

        self.previous_month_button.clicked.connect(self._previous_month)
        self.next_month_button.clicked.connect(self._next_month)

        self._update_month_navigation()
        self._apply_responsive_layout(self.width())
        self.refresh()

    def _metric_card(self, title: str) -> tuple[Card, QLabel]:
        card = Card(title)
        value = text_label("—", "metric")
        value.setWordWrap(False)
        card.body.setContentsMargins(16, 10, 16, 10)
        card.body.setSpacing(4)
        card.setMinimumHeight(98)
        card.setMaximumHeight(112)
        card.body.addWidget(value)
        return card, value

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._apply_responsive_layout(event.size().width())

    def _apply_responsive_layout(self, width: int) -> None:
        summary_mode = "wide" if width >= 860 else "compact"
        if summary_mode != self._summary_mode:
            self._summary_mode = summary_mode
            for card in self.summary_cards:
                self.summary_grid.removeWidget(card)
            if summary_mode == "wide":
                for column, card in enumerate(self.summary_cards):
                    self.summary_grid.addWidget(card, 0, column)
            else:
                for index, card in enumerate(self.summary_cards):
                    self.summary_grid.addWidget(card, index // 2, index % 2)

        charts_mode = "wide" if width >= 980 else "stacked"
        if charts_mode != self._charts_mode:
            self._charts_mode = charts_mode
            self.charts_grid.removeWidget(self.trend_card)
            self.charts_grid.removeWidget(self.category_card)
            if charts_mode == "wide":
                self.charts_grid.addWidget(self.trend_card, 0, 0)
                self.charts_grid.addWidget(self.category_card, 0, 1)
            else:
                self.charts_grid.addWidget(self.trend_card, 0, 0)
                self.charts_grid.addWidget(self.category_card, 1, 0)

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
        self._update_month_navigation()
        self.refresh()

    def _next_month(self) -> None:
        today = QDate.currentDate()
        current = QDate(today.year(), today.month(), 1)
        candidate = self.selected_month.addMonths(1)
        if candidate > current:
            return
        self.selected_month = candidate
        self._update_month_navigation()
        self.refresh()

    def refresh(self) -> None:
        month = self._month_start_text()
        summary = self.service.monthly_report(month)
        categories = self.service.expense_categories(month)
        trend = self.service.monthly_trend(month, months=6)

        self.income_value.setText(
            format_minor(summary.income_minor, self.currency_code, self.currency_symbol)
        )
        self.expense_value.setText(
            format_minor(summary.expense_minor, self.currency_code, self.currency_symbol)
        )
        sign = "-" if summary.net_minor < 0 else ""
        self.net_value.setText(
            sign
            + format_minor(
                abs(summary.net_minor),
                self.currency_code,
                self.currency_symbol,
            )
        )
        self.count_value.setText(str(summary.transaction_count))
        self.trend_chart.set_points(trend)
        self.category_chart.set_categories(categories)
