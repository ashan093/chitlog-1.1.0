"""Dashboard Recent Activity action placement + behavior-source regression."""
from pathlib import Path


def test_hide_and_undo_actions_are_above_table_without_losing_safety_behavior():
    project = Path(__file__).resolve().parents[1]
    source = (
        project / "chitlog/ui/pages/dashboard.py"
    ).read_text(encoding="utf-8")

    action_layout = source.index("actions = QHBoxLayout()")
    action_add = source.index("recent_card.body.addLayout(actions)")
    table_add = source.index("recent_card.body.addWidget(self.table, 1)")

    assert action_layout < action_add < table_add
    assert 'self.hide_recent_button = button("Hide from Recent")' in source
    assert 'self.hide_recent_button.setProperty("compact", True)' in source
    assert 'self.undo_hide_button = button("Undo Hide")' in source
    assert 'self.undo_hide_button.setProperty("compact", True)' in source
    assert "actions.addStretch(1)" in source

    # Preserve the confirmed Step 8 non-destructive workflow.
    assert "if not _confirm_hide_recent(self):" in source
    assert "self._undo_hide_timer.start(10_000)" in source
    assert "def undo_hide_recent(self)" in source
    assert "self.service.restore_to_recent(transaction_id)" in source
