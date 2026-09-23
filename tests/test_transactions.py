"""Business and data-integrity tests for Step 7 transactions."""
import secrets

import pytest

from chitlog.data.database import Database
from chitlog.data.transaction_repository import TransactionRepository
from chitlog.services.transaction_service import TransactionError, TransactionInput, TransactionService


@pytest.fixture
def service(tmp_path):
    db = Database(tmp_path / "test.db", secrets.token_bytes(32), tmp_path / "snapshots").open()
    service = TransactionService(TransactionRepository(db), "LKR")
    yield service
    db.close()


def category_id(service, kind, name):
    return next(item.id for item in service.list_categories(kind) if item.name == name)


def test_default_categories_exist(service):
    expense = {item.name for item in service.list_categories("expense")}
    income = {item.name for item in service.list_categories("income")}
    assert {"Food", "Transport", "Bills", "Other"}.issubset(expense)
    assert {"Salary", "Business Income", "Other Income"}.issubset(income)


def test_other_categories_are_always_last(service):
    expense = [item.name for item in service.list_categories("expense")]
    income = [item.name for item in service.list_categories("income")]
    assert expense[-1] == "Other"
    assert income[-1] == "Other Income"

    service.add_category("expense", "ZZ Custom")
    service.add_category("income", "ZZ Income")
    expense = [item.name for item in service.list_categories("expense")]
    income = [item.name for item in service.list_categories("income")]
    assert expense[-1] == "Other"
    assert income[-1] == "Other Income"


def test_create_edit_totals_soft_delete_and_undo(service):
    salary = category_id(service, "income", "Salary")
    food = category_id(service, "expense", "Food")

    income_id = service.create_transaction(TransactionInput(
        "income", "2026-09-15", "1000.00", salary, "Salary", "Bank Transfer"
    ))
    expense_id = service.create_transaction(TransactionInput(
        "expense", "2026-09-15", "250.25", food, "Lunch", "Cash"
    ))
    assert service.totals() == (100000, 25025, 74975)

    service.update_transaction(expense_id, TransactionInput(
        "expense", "2026-09-15", "300.25", food, "Lunch and transport", "Cash"
    ))
    assert service.get_transaction(expense_id).description == "Lunch and transport"
    assert service.totals() == (100000, 30025, 69975)

    assert service.delete_transaction(income_id) is True
    assert service.get_transaction(income_id) is None
    assert service.totals() == (0, 30025, -30025)
    assert service.undo_delete(income_id) is True
    assert service.totals() == (100000, 30025, 69975)


def test_user_text_is_stored_as_data(service):
    other = category_id(service, "expense", "Other")
    text = "'); DROP TABLE transactions; -- <script>alert(1)</script>"
    transaction_id = service.create_transaction(TransactionInput(
        "expense", "2026-09-15", "12.50", other, text, "Other"
    ))
    assert service.get_transaction(transaction_id).description == text
    assert len(service.list_transactions(search="DROP TABLE")) == 1


def test_category_kind_and_archived_category_are_enforced(service):
    food = category_id(service, "expense", "Food")
    with pytest.raises(TransactionError):
        service.create_transaction(TransactionInput(
            "income", "2026-09-15", "10.00", food, "Wrong kind", None
        ))
    service.set_category_active(food, False)
    assert "Food" not in {item.name for item in service.list_categories("expense")}
    with pytest.raises(TransactionError):
        service.create_transaction(TransactionInput(
            "expense", "2026-09-15", "10.00", food, "Archived", None
        ))
    all_categories = service.list_categories("expense", include_inactive=True)
    assert any(item.name == "Food" and not item.is_active for item in all_categories)


def test_custom_category_add_rename_duplicate_and_restore(service):
    category = service.add_category("expense", "Garden")
    assert service.repository.get_category(category).name == "Garden"
    service.rename_category(category, "Farm")
    assert service.repository.get_category(category).name == "Farm"
    with pytest.raises(TransactionError):
        service.add_category("expense", "farm")
    service.set_category_active(category, False)
    service.set_category_active(category, True)
    assert service.repository.get_category(category).is_active is True



def test_transaction_filters_by_type_category_date_and_search(service):
    salary = category_id(service, "income", "Salary")
    food = category_id(service, "expense", "Food")
    service.create_transaction(TransactionInput(
        "income", "2026-08-31", "500.00", salary, "August salary", "Bank Transfer"
    ))
    service.create_transaction(TransactionInput(
        "expense", "2026-09-10", "20.00", food, "Lunch", "Cash"
    ))
    service.create_transaction(TransactionInput(
        "expense", "2026-09-20", "30.00", food, "Dinner", "Card"
    ))
    assert len(service.list_transactions(transaction_type="expense")) == 2
    assert len(service.list_transactions(category_id=food)) == 2
    assert len(service.list_transactions(start_date="2026-09-01", end_date="2026-09-15")) == 1
    assert service.list_transactions(search="Dinner")[0].description == "Dinner"
    with pytest.raises(TransactionError):
        service.list_transactions(start_date="2026-10-01", end_date="2026-09-01")

def test_invalid_inputs_do_not_create_partial_records(service):
    food = category_id(service, "expense", "Food")
    starting = len(service.list_transactions())
    bad_inputs = (
        TransactionInput("expense", "bad-date", "10.00", food),
        TransactionInput("expense", "2026-09-15", "0", food),
        TransactionInput("expense", "2026-09-15", "1.234", food),
        TransactionInput("expense", "2026-09-15", "10.00", -99),
    )
    for value in bad_inputs:
        with pytest.raises(TransactionError):
            service.create_transaction(value)
    assert len(service.list_transactions()) == starting
