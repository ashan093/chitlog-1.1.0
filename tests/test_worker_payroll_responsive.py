"""Deterministic checks for Step 14 payroll layout and selection behavior."""
from pathlib import Path


def test_payroll_layout_order_and_scrollable_table_are_defined():
    root = Path(__file__).resolve().parents[1]
    source = (root / "chitlog/ui/pages/worker_payroll_summary.py").read_text(encoding="utf-8")
    assert 'Card("Total Amount to Pay")' in source
    assert source.index('root.addWidget(self.cards_widget)') < source.index('root.addLayout(filters)')
    assert source.index('root.addLayout(filters)') < source.index('root.addLayout(month_row)')
    assert source.index('root.addLayout(month_row)') < source.index('root.addWidget(self.carry_control)')
    assert source.index('root.addWidget(self.carry_control)') < source.index('root.addWidget(self.table, 1)')
    assert 'ScrollBarAsNeeded' in source
    assert 'ResizeMode.Fixed' in source
    assert 'def _size_table_columns' in source
    assert 'self.carry_choice = button("Carry")' in source
    assert 'self.carry_choice.setCheckable(True)' in source
    assert 'def _set_global_carry_context' in source
    assert 'self.carry_choice.setText("Carry All")' in source
    assert 'status="all", worker_type="all", search=""' in source
    assert 'compact_list_widget' not in source
    assert '"Amount to Pay", "Money Given", "Remaining Due", "Status"' in source
    assert 'self.table.clearSelection()' in source
    assert 'self._show_total_cards()' in source
    assert source.count("carry_layout.addSpacing(8)") >= 2
    assert source.index('carry_layout.addWidget(self.select_slips_button)') < source.index('carry_layout.addSpacing(8)')
    assert source.index('carry_layout.addWidget(self.clear_slips_button)') < source.rindex('carry_layout.addSpacing(8)')
    assert source.rindex('carry_layout.addSpacing(8)') < source.index('carry_layout.addWidget(self.generate_slips_button)')
    carry_block = source[source.index('self.carry_control = QWidget()'):source.index('root.addWidget(self.carry_control)')]
    assert carry_block.index('carry_layout.addWidget(self.carry_choice)') < carry_block.index('carry_layout.addStretch(1)')
    assert carry_block.index('carry_layout.addStretch(1)') < carry_block.index('carry_layout.addWidget(self.select_slips_button)')


def test_workers_use_single_page_instead_of_fixed_child_tabs():
    root = Path(__file__).resolve().parents[1]
    main = (root / "chitlog/ui/main_window.py").read_text(encoding="utf-8")
    workers = (root / "chitlog/ui/pages/workers.py").read_text(encoding="utf-8")

    # The redesigned Workers area is one page. The old fixed child-tab
    # navigation must not be recreated in MainWindow.
    assert 'tabs_narrow = width < 650' not in main
    assert '("Profiles", "Records", "Payments", "Payroll")' not in main
    assert 'setTabToolTip' not in main
    assert 'return WorkersPage(' in main

    # Essential actions and monthly payroll remain available on that page.
    assert 'button("+ Add Worker", "primary")' in workers
    assert 'button("+ Work", "primary")' in workers
    assert 'button("+ Other Earning")' in workers
    assert 'button("+ Payment")' in workers
    assert 'button("+ Advance")' in workers
    assert 'Card("Monthly Payroll Overview")' in workers
    assert 'button("Generate Salary Slips")' in workers
    assert 'self.activity_table = QTableWidget(0, 5)' in workers
