"""Step 9 budget calculation and carry-forward tests."""
import secrets

import pytest

from chitlog.data.budget_repository import BudgetRepository
from chitlog.data.database import Database
from chitlog.data.transaction_repository import TransactionRepository
from chitlog.services.budget_service import BudgetError, BudgetService
from chitlog.services.transaction_service import TransactionInput, TransactionService


@pytest.fixture
def services(tmp_path):
    db = Database(tmp_path / "test.db", secrets.token_bytes(32), tmp_path / "snapshots").open()
    transactions = TransactionService(TransactionRepository(db), "USD")
    budget = BudgetService(BudgetRepository(db), "USD")
    yield db, transactions, budget
    db.close()


def category_id(transactions, name):
    return next(item.id for item in transactions.list_categories("expense") if item.name == name)


def add_expense(transactions, day, amount, category_name="Food"):
    return transactions.create_transaction(
        TransactionInput(
            transaction_type="expense",
            transaction_date=day,
            amount_text=amount,
            category_id=category_id(transactions, category_name),
            description="budget test",
        )
    )


def test_monthly_budget_spending_remaining_and_deleted_records(services):
    _db, transactions, budget = services
    budget.set_monthly_budget("2026-09", "1000.00", False)
    add_expense(transactions, "2026-09-01", "125.50")
    deleted_id = add_expense(transactions, "2026-09-30", "50.00")
    add_expense(transactions, "2026-10-01", "99.00")
    transactions.delete_transaction(deleted_id)

    status = budget.status("2026-09")
    assert status.base_budget_minor == 100000
    assert status.carry_in_minor == 0
    assert status.effective_budget_minor == 100000
    assert status.spent_minor == 12550
    assert status.remaining_minor == 87450
    assert status.used_percent == 13


def test_positive_unused_budget_carries_forward_idempotently(services):
    db, transactions, budget = services
    budget.set_monthly_budget("2026-01", "1000.00", True)
    add_expense(transactions, "2026-01-10", "200.00")

    first = budget.status("2026-02")
    second = budget.status("2026-02")
    assert first.carry_in_minor == 80000
    assert second.carry_in_minor == 80000
    assert db.connection.execute(
        "SELECT count(*) FROM budget_carry_forward WHERE target_month='2026-02'"
    ).fetchone()[0] == 1

    budget.set_monthly_budget("2026-02", "500.00", True)
    add_expense(transactions, "2026-02-11", "100.00")
    march = budget.status("2026-03")
    assert march.carry_in_minor == 120000


def test_overspending_never_creates_negative_carry(services):
    _db, transactions, budget = services
    budget.set_monthly_budget("2026-04", "100.00", True)
    add_expense(transactions, "2026-04-20", "150.00")
    may = budget.status("2026-05")
    assert may.carry_in_minor == 0


def test_disabling_carry_removes_derived_target_carry(services):
    db, transactions, budget = services
    budget.set_monthly_budget("2026-06", "500.00", True)
    add_expense(transactions, "2026-06-03", "100.00")
    assert budget.status("2026-07").carry_in_minor == 40000

    budget.set_monthly_budget("2026-06", "500.00", False)
    assert budget.status("2026-07").carry_in_minor == 0
    assert db.connection.execute(
        "SELECT count(*) FROM budget_carry_forward WHERE target_month='2026-07'"
    ).fetchone()[0] == 0


def test_category_budget_spending_percentage_and_removal(services):
    _db, transactions, budget = services
    food = category_id(transactions, "Food")
    budget.set_category_budget("2026-09", food, "300.00")
    add_expense(transactions, "2026-09-05", "120.00", "Food")

    status = budget.status("2026-09")
    item = next(row for row in status.category_budgets if row.category_id == food)
    assert item.budget_minor == 30000
    assert item.spent_minor == 12000
    assert item.remaining_minor == 18000
    assert item.used_percent == 40
    assert budget.remove_category_budget("2026-09", food) is True
    assert not budget.status("2026-09").category_budgets


def test_budget_validation_rejects_zero_bad_month_and_inactive_category(services):
    _db, transactions, budget = services
    with pytest.raises(BudgetError):
        budget.set_monthly_budget("bad", "100", False)
    with pytest.raises(BudgetError):
        budget.set_monthly_budget("2026-09", "0", False)

    food = category_id(transactions, "Food")
    transactions.set_category_active(food, False)
    with pytest.raises(BudgetError):
        budget.set_category_budget("2026-09", food, "10.00")
