"""Persistence for per-worker, per-month payroll carry-forward choices."""
from __future__ import annotations

from datetime import date

from chitlog.data.database import Database


class WorkerPayrollRepository:
    """Stores whether one worker's month-end due carries into the next month.

    No row means the legacy/default behavior: carry forward is enabled.
    """

    def __init__(self, database: Database):
        self.database = database

    @staticmethod
    def _normalize_month(month: str | date) -> str:
        if isinstance(month, date):
            parsed = month
        else:
            try:
                parsed = date.fromisoformat((month or "").strip())
            except ValueError:
                raise ValueError("Enter a valid payroll month.") from None
        return parsed.replace(day=1).isoformat()

    def carry_forward_for(self, worker_id: int, month: str | date) -> bool:
        month_start = self._normalize_month(month)
        row = self.database.connection.execute(
            "SELECT carry_forward FROM worker_payroll_carry_forward "
            "WHERE worker_id=? AND source_month=?",
            (worker_id, month_start),
        ).fetchone()
        # Existing data keeps the Step 14 behavior unless the user chooses otherwise.
        return True if row is None else bool(row[0])

    def set_carry_forward(
        self, worker_id: int, month: str | date, carry_forward: bool
    ) -> None:
        month_start = self._normalize_month(month)
        with self.database.transaction() as connection:
            connection.execute(
                "INSERT INTO worker_payroll_carry_forward("
                "worker_id,source_month,carry_forward"
                ") VALUES (?,?,?) "
                "ON CONFLICT(worker_id,source_month) DO UPDATE SET "
                "carry_forward=excluded.carry_forward,updated_at=CURRENT_TIMESTAMP",
                (worker_id, month_start, 1 if carry_forward else 0),
            )
