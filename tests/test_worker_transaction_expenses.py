"""Worker payments are optionally mirrored into Transactions as linked expenses."""
import secrets

from chitlog.data.database import Database
from chitlog.data.settings_repository import SettingsRepository
from chitlog.data.transaction_repository import TransactionRepository
from chitlog.data.worker_payment_repository import WorkerPaymentRepository
from chitlog.data.worker_repository import WorkerRepository
from chitlog.services.transaction_service import TransactionService
from chitlog.services.worker_payment_service import WorkerPaymentInput, WorkerPaymentService
from chitlog.services.worker_service import WorkerInput, WorkerService


def _services(tmp_path):
    db = Database(tmp_path / "linked-expenses.db", secrets.token_bytes(32), tmp_path / "snapshots").open()
    worker_repo = WorkerRepository(db)
    workers = WorkerService(worker_repo, "LKR")
    payments = WorkerPaymentService(WorkerPaymentRepository(db), worker_repo, "LKR")
    transactions = TransactionService(TransactionRepository(db), "LKR")
    settings = SettingsRepository(db)
    return db, workers, payments, transactions, settings


def _worker(workers):
    return workers.create_worker(
        WorkerInput(
            "Nimal Perera",
            "permanent",
            payment_method="daily",
            normal_rate="2500",
            date_added="2026-09-01",
        )
    )


def test_worker_payment_and_advance_are_linked_expenses_by_default(tmp_path):
    db, workers, payments, transactions, settings = _services(tmp_path)
    try:
        assert settings.worker_payments_in_transactions() is True
        worker_id = _worker(workers)
        payment_id = payments.create(
            worker_id,
            WorkerPaymentInput("2026-09-20", "1000", "advance", "cash"),
        )
        expenses = transactions.list_transactions(transaction_type="expense")
        linked = [row for row in expenses if transactions.is_worker_payment_expense(row.id)]
        assert len(linked) == 1
        assert linked[0].amount_minor == 100_000
        assert linked[0].transaction_date == "2026-09-20"
        assert "Worker advance" in linked[0].description
        source = TransactionRepository(db).source_for(linked[0].id)
        assert source == ("worker_payment", payment_id)
        assert transactions.linked_expense_reference(linked[0].id) == (
            "worker_payment", payment_id
        )
    finally:
        db.close()


def test_worker_payment_edit_delete_and_restore_keep_one_expense_in_sync(tmp_path):
    db, workers, payments, transactions, _settings = _services(tmp_path)
    try:
        worker_id = _worker(workers)
        payment_id = payments.create(
            worker_id,
            WorkerPaymentInput("2026-09-20", "1000", "advance", "first"),
        )
        payments.update(
            payment_id,
            WorkerPaymentInput("2026-09-21", "1250", "normal", "updated"),
        )
        linked = [r for r in transactions.list_transactions(transaction_type="expense") if transactions.is_worker_payment_expense(r.id)]
        assert len(linked) == 1
        assert linked[0].amount_minor == 125_000
        assert linked[0].transaction_date == "2026-09-21"
        assert "Worker payment" in linked[0].description

        assert payments.delete(payment_id)
        assert not [r for r in transactions.list_transactions(transaction_type="expense") if transactions.is_worker_payment_expense(r.id)]
        assert payments.restore(payment_id)
        linked = [r for r in transactions.list_transactions(transaction_type="expense") if transactions.is_worker_payment_expense(r.id)]
        assert len(linked) == 1
        count = db.connection.execute(
            "SELECT COUNT(*) FROM transactions WHERE source_type='worker_payment' AND source_id=?",
            (payment_id,),
        ).fetchone()[0]
        assert count == 1
    finally:
        db.close()


def test_settings_toggle_hides_and_restores_linked_expenses_without_worker_data_loss(tmp_path):
    db, workers, payments, transactions, settings = _services(tmp_path)
    try:
        worker_id = _worker(workers)
        payment_id = payments.create(
            worker_id,
            WorkerPaymentInput("2026-09-20", "800", "partial", "part payment"),
        )
        settings.set_worker_payments_in_transactions(False)
        assert payments.get(payment_id) is not None
        assert not [r for r in transactions.list_transactions(transaction_type="expense") if transactions.is_worker_payment_expense(r.id)]

        settings.set_worker_payments_in_transactions(True)
        linked = [r for r in transactions.list_transactions(transaction_type="expense") if transactions.is_worker_payment_expense(r.id)]
        assert len(linked) == 1
        assert linked[0].amount_minor == 80_000
    finally:
        db.close()


