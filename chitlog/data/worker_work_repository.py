"""Parameterized SQL access for worker attendance and earning/work records."""
from __future__ import annotations

from dataclasses import dataclass

from chitlog.data.database import Database


@dataclass(frozen=True)
class WorkerWorkRecord:
    id: int
    worker_id: int
    earning_type: str
    start_date: str
    end_date: str
    amount_minor: int
    description: str
    is_deleted: bool
    created_at: str
    updated_at: str
    deleted_at: str | None


@dataclass(frozen=True)
class WorkerAttendanceRecord:
    id: int
    worker_id: int
    work_date: str
    amount_minor: int
    note: str
    duration_type: str
    hours_minutes: int
    is_deleted: bool
    created_at: str
    updated_at: str
    deleted_at: str | None


class WorkerWorkRepository:
    def __init__(self, database: Database):
        self.database = database

    @staticmethod
    def _row_to_record(row) -> WorkerWorkRecord | None:
        if row is None:
            return None
        values = list(row)
        values[7] = bool(values[7])
        return WorkerWorkRecord(*values)

    @staticmethod
    def _row_to_attendance(row) -> WorkerAttendanceRecord | None:
        if row is None:
            return None
        values = list(row)
        values[7] = bool(values[7])
        return WorkerAttendanceRecord(*values)

    # ------------------------------ attendance ------------------------------
    def create_attendance(
        self,
        *,
        worker_id: int,
        work_date: str,
        amount_minor: int,
        note: str,
        duration_type: str,
        hours_minutes: int,
    ) -> int:
        with self.database.transaction() as connection:
            cursor = connection.execute(
                "INSERT INTO worker_attendance("
                "worker_id,work_date,amount_minor,note,duration_type,hours_minutes"
                ") VALUES (?,?,?,?,?,?)",
                (worker_id, work_date, amount_minor, note, duration_type, hours_minutes),
            )
            return int(cursor.lastrowid)

    def update_attendance(
        self,
        attendance_id: int,
        *,
        work_date: str,
        amount_minor: int,
        note: str,
        duration_type: str,
        hours_minutes: int,
    ) -> bool:
        with self.database.transaction() as connection:
            cursor = connection.execute(
                "UPDATE worker_attendance SET work_date=?,amount_minor=?,note=?,"
                "duration_type=?,hours_minutes=?,updated_at=CURRENT_TIMESTAMP "
                "WHERE id=? AND is_deleted=0",
                (work_date, amount_minor, note, duration_type, hours_minutes, attendance_id),
            )
            return cursor.rowcount == 1

    def get_attendance(
        self, attendance_id: int, *, include_deleted: bool = False
    ) -> WorkerAttendanceRecord | None:
        clause = "" if include_deleted else " AND is_deleted=0"
        row = self.database.connection.execute(
            "SELECT id,worker_id,work_date,amount_minor,note,duration_type,hours_minutes,"
            "is_deleted,created_at,updated_at,deleted_at FROM worker_attendance "
            "WHERE id=?" + clause,
            (attendance_id,),
        ).fetchone()
        return self._row_to_attendance(row)

    def attendance_exists(
        self, worker_id: int, work_date: str, *, exclude_id: int | None = None
    ) -> bool:
        sql = (
            "SELECT 1 FROM worker_attendance WHERE worker_id=? AND work_date=? AND is_deleted=0"
        )
        params: list[object] = [worker_id, work_date]
        if exclude_id is not None:
            sql += " AND id<>?"
            params.append(exclude_id)
        sql += " LIMIT 1"
        return self.database.connection.execute(sql, params).fetchone() is not None

    def list_attendance_month(
        self, worker_id: int, start_date: str, end_date: str
    ) -> list[WorkerAttendanceRecord]:
        rows = self.database.connection.execute(
            "SELECT id,worker_id,work_date,amount_minor,note,duration_type,hours_minutes,"
            "is_deleted,created_at,updated_at,deleted_at FROM worker_attendance "
            "WHERE worker_id=? AND is_deleted=0 "
            "AND work_date>=? AND work_date<=? ORDER BY work_date DESC,id DESC",
            (worker_id, start_date, end_date),
        ).fetchall()
        return [self._row_to_attendance(row) for row in rows]

    def attendance_summary_month(self, worker_id: int, start_date: str, end_date: str) -> tuple[int, int]:
        row = self.database.connection.execute(
            "SELECT COUNT(*),COALESCE(SUM(amount_minor),0) FROM worker_attendance "
            "WHERE worker_id=? AND is_deleted=0 AND work_date>=? AND work_date<=?",
            (worker_id, start_date, end_date),
        ).fetchone()
        return int(row[0] or 0), int(row[1] or 0)

    def attendance_duration_summary_month(
        self, worker_id: int, start_date: str, end_date: str
    ) -> tuple[int, int, int]:
        row = self.database.connection.execute(
            "SELECT "
            "COALESCE(SUM(CASE WHEN duration_type='full_day' THEN 1 ELSE 0 END),0),"
            "COALESCE(SUM(CASE WHEN duration_type='half_day' THEN 1 ELSE 0 END),0),"
            "COALESCE(SUM(CASE WHEN duration_type='hours' THEN hours_minutes ELSE 0 END),0) "
            "FROM worker_attendance WHERE worker_id=? AND is_deleted=0 "
            "AND work_date>=? AND work_date<=?",
            (worker_id, start_date, end_date),
        ).fetchone()
        return int(row[0] or 0), int(row[1] or 0), int(row[2] or 0)

    def soft_delete_attendance(self, attendance_id: int) -> bool:
        with self.database.transaction() as connection:
            cursor = connection.execute(
                "UPDATE worker_attendance SET is_deleted=1,deleted_at=CURRENT_TIMESTAMP,"
                "updated_at=CURRENT_TIMESTAMP WHERE id=? AND is_deleted=0",
                (attendance_id,),
            )
            return cursor.rowcount == 1

    def restore_attendance(self, attendance_id: int) -> bool:
        with self.database.transaction() as connection:
            cursor = connection.execute(
                "UPDATE worker_attendance SET is_deleted=0,deleted_at=NULL,"
                "updated_at=CURRENT_TIMESTAMP WHERE id=? AND is_deleted=1",
                (attendance_id,),
            )
            return cursor.rowcount == 1

    # ------------------------------- earnings -------------------------------
    def create(
        self,
        *,
        worker_id: int,
        earning_type: str,
        start_date: str,
        end_date: str,
        amount_minor: int,
        description: str,
    ) -> int:
        with self.database.transaction() as connection:
            cursor = connection.execute(
                "INSERT INTO worker_work_records("
                "worker_id,earning_type,start_date,end_date,amount_minor,description"
                ") VALUES (?,?,?,?,?,?)",
                (worker_id, earning_type, start_date, end_date, amount_minor, description),
            )
            return int(cursor.lastrowid)

    def update(
        self,
        record_id: int,
        *,
        earning_type: str,
        start_date: str,
        end_date: str,
        amount_minor: int,
        description: str,
    ) -> bool:
        with self.database.transaction() as connection:
            cursor = connection.execute(
                "UPDATE worker_work_records SET earning_type=?,start_date=?,end_date=?,"
                "amount_minor=?,description=?,updated_at=CURRENT_TIMESTAMP "
                "WHERE id=? AND is_deleted=0",
                (earning_type, start_date, end_date, amount_minor, description, record_id),
            )
            return cursor.rowcount == 1

    def get(self, record_id: int, *, include_deleted: bool = False) -> WorkerWorkRecord | None:
        clause = "" if include_deleted else " AND is_deleted=0"
        row = self.database.connection.execute(
            "SELECT id,worker_id,earning_type,start_date,end_date,amount_minor,description,"
            "is_deleted,created_at,updated_at,deleted_at FROM worker_work_records "
            f"WHERE id=?{clause}",
            (record_id,),
        ).fetchone()
        return self._row_to_record(row)

    def list_for_worker(self, worker_id: int) -> list[WorkerWorkRecord]:
        rows = self.database.connection.execute(
            "SELECT id,worker_id,earning_type,start_date,end_date,amount_minor,description,"
            "is_deleted,created_at,updated_at,deleted_at FROM worker_work_records "
            "WHERE worker_id=? AND is_deleted=0 "
            "ORDER BY start_date DESC,end_date DESC,id DESC",
            (worker_id,),
        ).fetchall()
        return [self._row_to_record(row) for row in rows]

    def list_for_worker_month(
        self, worker_id: int, start_date: str, end_date: str
    ) -> list[WorkerWorkRecord]:
        rows = self.database.connection.execute(
            "SELECT id,worker_id,earning_type,start_date,end_date,amount_minor,description,"
            "is_deleted,created_at,updated_at,deleted_at FROM worker_work_records "
            "WHERE worker_id=? AND is_deleted=0 AND earning_type<>'daily' "
            "AND start_date>=? AND start_date<=? "
            "ORDER BY start_date DESC,end_date DESC,id DESC",
            (worker_id, start_date, end_date),
        ).fetchall()
        return [self._row_to_record(row) for row in rows]

    def total_for_worker(self, worker_id: int) -> int:
        row = self.database.connection.execute(
            "SELECT COALESCE(SUM(amount_minor),0) FROM worker_work_records "
            "WHERE worker_id=? AND is_deleted=0 AND earning_type<>'daily'",
            (worker_id,),
        ).fetchone()
        work_total = int(row[0] or 0)
        row = self.database.connection.execute(
            "SELECT COALESCE(SUM(amount_minor),0) FROM worker_attendance "
            "WHERE worker_id=? AND is_deleted=0",
            (worker_id,),
        ).fetchone()
        return work_total + int(row[0] or 0)

    def total_work_for_month(self, worker_id: int, start_date: str, end_date: str) -> int:
        row = self.database.connection.execute(
            "SELECT COALESCE(SUM(amount_minor),0) FROM worker_work_records "
            "WHERE worker_id=? AND is_deleted=0 AND earning_type<>'daily' "
            "AND start_date>=? AND start_date<=?",
            (worker_id, start_date, end_date),
        ).fetchone()
        return int(row[0] or 0)

    def monthly_exists(self, worker_id: int, month_start: str, *, exclude_id: int | None = None) -> bool:
        sql = (
            "SELECT 1 FROM worker_work_records WHERE worker_id=? AND earning_type='monthly' "
            "AND start_date=? AND is_deleted=0"
        )
        params: list[object] = [worker_id, month_start]
        if exclude_id is not None:
            sql += " AND id<>?"
            params.append(exclude_id)
        sql += " LIMIT 1"
        return self.database.connection.execute(sql, params).fetchone() is not None

    def soft_delete(self, record_id: int) -> bool:
        with self.database.transaction() as connection:
            cursor = connection.execute(
                "UPDATE worker_work_records SET is_deleted=1,deleted_at=CURRENT_TIMESTAMP,"
                "updated_at=CURRENT_TIMESTAMP WHERE id=? AND is_deleted=0",
                (record_id,),
            )
            return cursor.rowcount == 1

    def restore(self, record_id: int) -> bool:
        with self.database.transaction() as connection:
            cursor = connection.execute(
                "UPDATE worker_work_records SET is_deleted=0,deleted_at=NULL,"
                "updated_at=CURRENT_TIMESTAMP WHERE id=? AND is_deleted=1",
                (record_id,),
            )
            return cursor.rowcount == 1
