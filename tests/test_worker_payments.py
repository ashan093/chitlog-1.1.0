"""Worker payment/advance integrity tests for Step 13."""
import secrets
from datetime import date, timedelta

import pytest

from chitlog.data.database import Database
from chitlog.data.worker_payment_repository import WorkerPaymentRepository
from chitlog.data.worker_repository import WorkerRepository
from chitlog.services.worker_payment_service import (
    WorkerPaymentError,
    WorkerPaymentInput,
    WorkerPaymentService,
)
from chitlog.services.worker_service import WorkerError, WorkerInput, WorkerService


@pytest.fixture
def services(tmp_path):
    db = Database(tmp_path / "payments.db", secrets.token_bytes(32), tmp_path / "snapshots").open()
    worker_repo = WorkerRepository(db)
    workers = WorkerService(worker_repo, "LKR")
    payments = WorkerPaymentService(WorkerPaymentRepository(db), worker_repo, "LKR")
    yield db, workers, payments
    db.close()


def make_worker(workers, *, method="daily", rate="2500"):
    return workers.create_worker(
        WorkerInput(
            "Worker One",
            "permanent",
            payment_method=method,
            normal_rate=rate,
            date_added="2026-09-01",
        )
    )


def test_all_payment_types_are_recorded_and_advances_are_not_double_counted(services):
    _db, workers, payments = services
    worker_id = make_worker(workers)
    for payment_type, amount in (
        ("normal", "1000"),
        ("end_of_day", "2500"),
        ("partial", "500"),
        ("salary", "4000"),
        ("advance", "1500"),
    ):
        payments.create(
            worker_id,
            WorkerPaymentInput("2026-09-10", amount, payment_type, payment_type),
        )

    totals = payments.month_totals(worker_id, "2026-09-01", "2026-09-30")
    assert totals.regular_payments_minor == 800_000
    assert totals.advances_minor == 150_000
    assert totals.total_money_given_minor == 950_000
    records = payments.list_for_worker_month(worker_id, "2026-09-01", "2026-09-30")
    assert len(records) == 5
    assert sum(r.amount_minor for r in records) == totals.total_money_given_minor


def test_soft_delete_and_restore_change_totals_exactly_once(services):
    _db, workers, payments = services
    worker_id = make_worker(workers)
    payment_id = payments.create(
        worker_id,
        WorkerPaymentInput("2026-09-11", "2000", "advance", "cash advance"),
    )
    assert payments.month_totals(worker_id, "2026-09-01", "2026-09-30").advances_minor == 200_000
    assert payments.delete(payment_id)
    totals = payments.month_totals(worker_id, "2026-09-01", "2026-09-30")
    assert totals.advances_minor == 0
    assert totals.total_money_given_minor == 0
    assert payments.restore(payment_id)
    totals = payments.month_totals(worker_id, "2026-09-01", "2026-09-30")
    assert totals.advances_minor == 200_000
    assert totals.total_money_given_minor == 200_000
    assert not payments.restore(payment_id)


def test_payment_edit_can_change_type_without_double_counting(services):
    _db, workers, payments = services
    worker_id = make_worker(workers)
    payment_id = payments.create(
        worker_id,
        WorkerPaymentInput("2026-09-12", "3000", "normal", "first"),
    )
    payments.update(
        payment_id,
        WorkerPaymentInput("2026-09-12", "3000", "advance", "changed to advance"),
    )
    totals = payments.month_totals(worker_id, "2026-09-01", "2026-09-30")
    assert totals.regular_payments_minor == 0
    assert totals.advances_minor == 300_000
    assert totals.total_money_given_minor == 300_000


def test_payment_dates_amount_and_type_are_validated(services):
    _db, workers, payments = services
    worker_id = make_worker(workers)
    with pytest.raises(WorkerPaymentError, match="before the worker"):
        payments.create(worker_id, WorkerPaymentInput("2026-08-31", "100", "normal"))
    future = (date.today() + timedelta(days=1)).isoformat()
    with pytest.raises(WorkerPaymentError, match="future"):
        payments.create(worker_id, WorkerPaymentInput(future, "100", "normal"))
    with pytest.raises(WorkerPaymentError, match="valid payment type"):
        payments.create(worker_id, WorkerPaymentInput("2026-09-10", "100", "bonus"))
    with pytest.raises(WorkerPaymentError):
        payments.create(worker_id, WorkerPaymentInput("2026-09-10", "0", "normal"))


def test_inactive_worker_can_still_receive_payment_for_outstanding_money(services):
    _db, workers, payments = services
    worker_id = make_worker(workers)
    workers.deactivate_worker(worker_id)
    payment_id = payments.create(
        worker_id,
        WorkerPaymentInput("2026-09-15", "2500", "partial", "settlement after deactivation"),
    )
    assert payments.get(payment_id).amount_minor == 250_000


def test_worker_with_payment_history_cannot_be_permanently_deleted(services):
    _db, workers, payments = services
    worker_id = make_worker(workers)
    payments.create(worker_id, WorkerPaymentInput("2026-09-15", "1000", "normal"))
    with pytest.raises(WorkerError, match="cannot be permanently deleted"):
        workers.delete_worker_permanently(worker_id)
    assert workers.get_worker(worker_id) is not None


def test_worker_date_added_cannot_move_after_payment_history(services):
    _db, workers, payments = services
    worker_id = make_worker(workers)
    payments.create(worker_id, WorkerPaymentInput("2026-09-05", "1000", "advance"))
    existing = workers.get_worker(worker_id)
    with pytest.raises(WorkerError, match="earliest work record"):
        workers.update_worker(
            worker_id,
            WorkerInput(
                existing.name,
                existing.worker_type,
                existing.phone,
                existing.address,
                existing.notes,
                existing.payment_method,
                "2500",
                "2026-09-06",
            ),
        )
