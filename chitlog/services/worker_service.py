"""Validation and business logic for worker profiles."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from chitlog.core.money import MoneyError, parse_amount_to_minor
from chitlog.data.worker_repository import WorkerRecord, WorkerRepository


WORKER_TYPES = {"permanent", "temporary"}
PAYMENT_METHODS = {"daily", "job", "period", "monthly"}


class WorkerError(ValueError):
    """Safe worker validation error for display in the UI."""


@dataclass(frozen=True)
class WorkerInput:
    name: str
    worker_type: str
    phone: str = ""
    address: str = ""
    notes: str = ""
    payment_method: str = "daily"
    normal_rate: str = ""
    date_added: str = ""


@dataclass(frozen=True)
class WorkerCounts:
    total: int
    active: int
    inactive: int
    temporary: int


class WorkerService:
    def __init__(self, repository: WorkerRepository, currency_code: str):
        self.repository = repository
        self.currency_code = currency_code

    @staticmethod
    def _clean_text(value: str, *, field: str, max_length: int, required: bool = False) -> str:
        cleaned = " ".join((value or "").strip().split()) if field != "address" and field != "notes" else (value or "").strip()
        if required and not cleaned:
            raise WorkerError(f"Enter the worker {field}.")
        if len(cleaned) > max_length:
            raise WorkerError(f"Worker {field} must be {max_length} characters or fewer.")
        return cleaned

    @staticmethod
    def _validate_date(value: str) -> str:
        text = (value or "").strip()
        try:
            parsed = date.fromisoformat(text)
        except ValueError:
            raise WorkerError("Enter a valid date added.") from None
        return parsed.isoformat()

    def _validated(self, item: WorkerInput) -> dict[str, object]:
        name = self._clean_text(item.name, field="name", max_length=120, required=True)
        worker_type = (item.worker_type or "").strip().lower()
        if worker_type not in WORKER_TYPES:
            raise WorkerError("Choose Permanent or Temporary worker type.")
        phone = self._clean_text(item.phone, field="phone", max_length=40)
        address = self._clean_text(item.address, field="address", max_length=300)
        notes = self._clean_text(item.notes, field="notes", max_length=1000)
        payment_method = (item.payment_method or "").strip().lower()
        if payment_method not in PAYMENT_METHODS:
            raise WorkerError("Choose a valid default payment method.")
        date_added = self._validate_date(item.date_added)

        normal_rate_minor: int | None = None
        rate_text = (item.normal_rate or "").strip()
        if rate_text:
            try:
                normal_rate_minor = parse_amount_to_minor(rate_text, self.currency_code)
            except MoneyError as error:
                raise WorkerError(str(error)) from None
        elif payment_method == "daily":
            raise WorkerError("Enter the worker's normal daily rate.")
        elif payment_method == "monthly":
            raise WorkerError("Enter the worker's fixed monthly salary.")

        return {
            "name": name,
            "worker_type": worker_type,
            "phone": phone,
            "address": address,
            "notes": notes,
            "payment_method": payment_method,
            "normal_rate_minor": normal_rate_minor,
            "date_added": date_added,
        }

    def create_worker(self, item: WorkerInput) -> int:
        return self.repository.create_worker(**self._validated(item))

    def update_worker(self, worker_id: int, item: WorkerInput) -> None:
        if self.repository.get_worker(worker_id) is None:
            raise WorkerError("That worker no longer exists.")
        values = self._validated(item)
        earliest_work = self.repository.earliest_work_date(worker_id)
        if earliest_work is not None and str(values["date_added"]) > earliest_work:
            raise WorkerError(
                f"Date Added cannot be later than the worker's earliest work record ({earliest_work})."
            )
        if not self.repository.update_worker(worker_id, **values):
            raise WorkerError("That worker could not be updated.")

    def get_worker(self, worker_id: int) -> WorkerRecord | None:
        return self.repository.get_worker(worker_id)

    def list_workers(
        self,
        *,
        status: str = "active",
        worker_type: str = "all",
        search: str = "",
    ) -> list[WorkerRecord]:
        if status not in {"active", "inactive", "all"}:
            raise WorkerError("Invalid worker status filter.")
        if worker_type not in {"all", "permanent", "temporary"}:
            raise WorkerError("Invalid worker type filter.")
        return self.repository.list_workers(status=status, worker_type=worker_type, search=search)

    def deactivate_worker(self, worker_id: int) -> None:
        worker = self.repository.get_worker(worker_id)
        if worker is None:
            raise WorkerError("That worker no longer exists.")
        if not worker.is_active:
            return
        if not self.repository.set_active(worker_id, False):
            raise WorkerError("That worker could not be deactivated.")

    def reactivate_worker(self, worker_id: int) -> None:
        worker = self.repository.get_worker(worker_id)
        if worker is None:
            raise WorkerError("That worker no longer exists.")
        if worker.is_active:
            return
        if not self.repository.set_active(worker_id, True):
            raise WorkerError("That worker could not be reactivated.")


    def delete_worker_permanently(self, worker_id: int) -> None:
        """Irreversibly remove a worker profile when no history references it."""
        result = self.repository.delete_worker_permanently(worker_id)
        if result == "deleted":
            return
        if result == "history":
            raise WorkerError(
                "This worker has work, payment, or payroll history and cannot be permanently deleted. "
                "Deactivate the worker instead."
            )
        raise WorkerError("That worker no longer exists.")

    def counts(self) -> WorkerCounts:
        total, active, temporary = self.repository.counts()
        return WorkerCounts(total=total, active=active, inactive=total - active, temporary=temporary)
