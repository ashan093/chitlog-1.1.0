"""Parameterized SQLite access for worker profiles."""
from __future__ import annotations

from dataclasses import dataclass

from chitlog.data.database import Database


@dataclass(frozen=True)
class WorkerRecord:
    id: int
    name: str
    worker_type: str
    phone: str
    address: str
    notes: str
    payment_method: str
    normal_rate_minor: int | None
    date_added: str
    is_active: bool
    created_at: str
    updated_at: str


class WorkerRepository:
    def __init__(self, database: Database):
        self.database = database

    def create_worker(
        self,
        *,
        name: str,
        worker_type: str,
        phone: str,
        address: str,
        notes: str,
        payment_method: str,
        normal_rate_minor: int | None,
        date_added: str,
    ) -> int:
        with self.database.transaction() as connection:
            cursor = connection.execute(
                "INSERT INTO workers("
                "name,worker_type,phone,address,notes,payment_method,normal_rate_minor,date_added"
                ") VALUES (?,?,?,?,?,?,?,?)",
                (
                    name,
                    worker_type,
                    phone,
                    address,
                    notes,
                    payment_method,
                    normal_rate_minor,
                    date_added,
                ),
            )
            return int(cursor.lastrowid)

    def update_worker(
        self,
        worker_id: int,
        *,
        name: str,
        worker_type: str,
        phone: str,
        address: str,
        notes: str,
        payment_method: str,
        normal_rate_minor: int | None,
        date_added: str,
    ) -> bool:
        with self.database.transaction() as connection:
            cursor = connection.execute(
                "UPDATE workers SET name=?,worker_type=?,phone=?,address=?,notes=?,"
                "payment_method=?,normal_rate_minor=?,date_added=?,updated_at=CURRENT_TIMESTAMP "
                "WHERE id=?",
                (
                    name,
                    worker_type,
                    phone,
                    address,
                    notes,
                    payment_method,
                    normal_rate_minor,
                    date_added,
                    worker_id,
                ),
            )
            return cursor.rowcount == 1

    def get_worker(self, worker_id: int) -> WorkerRecord | None:
        row = self.database.connection.execute(
            "SELECT id,name,worker_type,phone,address,notes,payment_method,normal_rate_minor,"
            "date_added,is_active,created_at,updated_at FROM workers WHERE id=?",
            (worker_id,),
        ).fetchone()
        if row is None:
            return None
        values = list(row)
        values[9] = bool(values[9])
        return WorkerRecord(*values)

    def list_workers(
        self,
        *,
        status: str = "active",
        worker_type: str = "all",
        search: str = "",
    ) -> list[WorkerRecord]:
        clauses: list[str] = []
        parameters: list[object] = []

        if status == "active":
            clauses.append("is_active=1")
        elif status == "inactive":
            clauses.append("is_active=0")
        elif status != "all":
            raise ValueError("Invalid worker status filter")

        if worker_type in {"permanent", "temporary"}:
            clauses.append("worker_type=?")
            parameters.append(worker_type)
        elif worker_type != "all":
            raise ValueError("Invalid worker type filter")

        text = search.strip()
        if text:
            clauses.append("(name LIKE ? ESCAPE '\\' OR phone LIKE ? ESCAPE '\\')")
            escaped = text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
            pattern = f"%{escaped}%"
            parameters.extend((pattern, pattern))

        where = " WHERE " + " AND ".join(clauses) if clauses else ""
        rows = self.database.connection.execute(
            "SELECT id,name,worker_type,phone,address,notes,payment_method,normal_rate_minor,"
            "date_added,is_active,created_at,updated_at FROM workers"
            + where
            + " ORDER BY is_active DESC,name COLLATE NOCASE,id DESC",
            tuple(parameters),
        ).fetchall()
        result: list[WorkerRecord] = []
        for row in rows:
            values = list(row)
            values[9] = bool(values[9])
            result.append(WorkerRecord(*values))
        return result

    def earliest_work_date(self, worker_id: int) -> str | None:
        """Return the earliest retained work or payment date for Date Added integrity."""
        tables = {
            row[0]
            for row in self.database.connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }
        dates: list[str] = []
        if "worker_work_records" in tables:
            row = self.database.connection.execute(
                "SELECT MIN(start_date) FROM worker_work_records "
                "WHERE worker_id=? AND is_deleted=0",
                (worker_id,),
            ).fetchone()
            if row and row[0]:
                dates.append(row[0])
        if "worker_attendance" in tables:
            row = self.database.connection.execute(
                "SELECT MIN(work_date) FROM worker_attendance "
                "WHERE worker_id=? AND is_deleted=0",
                (worker_id,),
            ).fetchone()
            if row and row[0]:
                dates.append(row[0])
        if "worker_payments" in tables:
            row = self.database.connection.execute(
                "SELECT MIN(payment_date) FROM worker_payments "
                "WHERE worker_id=? AND is_deleted=0",
                (worker_id,),
            ).fetchone()
            if row and row[0]:
                dates.append(row[0])
        return min(dates) if dates else None

    def set_active(self, worker_id: int, active: bool) -> bool:
        with self.database.transaction() as connection:
            cursor = connection.execute(
                "UPDATE workers SET is_active=?,updated_at=CURRENT_TIMESTAMP WHERE id=?",
                (1 if active else 0, worker_id),
            )
            return cursor.rowcount == 1


    @staticmethod
    def _worker_history_tables(connection) -> dict[str, set[str]]:
        """Return existing worker-history tables and their column names.

        Table names are application-owned constants.  Introspecting columns lets
        newer/older compatible databases be handled without assuming that every
        optional history table has soft-delete support.
        """
        candidates = (
            "worker_attendance",
            "worker_work_records",
            "worker_payments",
            "payroll_adjustments",
        )
        existing = {
            str(row[0])
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }
        result: dict[str, set[str]] = {}
        for table in candidates:
            if table not in existing:
                continue
            # Safe because ``table`` comes only from the fixed tuple above.
            columns = {
                str(row[1])
                for row in connection.execute(f"PRAGMA table_info({table})").fetchall()
            }
            result[table] = columns
        return result

    @classmethod
    def _has_retained_history(cls, connection, worker_id: int) -> bool:
        """Return True when non-deleted history still belongs to the worker."""
        for table, columns in cls._worker_history_tables(connection).items():
            sql = f"SELECT 1 FROM {table} WHERE worker_id=?"
            if "is_deleted" in columns:
                sql += " AND is_deleted=0"
            sql += " LIMIT 1"
            if connection.execute(sql, (worker_id,)).fetchone() is not None:
                return True
        return False

    def permanent_delete_status(self, worker_id: int) -> str:
        """Return ``deletable``, ``history``, or ``missing`` for the worker.

        Soft-deleted work/payment rows are not treated as live financial history.
        They are purged only if the user confirms permanent worker deletion.
        """
        connection = self.database.connection
        if connection.execute("SELECT 1 FROM workers WHERE id=?", (worker_id,)).fetchone() is None:
            return "missing"
        return "history" if self._has_retained_history(connection, worker_id) else "deletable"

    def delete_worker_permanently(self, worker_id: int) -> str:
        """Permanently remove a worker when no non-deleted history remains.

        A normal Delete/Undo operation keeps worker history as soft-deleted rows.
        Once the user separately confirms *permanent worker deletion*, those
        already-deleted rows and their linked transaction mirrors are purged so
        foreign keys cannot leave a recordless worker undeletable.
        """
        with self.database.transaction() as connection:
            if connection.execute(
                "SELECT 1 FROM workers WHERE id=?", (worker_id,)
            ).fetchone() is None:
                return "missing"

            if self._has_retained_history(connection, worker_id):
                return "history"

            table_columns = self._worker_history_tables(connection)

            # Remove linked transaction mirrors before deleting soft-deleted
            # worker payments.  dismissed_recent_items follows via ON DELETE CASCADE.
            if "worker_payments" in table_columns:
                tx_columns = {
                    str(row[1])
                    for row in connection.execute("PRAGMA table_info(transactions)").fetchall()
                }
                if {"source_type", "source_id"}.issubset(tx_columns):
                    connection.execute(
                        "DELETE FROM transactions WHERE source_type='worker_payment' "
                        "AND source_id IN (SELECT id FROM worker_payments "
                        "WHERE worker_id=? AND is_deleted=1)",
                        (worker_id,),
                    )

            # At this point no live history exists.  Purge only rows that are
            # explicitly soft-deleted; a table without is_deleted would already
            # have caused _has_retained_history() to block deletion above.
            for table, columns in table_columns.items():
                if "is_deleted" not in columns:
                    continue
                connection.execute(
                    f"DELETE FROM {table} WHERE worker_id=? AND is_deleted=1",
                    (worker_id,),
                )

            cursor = connection.execute(
                "DELETE FROM workers WHERE id=?",
                (worker_id,),
            )
            return "deleted" if cursor.rowcount == 1 else "missing"

    def counts(self) -> tuple[int, int, int]:
        row = self.database.connection.execute(
            "SELECT COUNT(*),"
            "SUM(CASE WHEN is_active=1 THEN 1 ELSE 0 END),"
            "SUM(CASE WHEN worker_type='temporary' THEN 1 ELSE 0 END) "
            "FROM workers"
        ).fetchone()
        return int(row[0]), int(row[1] or 0), int(row[2] or 0)
