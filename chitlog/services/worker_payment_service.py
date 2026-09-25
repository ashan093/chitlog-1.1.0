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

    def _include_in_transactions(self) -> bool:
        row = self.repository.database.connection.execute(
            "SELECT value FROM application_settings WHERE key=?",
            ("worker_payments_in_transactions",),
        ).fetchone()
        return row is None or str(row[0]) != "0"

    def _sync_transaction_expense(self, payment_id: int, *, connection=None) -> None:
        """Keep exactly one transaction expense linked to a worker payment/advance.

        When ``connection`` is supplied the payment row and its transaction mirror
        are changed inside the same database transaction.  This prevents a saved
        worker payment from being left without its matching expense if the second
        write fails.
        """
        record = self.repository.get(payment_id, include_deleted=True)
        if record is None:
            return
        worker = self.worker_repository.get_worker(record.worker_id)
        if worker is None:
            return
        db_connection = self.repository.database.connection
        category = db_connection.execute(
            "SELECT id FROM categories WHERE kind='expense' "
            "ORDER BY CASE WHEN lower(name)='salary payment' THEN 0 ELSE 1 END,id LIMIT 1"
        ).fetchone()
        if category is None:
            raise WorkerPaymentError("No expense category is available for worker payments.")

        prefix = "Worker advance" if record.payment_type == "advance" else "Worker payment"
        description = f"{prefix} — {worker.name}"
        if record.note:
            description += f" — {record.note}"
        description = description[:500]
        visible = self._include_in_transactions() and not record.is_deleted

        def sync(tx) -> None:
            linked = tx.execute(
                "SELECT id,transaction_type,transaction_date,amount_minor,category_id,"
                "description,payment_method,is_deleted,deleted_at FROM transactions "
                "WHERE source_type='worker_payment' AND source_id=?",
                (payment_id,),
            ).fetchone()
            deleted = 0 if visible else 1
            deleted_at_sql = None if visible else record.deleted_at
            target_deleted_at = (
                deleted_at_sql if deleted_at_sql else (None if visible else record.updated_at)
            )
            if linked is None:
                tx.execute(
                    "INSERT INTO transactions("
                    "transaction_type,transaction_date,amount_minor,category_id,description,"
                    "payment_method,is_deleted,deleted_at,source_type,source_id"
                    ") VALUES ('expense',?,?,?,?,?,?,?,?,?)",
                    (
                        record.payment_date, record.amount_minor, int(category[0]),
                        description, "Worker Payment", deleted, target_deleted_at,
                        "worker_payment", payment_id,
                    ),
                )
            else:
                target = (
                    "expense", record.payment_date, int(record.amount_minor), int(category[0]),
                    description, "Worker Payment", int(deleted), target_deleted_at,
                )
                current = (
                    str(linked[1]), str(linked[2]), int(linked[3]), int(linked[4]),
                    str(linked[5]), str(linked[6] or ""), int(linked[7]), linked[8],
                )
                # Startup reconciliation should be an integrity check, not an
                # artificial edit. Preserve updated_at when the mirror already
                # exactly matches the authoritative worker payment.
                if current == target:
                    return
                tx.execute(
                    "UPDATE transactions SET transaction_type='expense',transaction_date=?,"
                    "amount_minor=?,category_id=?,description=?,payment_method='Worker Payment',"
                    "is_deleted=?,deleted_at=?,updated_at=CURRENT_TIMESTAMP "
                    "WHERE id=?",
                    (
                        record.payment_date, record.amount_minor, int(category[0]), description,
                        deleted, target_deleted_at, int(linked[0]),
                    ),
                )

        if connection is not None:
            sync(connection)
        else:
            with self.repository.database.transaction() as tx:
                sync(tx)

    def reconcile_transaction_expenses(self) -> None:
        """Repair missing/orphaned worker-payment transaction mirrors safely.

        Schema v14 intentionally does not use a foreign key from Transactions back
        to worker_payments, so an interrupted older build could theoretically leave
        a missing or orphaned mirror.  Reconciliation is idempotent and keeps the
        database authoritative before the UI opens.
        """
        db = self.repository.database
        with db.transaction() as tx:
            payment_ids = [
                int(row[0])
                for row in tx.execute("SELECT id FROM worker_payments ORDER BY id").fetchall()
            ]
            for payment_id in payment_ids:
                self._sync_transaction_expense(payment_id, connection=tx)
            tx.execute(
                "DELETE FROM transactions WHERE source_type='worker_payment' "
                "AND NOT EXISTS (SELECT 1 FROM worker_payments wp "
                "WHERE wp.id=transactions.source_id)"
            )

    def create(self, worker_id: int, item: WorkerPaymentInput) -> int:
        values = self._validated(worker_id, item)
        with self.repository.database.transaction() as tx:
            payment_id = self.repository.create(worker_id=worker_id, connection=tx, **values)
            self._sync_transaction_expense(payment_id, connection=tx)
        return payment_id

    def update(self, payment_id: int, item: WorkerPaymentInput) -> None:
        existing = self.repository.get(payment_id)
        if existing is None:
            raise WorkerPaymentError("That payment record no longer exists.")
        values = self._validated(existing.worker_id, item)
        with self.repository.database.transaction() as tx:
            if not self.repository.update(payment_id, connection=tx, **values):
                raise WorkerPaymentError("That payment record could not be updated.")
            self._sync_transaction_expense(payment_id, connection=tx)

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
        with self.repository.database.transaction() as tx:
            changed = self.repository.soft_delete(payment_id, connection=tx)
            if changed:
                self._sync_transaction_expense(payment_id, connection=tx)
            return changed

    def restore(self, payment_id: int) -> bool:
        record = self.repository.get(payment_id, include_deleted=True)
        if record is None or not record.is_deleted:
            return False
        with self.repository.database.transaction() as tx:
            changed = self.repository.restore(payment_id, connection=tx)
            if changed:
                self._sync_transaction_expense(payment_id, connection=tx)
            return changed
