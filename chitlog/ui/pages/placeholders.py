"""Step 6 placeholder pages. No finance records are written or calculated here."""
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QGridLayout, QScrollArea, QVBoxLayout, QWidget

from chitlog.ui.theme import SPACE
from chitlog.ui.widgets import Card, text_label


PAGE_COPY = {
    "Dashboard": (
        "Your ChitLog overview will live here.",
        "Balances, monthly totals, recent activity, budget status, liabilities, and worker payment summaries will be connected in later steps.",
    ),
    "Transactions": (
        "Income and expense records.",
        "Transaction features are available after opening the encrypted ChitLog database. Preview-only mode keeps this page read-only.",
    ),
    "Budget": (
        "Monthly and category budgets.",
        "Budget allocation, spending progress, remaining amounts, and carry-forward will be implemented in Step 9.",
    ),
    "Liabilities": (
        "Loans and other money you owe.",
        "Liability records, payments, and outstanding balances will be implemented in Step 10.",
    ),
    "Workers": (
        "People who work for you.",
        "Permanent and temporary worker profiles, work records, payments, advances, and payroll summaries will be added in later worker steps.",
    ),
    "Reports": (
        "Useful financial and worker reports.",
        "Monthly summaries and charts will be connected after the underlying finance modules are complete.",
    ),
    "Settings": (
        "ChitLog preferences and security settings.",
        "The full Settings page will be completed later. Theme switching remains available in the top bar during development.",
    ),
}


class PlaceholderPage(QScrollArea):
    """Responsive empty state that scrolls instead of forcing the window larger."""

    def __init__(self, name: str):
        super().__init__()
        if name not in PAGE_COPY:
            raise ValueError(f"Unknown placeholder page: {name}")

        self.page_name = name
        self.setWidgetResizable(True)
        self.setFrameShape(QScrollArea.Shape.NoFrame)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setMinimumSize(0, 0)

        self.content = QWidget()
        self.content.setObjectName("content")
        self.content.setMinimumSize(0, 0)
        self.root = QVBoxLayout(self.content)
        self.root.setContentsMargins(0, 0, SPACE["sm"], 0)
        self.root.setSpacing(SPACE["lg"])

        title, description = PAGE_COPY[name]
        self.root.addWidget(text_label(name.upper(), "eyebrow"))
        self.root.addWidget(text_label(title, "title"))
        self.root.addWidget(text_label(description, "muted"))

        card = Card("Navigation ready", glass=True)
        card.body.addWidget(
            text_label(
                "This page is intentionally a placeholder at this checkpoint. No financial values are calculated or written here yet.",
                "muted",
            )
        )
        card.setMinimumHeight(150)
        self.root.addWidget(card)
        self.root.addStretch(1)
        self.setWidget(self.content)


class DashboardPlaceholder(PlaceholderPage):
    def __init__(self):
        super().__init__("Dashboard")

        grid = QGridLayout()
        grid.setHorizontalSpacing(SPACE["md"])
        grid.setVerticalSpacing(SPACE["md"])
        grid.setColumnStretch(0, 1)
        grid.setColumnStretch(1, 1)

        labels = (
            ("Current Balance", "—"),
            ("This Month Income", "—"),
            ("This Month Expenses", "—"),
            ("This Month Net", "—"),
        )
        for index, (label, value) in enumerate(labels):
            card = Card(label)
            metric = text_label(value, "metric")
            metric.setAlignment(Qt.AlignmentFlag.AlignLeft)
            card.body.addWidget(metric)
            card.body.addWidget(text_label("Not connected yet", "muted"))
            grid.addWidget(card, index // 2, index % 2)

        # Insert the summary grid before the navigation-ready card.
        self.root.insertLayout(3, grid)


def create_placeholder_page(name: str) -> QWidget:
    if name == "Dashboard":
        return DashboardPlaceholder()
    return PlaceholderPage(name)
