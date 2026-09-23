"""Step 8 dashboard calculations and Hide from Recent integrity tests."""
from datetime import date
import secrets

import pytest

from chitlog.data.database import Database
from chitlog.data.transaction_repository import TransactionRepository
from chitlog.services.dashboard_service import DashboardService
from chitlog.services.transaction_service import TransactionInput, TransactionService


@pytest.fixture
def services(tmp_path):
    db = Database(
        tmp_path / "test.db",
        secrets.token_bytes(32),
        tmp_path / "snapshots",
    ).open()
    repository = TransactionRepository(db)
    transactions = TransactionService(repository, "LKR")
    dashboard = DashboardService(repository)
    yield transactions, dashboard, repository
    db.close()


def category_id(service, kind, name):
    return next(item.id for item in service.list_categories(kind) if item.name == name)


def test_dashboard_summary_uses_all_time_balance_and_current_month(services):
    transactions, dashboard, _repository = services
    salary = category_id(transactions, "income", "Salary")
    food = category_id(transactions, "expense", "Food")

    transactions.create_transaction(TransactionInput(
        "income", "2026-08-31", "1000.00", salary, "Previous month", "Bank Transfer"
    ))
    transactions.create_transaction(TransactionInput(
        "income", "2026-09-05", "500.00", salary, "September salary", "Bank Transfer"
    ))
    transactions.create_transaction(TransactionInput(
        "expense", "2026-09-10", "125.50", food, "Groceries", "Cash"
    ))

    summary = dashboard.summary(date(2026, 9, 16))
    assert summary.current_balance_minor == 137450
    assert summary.month_income_minor == 50000
    assert summary.month_expense_minor == 12550
    assert summary.month_net_minor == 37450
    assert summary.month_label == "September 2026"


def test_hide_from_recent_does_not_delete_or_change_totals(services):
    transactions, dashboard, repository = services
    salary = category_id(transactions, "income", "Salary")
    food = category_id(transactions, "expense", "Food")

    older = transactions.create_transaction(TransactionInput(
        "income", "2026-09-15", "100.00", salary, "Older", None
    ))
    latest = transactions.create_transaction(TransactionInput(
        "expense", "2026-09-16", "25.00", food, "Latest", None
    ))

    before_totals = transactions.totals()
    assert [record.id for record in dashboard.recent_activity()] == [latest, older]

    assert dashboard.hide_from_recent(latest) is True
    assert [record.id for record in dashboard.recent_activity()] == [older]

    # Hide from Recent has its own undo and never touches the real transaction.
    assert dashboard.restore_to_recent(latest) is True
    assert [record.id for record in dashboard.recent_activity()] == [latest, older]
    assert dashboard.hide_from_recent(latest) is True

    # The real transaction still exists, is searchable, and still affects totals.
    assert transactions.get_transaction(latest) is not None
    assert transactions.totals() == before_totals
    assert any(record.id == latest for record in transactions.list_transactions())
    assert repository.database.connection.execute(
        "SELECT is_deleted FROM transactions WHERE id=?", (latest,)
    ).fetchone() == (0,)

    # Hiding again is harmless and does not create duplicates.
    assert dashboard.hide_from_recent(latest) is False
    assert repository.database.connection.execute(
        "SELECT count(*) FROM dismissed_recent_items WHERE transaction_id=?", (latest,)
    ).fetchone()[0] == 1


def test_deleted_transactions_are_excluded_from_dashboard(services):
    transactions, dashboard, _repository = services
    salary = category_id(transactions, "income", "Salary")
    item = transactions.create_transaction(TransactionInput(
        "income", "2026-09-16", "300.00", salary, "Temporary", None
    ))
    assert dashboard.summary(date(2026, 9, 16)).month_income_minor == 30000
    assert dashboard.recent_activity()[0].id == item

    transactions.delete_transaction(item)
    summary = dashboard.summary(date(2026, 9, 16))
    assert summary.current_balance_minor == 0
    assert summary.month_income_minor == 0
    assert dashboard.recent_activity() == []
