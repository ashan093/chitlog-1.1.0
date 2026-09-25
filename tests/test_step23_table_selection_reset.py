"""Regression checks for consistent table click-away and selection reset behavior."""
from pathlib import Path


def _project() -> Path:
    return Path(__file__).resolve().parents[1]


def test_click_away_rule_discovers_every_selectable_qtablewidget():
    source = (_project() / "chitlog/ui/step23_polish.py").read_text(encoding="utf-8")

    assert "self.root.findChildren(QTableWidget)" in source
    assert "SelectionMode.NoSelection" in source
    assert "app.installEventFilter(self)" in source
    assert "QEvent.Type.MouseButtonRelease" in source
    assert "if self._inside_table(watched):" in source
    assert "if not self._is_empty_background_target(watched):" in source
    assert "QTimer.singleShot(0, self.clear_table_selections)" in source


def test_click_away_clears_current_index_not_only_highlight():
    source = (_project() / "chitlog/ui/step23_polish.py").read_text(encoding="utf-8")

    assert "def clear_table_selections" in source
    assert "model.hasSelection() or model.currentIndex().isValid()" in source
    assert "model.clear()" in source


def test_liability_selection_uses_selected_rows_and_resets_after_delete_and_undo():
    source = (_project() / "chitlog/ui/pages/liabilities.py").read_text(encoding="utf-8")

    selected_block = source[source.index("    def _selected_id"):source.index("    def refresh", source.index("    def _selected_id"))]
    assert "selectionModel().selectedRows()" in selected_block
    assert "row = self.table.currentRow()" not in selected_block
    assert "def _clear_table_selection" in selected_block
    assert "model.clear()" in selected_block

    delete_block = source[source.index("    def _delete_liability"):source.index("    def _undo_delete_liability")]
    undo_block = source[source.index("    def _undo_delete_liability"):source.index("    def _expire_delete_undo")]
    assert "self.refresh()\n        self._clear_table_selection()" in delete_block
    assert "self.refresh()\n        self._clear_table_selection()" in undo_block


def test_click_away_only_uses_empty_background_not_controls_or_content():
    source = (_project() / "chitlog/ui/step23_polish.py").read_text(encoding="utf-8")

    assert "def _is_empty_background_target" in source
    # Buttons/inputs/views and text labels are content, not empty space.
    for token in (
        "QAbstractButton",
        "QAbstractItemView",
        "QComboBox",
        "QDateEdit",
        "QLineEdit",
        "QPlainTextEdit",
        "QScrollBar",
        "QSlider",
        "QSpinBox",
        "QDoubleSpinBox",
        "QTabBar",
        "QTextEdit",
        "QLabel",
    ):
        assert token in source
    assert 'property("keepTableSelectionOnClick")' in source
    assert "widget.layout() is not None" in source
    assert "or isinstance(widget, QFrame)" in source
    assert "or type(widget) is QWidget" in source
    assert "current.isCheckable()" in source
    assert "preserveClickAwaySelection" not in source


def test_legacy_worker_payroll_page_defers_to_global_selection_rule():
    source = (_project() / "chitlog/ui/pages/worker_payroll_summary.py").read_text(encoding="utf-8")
    assert "Global click-away selection handling" in source
    assert "self.installEventFilter(self)" not in source
    assert "def eventFilter(self, watched, event)" not in source
