"""Parameterized SQL access for actual worker payments and advances."""
from __future__ import annotations

from dataclasses import dataclass

from chitlog.data.database import Database


@dataclass(frozen=True)
class WorkerPaymentRecord:
    id: int
    worker_id: int
    payment_date: str
    amount_minor: int
    payment_type: str
    note: str
    is_deleted: bool
    created_at: str
    updated_at: str
    deleted_at: str | None


@dataclass(frozen=True)
class WorkerPaymentMonthTotals:
    regular_payments_minor: int
    advances_minor: int

    @property
    def total_money_given_minor(self) -> int:
        return self.regular_payments_minor + self.advances_minor


class WorkerPaymentRepository:
    def __init__(self, database: Database):
        self.database = database

    @staticmethod
    def _row_to_record(row) -> WorkerPaymentRecord | None:
        if row is None:
            return None
        values = list(row)
        values[6] = bool(values[6])
        return WorkerPaymentRecord(*values)

    def create(
        self,
        *,
        worker_id: int,
        payment_date: str,
        amount_minor: int,
        payment_type: str,
        note: str,
        connection=None,
    ) -> int:
        def write(tx):
            cursor = tx.execute(
                "INSERT INTO worker_payments("
                "worker_id,payment_date,amount_minor,payment_type,note"
                ") VALUES (?,?,?,?,?)",
                (worker_id, payment_date, amount_minor, payment_type, note),
            )
            return int(cursor.lastrowid)

        if connection is not None:
            return write(connection)
        with self.database.transaction() as tx:
            return write(tx)

    def update(
        self,
        payment_id: int,
        *,
        payment_date: str,
        amount_minor: int,
        payment_type: str,
        note: str,
        connection=None,
    ) -> bool:
        def write(tx):
            cursor = tx.execute(
                "UPDATE worker_payments SET payment_date=?,amount_minor=?,payment_type=?,note=?,"
                "updated_at=CURRENT_TIMESTAMP WHERE id=? AND is_deleted=0",
                (payment_date, amount_minor, payment_type, note, payment_id),
            )
            return cursor.rowcount == 1

        if connection is not None:
            return write(connection)
        with self.database.transaction() as tx:
            return write(tx)

    def get(
        self, payment_id: int, *, include_deleted: bool = False
    ) -> WorkerPaymentRecord | None:
        clause = "" if include_deleted else " AND is_deleted=0"
        row = self.database.connection.execute(
            "SELECT id,worker_id,payment_date,amount_minor,payment_type,note,is_deleted,"
            "created_at,updated_at,deleted_at FROM worker_payments WHERE id=?" + clause,
            (payment_id,),
        ).fetchone()
        return self._row_to_record(row)

    def list_for_worker_month(
        self, worker_id: int, start_date: str, end_date: str
    ) -> list[WorkerPaymentRecord]:
        rows = self.database.connection.execute(
            "SELECT id,worker_id,payment_date,amount_minor,payment_type,note,is_deleted,"
            "created_at,updated_at,deleted_at FROM worker_payments "
            "WHERE worker_id=? AND is_deleted=0 AND payment_date>=? AND payment_date<=? "
            "ORDER BY payment_date DESC,id DESC",
            (worker_id, start_date, end_date),
        ).fetchall()
        return [self._row_to_record(row) for row in rows]

    def month_totals(
        self, worker_id: int, start_date: str, end_date: str
    ) -> WorkerPaymentMonthTotals:
        row = self.database.connection.execute(
            "SELECT "
            "COALESCE(SUM(CASE WHEN payment_type<>'advance' THEN amount_minor ELSE 0 END),0),"
            "COALESCE(SUM(CASE WHEN payment_type='advance' THEN amount_minor ELSE 0 END),0) "
            "FROM worker_payments WHERE worker_id=? AND is_deleted=0 "
            "AND payment_date>=? AND payment_date<=?",
            (worker_id, start_date, end_date),
        ).fetchone()
        return WorkerPaymentMonthTotals(int(row[0] or 0), int(row[1] or 0))

    def soft_delete(self, payment_id: int, *, connection=None) -> bool:
        def write(tx):
            cursor = tx.execute(
                "UPDATE worker_payments SET is_deleted=1,deleted_at=CURRENT_TIMESTAMP,"
                "updated_at=CURRENT_TIMESTAMP WHERE id=? AND is_deleted=0",
                (payment_id,),
            )
            return cursor.rowcount == 1

        if connection is not None:
            return write(connection)
        with self.database.transaction() as tx:
            return write(tx)

    def restore(self, payment_id: int, *, connection=None) -> bool:
        def write(tx):
            cursor = tx.execute(
                "UPDATE worker_payments SET is_deleted=0,deleted_at=NULL,"
                "updated_at=CURRENT_TIMESTAMP WHERE id=? AND is_deleted=1",
                (payment_id,),
            )
            return cursor.rowcount == 1

        if connection is not None:
            return write(connection)
        with self.database.transaction() as tx:
            return write(tx)
