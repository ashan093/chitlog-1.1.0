"""Liability payments mirrored into Transactions without double counting or drift."""
import secrets

import pytest

from chitlog.data.database import Database
from chitlog.data.liability_repository import LiabilityRepository
from chitlog.data.settings_repository import SettingsRepository
from chitlog.data.transaction_repository import TransactionRepository
from chitlog.services.liability_service import (
    LiabilityInput,
    LiabilityPaymentInput,
    LiabilityService,
)
from chitlog.services.transaction_service import TransactionService


@pytest.fixture
def linked_services(tmp_path):
    db = Database(tmp_path / "test.db", secrets.token_bytes(32), tmp_path / "snapshots").open()
    liability = LiabilityService(LiabilityRepository(db), "LKR")
    settings = SettingsRepository(db)
    transactions = TransactionService(TransactionRepository(db), "LKR")
    yield db, liability, settings, transactions
    db.close()


def make_liability(service, name="Vehicle loan"):
    return service.create_liability(
        LiabilityInput(name, "Bank", "1000.00", "2026-09-01", notes="test liability")
    )


def test_liability_payment_creates_one_linked_expense_by_default(linked_services):
    db, service, settings, transactions = linked_services
    assert settings.liability_payments_in_transactions() is True
    liability_id = make_liability(service)
    payment_id = service.add_payment(
        liability_id,
        LiabilityPaymentInput("2026-09-20", "250.00", "installment"),
    )

    rows = db.connection.execute(
        "SELECT t.id,transaction_type,transaction_date,amount_minor,c.name,t.description,"
        "t.payment_method,t.is_deleted,t.liability_payment_id "
        "FROM transactions t JOIN categories c ON c.id=t.category_id "
        "WHERE t.liability_payment_id=?",
        (payment_id,),
    ).fetchall()
    assert len(rows) == 1
    transaction_id, kind, tx_date, amount, category, description, method, deleted, linked_id = rows[0]
    assert kind == "expense"
    assert tx_date == "2026-09-20"
    assert amount == 25_000
    assert category == "Bills"
    assert description == "Liability payment — Vehicle loan — installment"
    assert method == "Liability Payment"
    assert deleted == 0
    assert linked_id == payment_id
    assert transactions.linked_expense_source(transaction_id) == "liability_payment"
    assert transactions.linked_expense_reference(transaction_id) == (
        "liability_payment", payment_id
    )
    assert transactions.delete_transaction(transaction_id) is False
    assert transactions.undo_delete(transaction_id) is False


def test_setting_hides_and_restores_existing_link_without_duplicates(linked_services):
    db, service, settings, _ = linked_services
    liability_id = make_liability(service)
    payment_id = service.add_payment(
        liability_id, LiabilityPaymentInput("2026-09-20", "100.00", "first")
    )

    settings.set_liability_payments_in_transactions(False)
    assert settings.liability_payments_in_transactions() is False
    assert db.connection.execute(
        "SELECT is_deleted FROM transactions WHERE liability_payment_id=?", (payment_id,)
    ).fetchone()[0] == 1

    # Payments created while hidden still get one linked mirror, kept invisible.
    second_id = service.add_payment(
        liability_id, LiabilityPaymentInput("2026-09-21", "100.00", "second")
    )
    assert db.connection.execute(
        "SELECT is_deleted FROM transactions WHERE liability_payment_id=?", (second_id,)
    ).fetchone()[0] == 1

    settings.set_liability_payments_in_transactions(True)
    assert settings.liability_payments_in_transactions() is True
    assert db.connection.execute(
        "SELECT COUNT(*) FROM transactions WHERE liability_payment_id IN (?,?)",
        (payment_id, second_id),
    ).fetchone()[0] == 2
    assert db.connection.execute(
        "SELECT COUNT(*) FROM transactions WHERE liability_payment_id IN (?,?) AND is_deleted=0",
        (payment_id, second_id),
    ).fetchone()[0] == 2


def test_liability_rename_updates_linked_expense_description(linked_services):
    db, service, _, _ = linked_services
    liability_id = make_liability(service)
    payment_id = service.add_payment(
        liability_id, LiabilityPaymentInput("2026-09-20", "100.00", "installment")
    )
    service.update_liability(
        liability_id,
        LiabilityInput("Renamed loan", "Bank", "1000.00", "2026-09-01"),
    )
    description = db.connection.execute(
        "SELECT description FROM transactions WHERE liability_payment_id=?", (payment_id,)
    ).fetchone()[0]
    assert description == "Liability payment — Renamed loan — installment"


def test_reconciliation_recreates_missing_mirror_without_duplicate(linked_services):
    db, service, _, _ = linked_services
    liability_id = make_liability(service)
    payment_id = service.add_payment(
        liability_id, LiabilityPaymentInput("2026-09-20", "100.00", "repair")
    )
    with db.transaction() as tx:
        tx.execute("DELETE FROM transactions WHERE liability_payment_id=?", (payment_id,))
    service.reconcile_transaction_expenses()
    service.reconcile_transaction_expenses()
    assert db.connection.execute(
        "SELECT COUNT(*) FROM transactions WHERE liability_payment_id=?", (payment_id,)
    ).fetchone()[0] == 1


def test_payment_and_linked_expense_write_is_atomic(linked_services):
    db, service, _, _ = linked_services
    liability_id = make_liability(service)
    with db.transaction() as tx:
        tx.execute(
            "CREATE TRIGGER fail_liability_expense BEFORE INSERT ON transactions "
            "WHEN NEW.liability_payment_id IS NOT NULL BEGIN "
            "SELECT RAISE(ABORT,'forced mirror failure'); END"
        )
    before = db.connection.execute("SELECT COUNT(*) FROM liability_payments").fetchone()[0]
    with pytest.raises(Exception, match="forced mirror failure"):
        service.add_payment(
            liability_id, LiabilityPaymentInput("2026-09-20", "100.00", "must rollback")
        )
    assert db.connection.execute("SELECT COUNT(*) FROM liability_payments").fetchone()[0] == before


def test_kept_history_payment_can_be_deleted_and_restored_while_liability_stays_deleted(linked_services):
    db, service, _settings, transactions = linked_services
    liability_id = make_liability(service, "Archived loan")
    payment_id = service.add_payment(
        liability_id, LiabilityPaymentInput("2026-09-20", "125.00", "history")
    )
    transaction_id = db.connection.execute(
        "SELECT id FROM transactions WHERE liability_payment_id=?", (payment_id,)
    ).fetchone()[0]

    service.delete_liability(liability_id, keep_transaction_history=True)
    assert service.get_summary(liability_id) is None
    assert transactions.get_transaction(transaction_id) is not None

    assert service.delete_payment(payment_id) is True
    assert transactions.get_transaction(transaction_id) is None

    assert service.restore_payment(payment_id) is True
    assert service.get_summary(liability_id) is None
    assert transactions.get_transaction(transaction_id) is not None
