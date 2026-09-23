"""Validation and business rules for actual worker payments and advances."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from chitlog.core.money import MoneyError, parse_amount_to_minor
from chitlog.data.worker_payment_repository import (
    WorkerPaymentMonthTotals,
    WorkerPaymentRecord,
    WorkerPaymentRepository,
)
from chitlog.data.worker_repository import WorkerRepository


PAYMENT_TYPES = {
    "normal",
    "end_of_day",
    "partial",
    "salary",
    "advance",
}


class WorkerPaymentError(ValueError):
    """Safe payment validation error for display in the UI."""


@dataclass(frozen=True)
class WorkerPaymentInput:
    payment_date: str
    amount_text: str
    payment_type: str
    note: str = ""


class WorkerPaymentService:
    def __init__(
        self,
        repository: WorkerPaymentRepository,
        worker_repository: WorkerRepository,
        currency_code: str,
    ):
        self.repository = repository
        self.worker_repository = worker_repository
        self.currency_code = currency_code

    @staticmethod
    def _date(value: str) -> date:
        try:
            return date.fromisoformat((value or "").strip())
        except ValueError:
            raise WorkerPaymentError("Enter a valid payment date.") from None

    def _validated(self, worker_id: int, item: WorkerPaymentInput) -> dict[str, object]:
        worker = self.worker_repository.get_worker(worker_id)
        if worker is None:
            raise WorkerPaymentError("That worker no longer exists.")

        payment_date = self._date(item.payment_date)
        joined = date.fromisoformat(worker.date_added)
        if payment_date < joined:
            raise WorkerPaymentError("Payment date cannot be before the worker's Date Added.")
        if payment_date > date.today():
            raise WorkerPaymentError("Payment date cannot be in the future.")

        payment_type = (item.payment_type or "").strip().lower()
        if payment_type not in PAYMENT_TYPES:
            raise WorkerPaymentError("Choose a valid payment type.")

        try:
            amount_minor = parse_amount_to_minor((item.amount_text or "").strip(), self.currency_code)
        except MoneyError as error:
            raise WorkerPaymentError(str(error)) from None

        note = " ".join((item.note or "").strip().split())
        if len(note) > 500:
            raise WorkerPaymentError("Payment note must be 500 characters or fewer.")

        return {
            "payment_date": payment_date.isoformat(),
            "amount_minor": amount_minor,
            "payment_type": payment_type,
            "note": note,
        }

    def create(self, worker_id: int, item: WorkerPaymentInput) -> int:
        return self.repository.create(worker_id=worker_id, **self._validated(worker_id, item))

    def update(self, payment_id: int, item: WorkerPaymentInput) -> None:
        existing = self.repository.get(payment_id)
        if existing is None:
            raise WorkerPaymentError("That payment record no longer exists.")
        values = self._validated(existing.worker_id, item)
        if not self.repository.update(payment_id, **values):
            raise WorkerPaymentError("That payment record could not be updated.")

    def get(
        self, payment_id: int, *, include_deleted: bool = False
    ) -> WorkerPaymentRecord | None:
        return self.repository.get(payment_id, include_deleted=include_deleted)

    def list_for_worker_month(
        self, worker_id: int, start_date: str, end_date: str
    ) -> list[WorkerPaymentRecord]:
        if self.worker_repository.get_worker(worker_id) is None:
            return []
        return self.repository.list_for_worker_month(worker_id, start_date, end_date)

    def month_totals(
        self, worker_id: int, start_date: str, end_date: str
    ) -> WorkerPaymentMonthTotals:
        if self.worker_repository.get_worker(worker_id) is None:
            return WorkerPaymentMonthTotals(0, 0)
        return self.repository.month_totals(worker_id, start_date, end_date)

    def delete(self, payment_id: int) -> bool:
        return self.repository.soft_delete(payment_id)

    def restore(self, payment_id: int) -> bool:
        record = self.repository.get(payment_id, include_deleted=True)
        if record is None or not record.is_deleted:
            return False
        return self.repository.restore(payment_id)
