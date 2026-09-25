from pathlib import Path


def source() -> str:
    root = Path(__file__).resolve().parents[1]
    return (root / "chitlog/ui/pages/liabilities.py").read_text(encoding="utf-8")


def test_delete_dialog_offers_keep_or_delete_transaction_history():
    text = source()
    assert 'button("Keep Transaction History")' in text
    assert 'button("Delete Transaction History", "danger")' in text
    assert 'keep_transaction_history=history_choice == "keep"' in text
    assert "self.linked_expenses_changed.emit()" in text


def test_payment_history_has_contextual_edit_delete_undo_controls():
    text = source()
    assert 'self.payment_edit_button = button("Edit")' in text
    assert 'self.payment_delete_button = button("Delete")' in text
    assert 'self.payment_undo_button = button("Undo")' in text
    assert "self.payments_table.itemSelectionChanged.connect(self._payment_selection_changed)" in text
    assert "def _edit_payment(self) -> None:" in text
    assert "def _delete_payment(self) -> None:" in text
    assert "def _undo_delete_payment(self) -> None:" in text


def test_payment_history_uses_normal_click_away_selection_reset():
    text = source()
    assert "self.payments_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)" in text
    assert "self.payments_table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)" in text
    assert 'self.payments_table.setProperty("preserveClickAwaySelection", True)' not in text


def test_payment_edit_delete_stay_visible_but_disabled_without_selection():
    text = source()
    setup = text[text.index('self.payment_edit_button = button("Edit")'):text.index('self.payments_table = QTableWidget')]
    assert "self.payment_edit_button.setEnabled(False)" in setup
    assert "self.payment_delete_button.setEnabled(False)" in setup
    assert "self.payment_edit_button.setVisible(False)" not in setup
    assert "self.payment_delete_button.setVisible(False)" not in setup
    selection = text[text.index("def _payment_selection_changed"):text.index("def _load_payments")]
    assert "self.payment_edit_button.setEnabled(selected)" in selection
    assert "self.payment_delete_button.setEnabled(selected)" in selection
    assert "self.payment_undo_button.setVisible(has_undo)" in selection
