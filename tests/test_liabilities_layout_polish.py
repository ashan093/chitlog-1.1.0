"""Liabilities layout polish regression checks."""
from pathlib import Path


def test_liability_actions_live_above_table_and_on_toolbar_right():
    project = Path(__file__).resolve().parents[1]
    source = (
        project / "chitlog/ui/pages/liabilities.py"
    ).read_text(encoding="utf-8")

    toolbar = source.index("self.table_toolbar = QGridLayout()")
    actions = source.index("self.actions_widget = QWidget()")
    table = source.index("self.table = QTableWidget(0, 7)")

    assert toolbar < actions < table
    assert "Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter" in source

    # Action order requested for the table toolbar.
    assert source.index('self.add_button = button("+ Liability"', actions) < source.index(
        'self.edit_button = button("Edit Liability")', actions
    )
    assert source.index('self.edit_button = button("Edit Liability")', actions) < source.index(
        'self.delete_button = button("Delete Liability"', actions
    )
    assert source.index('self.delete_button = button("Delete Liability"', actions) < source.index(
        'self.payment_button = button("Record Payment"', actions
    )
    assert source.index('self.payment_button = button("Record Payment"', actions) < source.index(
        'self.undo_delete_button = button("Undo Delete")', actions
    )


def test_liability_summary_and_filter_controls_are_compact_themed():
    project = Path(__file__).resolve().parents[1]
    source = (
        project / "chitlog/ui/pages/liabilities.py"
    ).read_text(encoding="utf-8")

    assert "summary_card.setMaximumHeight(132)" in source
    assert 'self.status_filter.setProperty("compact", True)' in source
    assert "self.status_filter.setMaximumWidth(148)" in source
    assert 'self.refresh_button.setProperty("compact", True)' in source
    assert "self.refresh_button.setMaximumWidth(88)" in source

    for name in (
        "self.add_button",
        "self.edit_button",
        "self.delete_button",
        "self.payment_button",
        "self.undo_delete_button",
    ):
        assert f'{name}.setProperty("compact", True)' not in source
    # Buttons are compacted through the shared loop to preserve consistency.
    assert 'action_button.setProperty("compact", True)' in source


def test_liability_toolbar_remains_responsive_above_table():
    project = Path(__file__).resolve().parents[1]
    source = (
        project / "chitlog/ui/pages/liabilities.py"
    ).read_text(encoding="utf-8")

    assert "def _set_header_compact(self, compact: bool)" in source
    assert "self.table_toolbar.removeWidget(self.filter_widget)" in source
    assert "self.table_toolbar.removeWidget(self.actions_widget)" in source
    assert "self.actions_widget,\n                1,\n                0,\n                1,\n                2," in source
