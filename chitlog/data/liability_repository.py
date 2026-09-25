"""Parameterized SQL access for liabilities and liability payments."""
from __future__ import annotations

from dataclasses import dataclass

from chitlog.data.database import Database


@dataclass(frozen=True)
class LiabilityRecord:
    id: int
    name: str
    lender: str
    original_amount_minor: int
    start_date: str
    due_date: str | None
    notes: str
    created_at: str
    updated_at: str


@dataclass(frozen=True)
class LiabilityPaymentRecord:
    id: int
    liability_id: int
    payment_date: str
    amount_minor: int
    note: str
    is_deleted: bool
    created_at: str
    updated_at: str
    deleted_at: str | None


class LiabilityRepository:
    def __init__(self, database: Database):
        self.database = database

    @staticmethod
    def _payment_from_row(row) -> LiabilityPaymentRecord | None:
        if row is None:
            return None
        values = list(row)
        values[5] = bool(values[5])
        return LiabilityPaymentRecord(*values)

    def create_liability(
        self,
        *,
        name: str,
        lender: str,
        original_amount_minor: int,
        start_date: str,
        due_date: str | None,
        notes: str,
    ) -> int:
        with self.database.transaction() as connection:
            cursor = connection.execute(
                "INSERT INTO liabilities("
                "name,lender,original_amount_minor,start_date,due_date,notes"
                ") VALUES (?,?,?,?,?,?)",
                (name, lender, original_amount_minor, start_date, due_date, notes),
            )
            return int(cursor.lastrowid)

    def update_liability(
        self,
        liability_id: int,
        *,
        name: str,
        lender: str,
        original_amount_minor: int,
        start_date: str,
        due_date: str | None,
        notes: str,
        connection=None,
    ) -> bool:
        def write(tx):
            cursor = tx.execute(
                "UPDATE liabilities SET name=?,lender=?,original_amount_minor=?,"
                "start_date=?,due_date=?,notes=?,updated_at=CURRENT_TIMESTAMP "
                "WHERE id=? AND is_deleted=0",
                (
                    name,
                    lender,
                    original_amount_minor,
                    start_date,
                    due_date,
                    notes,
                    liability_id,
                ),
            )
            return cursor.rowcount == 1

        if connection is not None:
            return write(connection)
        with self.database.transaction() as tx:
            return write(tx)

    def get_liability(self, liability_id: int) -> LiabilityRecord | None:
        row = self.database.connection.execute(
            "SELECT id,name,lender,original_amount_minor,start_date,due_date,notes,"
            "created_at,updated_at FROM liabilities WHERE id=? AND is_deleted=0",
            (liability_id,),
        ).fetchone()
        return LiabilityRecord(*row) if row else None

    def list_liabilities(self) -> list[LiabilityRecord]:
        rows = self.database.connection.execute(
            "SELECT id,name,lender,original_amount_minor,start_date,due_date,notes,"
            "created_at,updated_at FROM liabilities WHERE is_deleted=0 "
            "ORDER BY CASE WHEN due_date IS NULL THEN 1 ELSE 0 END,due_date,id DESC"
        ).fetchall()
        return [LiabilityRecord(*row) for row in rows]

    def total_paid_minor(self, liability_id: int, *, connection=None) -> int:
        tx = connection if connection is not None else self.database.connection
        row = tx.execute(
            "SELECT COALESCE(SUM(amount_minor),0) FROM liability_payments "
            "WHERE liability_id=? AND is_deleted=0",
            (liability_id,),
        ).fetchone()
        return int(row[0])

    def add_payment(
        self,
        *,
        liability_id: int,
        payment_date: str,
        amount_minor: int,
        note: str,
        connection=None,
    ) -> int:
        def write(tx):
            cursor = tx.execute(
                "INSERT INTO liability_payments(liability_id,payment_date,amount_minor,note,updated_at) "
                "VALUES (?,?,?,?,CURRENT_TIMESTAMP)",
                (liability_id, payment_date, amount_minor, note),
            )
            return int(cursor.lastrowid)

        if connection is not None:
            return write(connection)
        with self.database.transaction() as tx:
            return write(tx)

    def update_payment(
        self,
        payment_id: int,
        *,
        payment_date: str,
        amount_minor: int,
        note: str,
        connection=None,
    ) -> bool:
        def write(tx):
            cursor = tx.execute(
                "UPDATE liability_payments SET payment_date=?,amount_minor=?,note=?,"
                "updated_at=CURRENT_TIMESTAMP WHERE id=? AND is_deleted=0",
                (payment_date, amount_minor, note, payment_id),
            )
            return cursor.rowcount == 1

        if connection is not None:
            return write(connection)
        with self.database.transaction() as tx:
            return write(tx)

    def get_payment(
        self,
        payment_id: int,
        *,
        include_deleted: bool = False,
        connection=None,
    ) -> LiabilityPaymentRecord | None:
        tx = connection if connection is not None else self.database.connection
        deleted_clause = "" if include_deleted else " AND is_deleted=0"
        row = tx.execute(
            "SELECT id,liability_id,payment_date,amount_minor,note,is_deleted,"
            "created_at,COALESCE(updated_at,created_at),deleted_at "
            "FROM liability_payments WHERE id=?" + deleted_clause,
            (payment_id,),
        ).fetchone()
        return self._payment_from_row(row)

    def list_payments(
        self,
        liability_id: int,
        *,
        include_deleted: bool = False,
        connection=None,
    ) -> list[LiabilityPaymentRecord]:
        tx = connection if connection is not None else self.database.connection
        deleted_clause = "" if include_deleted else " AND is_deleted=0"
        rows = tx.execute(
            "SELECT id,liability_id,payment_date,amount_minor,note,is_deleted,"
            "created_at,COALESCE(updated_at,created_at),deleted_at "
            "FROM liability_payments WHERE liability_id=?" + deleted_clause + " "
            "ORDER BY payment_date DESC,id DESC",
            (liability_id,),
        ).fetchall()
        return [self._payment_from_row(row) for row in rows]

    def soft_delete_payment(self, payment_id: int, *, connection=None) -> bool:
        def write(tx):
            cursor = tx.execute(
                "UPDATE liability_payments SET is_deleted=1,deleted_at=CURRENT_TIMESTAMP,"
                "updated_at=CURRENT_TIMESTAMP WHERE id=? AND is_deleted=0",
                (payment_id,),
            )
            return cursor.rowcount == 1

        if connection is not None:
            return write(connection)
        with self.database.transaction() as tx:
            return write(tx)

    def restore_payment(self, payment_id: int, *, connection=None) -> bool:
        def write(tx):
            cursor = tx.execute(
                "UPDATE liability_payments SET is_deleted=0,deleted_at=NULL,"
                "updated_at=CURRENT_TIMESTAMP WHERE id=? AND is_deleted=1",
                (payment_id,),
            )
            return cursor.rowcount == 1

        if connection is not None:
            return write(connection)
        with self.database.transaction() as tx:
            return write(tx)

    def soft_delete_liability(
        self,
        liability_id: int,
        *,
        keep_transaction_history: bool = True,
        connection=None,
    ) -> bool:
        """Hide a liability and persist the user's linked-transaction history choice."""
        def write(tx):
            cursor = tx.execute(
                "UPDATE liabilities SET is_deleted=1,deleted_at=CURRENT_TIMESTAMP,"
                "keep_transaction_history_on_delete=?,updated_at=CURRENT_TIMESTAMP "
                "WHERE id=? AND is_deleted=0",
                (1 if keep_transaction_history else 0, liability_id),
            )
            return cursor.rowcount == 1

        if connection is not None:
            return write(connection)
        with self.database.transaction() as tx:
            return write(tx)

    def restore_liability(self, liability_id: int, *, connection=None) -> bool:
        """Restore a previously soft-deleted liability without altering payment rows."""
        def write(tx):
            cursor = tx.execute(
                "UPDATE liabilities SET is_deleted=0,deleted_at=NULL,"
                "keep_transaction_history_on_delete=1,updated_at=CURRENT_TIMESTAMP "
                "WHERE id=? AND is_deleted=1",
                (liability_id,),
            )
            return cursor.rowcount == 1

        if connection is not None:
            return write(connection)
        with self.database.transaction() as tx:
            return write(tx)

    def aggregate_totals(self) -> tuple[int, int]:
        row = self.database.connection.execute(
            "SELECT COALESCE(SUM(l.original_amount_minor),0),"
            "COALESCE(SUM(p.paid_minor),0) "
            "FROM liabilities l LEFT JOIN ("
            "SELECT liability_id,SUM(amount_minor) AS paid_minor "
            "FROM liability_payments WHERE is_deleted=0 GROUP BY liability_id"
            ") p ON p.liability_id=l.id WHERE l.is_deleted=0"
        ).fetchone()
        return int(row[0]), int(row[1])