def test_permanent_worker_delete_succeeds_after_payment_was_deleted_and_purges_mirror(tmp_path):
    db, workers, payments, _transactions, _settings = _services(tmp_path)
    try:
        worker_id = _worker(workers)
        payment_id = payments.create(
            worker_id,
            WorkerPaymentInput("2026-09-20", "900", "normal", "finished"),
        )
        linked_id = db.connection.execute(
            "SELECT id FROM transactions WHERE source_type='worker_payment' AND source_id=?",
            (payment_id,),
        ).fetchone()[0]

        assert payments.delete(payment_id) is True
        assert workers.permanent_delete_status(worker_id) == "deletable"
        workers.delete_worker_permanently(worker_id)

        assert workers.get_worker(worker_id) is None
        assert db.connection.execute(
            "SELECT COUNT(*) FROM worker_payments WHERE id=?", (payment_id,)
        ).fetchone()[0] == 0
        assert db.connection.execute(
            "SELECT COUNT(*) FROM transactions WHERE id=?", (linked_id,)
        ).fetchone()[0] == 0
        assert db.connection.execute("PRAGMA foreign_key_check").fetchall() == []
    finally:
        db.close()


def test_worker_payment_and_transaction_mirror_are_one_atomic_write(tmp_path):
    db, workers, payments, _transactions, _settings = _services(tmp_path)
    try:
        worker_id = _worker(workers)
        # A healthy ChitLog database always has an expense category, but removing
        # them here forces the mirror step to fail and proves the payment insert
        # rolls back instead of leaving a database mismatch.
        with db.transaction() as connection:
            connection.execute("DELETE FROM categories WHERE kind='expense'")

        import pytest
        from chitlog.services.worker_payment_service import WorkerPaymentError

        with pytest.raises(WorkerPaymentError, match="No expense category"):
            payments.create(
                worker_id,
                WorkerPaymentInput("2026-09-20", "500", "normal", "rollback check"),
            )

        assert db.connection.execute(
            "SELECT COUNT(*) FROM worker_payments WHERE worker_id=?", (worker_id,)
        ).fetchone()[0] == 0
        assert db.connection.execute(
            "SELECT COUNT(*) FROM transactions WHERE source_type='worker_payment'"
        ).fetchone()[0] == 0
    finally:
        db.close()


def test_worker_payment_reconciliation_repairs_missing_and_orphan_mirrors(tmp_path):
    db, workers, payments, _transactions, _settings = _services(tmp_path)
    try:
        worker_id = _worker(workers)
        payment_id = payments.create(
            worker_id,
            WorkerPaymentInput("2026-09-20", "700", "advance", "repair"),
        )
        with db.transaction() as connection:
            connection.execute(
                "DELETE FROM transactions WHERE source_type='worker_payment' AND source_id=?",
                (payment_id,),
            )
            category_id = connection.execute(
                "SELECT id FROM categories WHERE kind='expense' ORDER BY id LIMIT 1"
            ).fetchone()[0]
            connection.execute(
                "INSERT INTO transactions("
                "transaction_type,transaction_date,amount_minor,category_id,description,"
                "payment_method,source_type,source_id"
                ") VALUES ('expense','2026-09-20',100,?,'orphan','Worker Payment',"
                "'worker_payment',999999)",
                (category_id,),
            )

        payments.reconcile_transaction_expenses()

        assert db.connection.execute(
            "SELECT COUNT(*) FROM transactions WHERE source_type='worker_payment' AND source_id=?",
            (payment_id,),
        ).fetchone()[0] == 1
        assert db.connection.execute(
            "SELECT COUNT(*) FROM transactions WHERE source_type='worker_payment' AND source_id=999999"
        ).fetchone()[0] == 0
        assert db.connection.execute("PRAGMA foreign_key_check").fetchall() == []
    finally:
        db.close()


def test_reconciliation_does_not_falsely_touch_already_matching_transaction(tmp_path):
    db, workers, payments, _transactions, _settings = _services(tmp_path)
    try:
        worker_id = _worker(workers)
        payment_id = payments.create(
            worker_id,
            WorkerPaymentInput("2026-09-20", "650", "normal", "stable"),
        )
        with db.transaction() as connection:
            connection.execute(
                "UPDATE transactions SET updated_at='2000-01-01 00:00:00' "
                "WHERE source_type='worker_payment' AND source_id=?",
                (payment_id,),
            )

        payments.reconcile_transaction_expenses()

        updated_at = db.connection.execute(
            "SELECT updated_at FROM transactions "
            "WHERE source_type='worker_payment' AND source_id=?",
            (payment_id,),
        ).fetchone()[0]
        assert updated_at == "2000-01-01 00:00:00"
    finally:
        db.close()
