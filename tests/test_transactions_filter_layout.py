"""Regression checks for the compact Transactions filter/date-range layout."""
from pathlib import Path


def _source() -> str:
    return (Path(__file__).resolve().parents[1] / "chitlog/ui/pages/transactions.py").read_text(encoding="utf-8")


def test_transaction_controls_are_compact_left_aligned_and_keep_existing_features():
    source = _source()
    assert 'self.search.setPlaceholderText("Search transactions…")' in source
    assert 'self.search.setToolTip("Search description, category, or payment method")' in source
    assert "self.search.setClearButtonEnabled(True)" in source
    assert "filters.addWidget(self.search)" in source
    assert "filters.addWidget(self.type_filter)" in source
    assert "filters.addWidget(self.category_filter)" in source
    assert "filters.addWidget(self.refresh_button)" in source
    assert "filters.addStretch(1)" in source
    assert "filters.addWidget(self.search, 1)" not in source

    # Existing behavior remains wired exactly as before.
    assert 'self.use_date_range = _compact(QCheckBox("Date range"))' in source
    assert "date_filters.addWidget(self.start_date)" in source
    assert "date_filters.addWidget(self.end_date)" in source
    assert "self.refresh_button.clicked.connect(lambda *_: self.refresh())" in source
    assert "self.use_date_range.toggled.connect(self._toggle_date_range)" in source
    assert "self.search.textChanged.connect(lambda *_: self.refresh())" in source
    assert "self.previous_month_button.clicked.connect(self._show_previous_month)" in source
    assert "self.next_month_button.clicked.connect(self._show_next_month)" in source


def test_transaction_control_visual_order_is_search_type_category_refresh_then_date_range():
    source = _source()
    block = source[source.index("filters = QHBoxLayout()"):source.index("filter_block = QVBoxLayout()")]
    assert block.index("filters.addWidget(self.search)") < block.index("filters.addWidget(self.type_filter)")
    assert block.index("filters.addWidget(self.type_filter)") < block.index("filters.addWidget(self.category_filter)")
    assert block.index("filters.addWidget(self.category_filter)") < block.index("filters.addWidget(self.refresh_button)")
    assert block.index('self.use_date_range = _compact(QCheckBox("Date range"))') > block.index("filters.addStretch(1)")
