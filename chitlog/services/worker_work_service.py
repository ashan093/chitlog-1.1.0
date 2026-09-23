"""Business logic for worker attendance and monthly earning/work records."""
from __future__ import annotations

from calendar import monthrange
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP

from chitlog.core.money import MoneyError, parse_amount_to_minor
from chitlog.data.worker_repository import WorkerRepository
from chitlog.data.worker_work_repository import (
    WorkerAttendanceRecord,
    WorkerWorkRecord,
    WorkerWorkRepository,
)


EARNING_TYPES = {"job", "period", "monthly"}
ATTENDANCE_DURATION_TYPES = {"full_day", "half_day", "hours"}


def format_hours_minutes(minutes: int) -> str:
    minutes = max(0, int(minutes))
    hours, remainder = divmod(minutes, 60)
    if remainder == 0:
        return f"{hours} hour" + ("" if hours == 1 else "s")
    value = Decimal(minutes) / Decimal(60)
    text = format(value.quantize(Decimal("0.01")), "f").rstrip("0").rstrip(".")
    return f"{text} hours"


def attendance_duration_label(record) -> str:
    kind = getattr(record, "duration_type", "full_day")
    if kind == "half_day":
        return "Half day"
    if kind == "hours":
        return format_hours_minutes(getattr(record, "hours_minutes", 0))
    return "Full day"


class WorkerWorkError(ValueError):
    """Safe worker-work validation error for UI display."""


@dataclass(frozen=True)
class WorkerAttendanceInput:
    work_date: str
    amount_text: str = ""
    note: str = ""
    duration_type: str = "full_day"
    hours_text: str = ""


@dataclass(frozen=True)
class WorkerWorkInput:
    earning_type: str
    start_date: str
    end_date: str
    amount_text: str
    description: str = ""


@dataclass(frozen=True)
class WorkerMonthSummary:
    days_worked: int
    attendance_amount_minor: int
    fixed_salary_minor: int = 0
    other_earnings_minor: int = 0
    full_days: int = 0
    half_days: int = 0
    hourly_minutes: int = 0

    @property
    def amount_to_pay_minor(self) -> int:
        return (
            self.attendance_amount_minor
            + self.fixed_salary_minor
            + self.other_earnings_minor
        )


class WorkerWorkService:
    def __init__(
        self,
        repository: WorkerWorkRepository,
        worker_repository: WorkerRepository,
        currency_code: str,
    ):
        self.repository = repository
        self.worker_repository = worker_repository
        self.currency_code = currency_code

    @staticmethod
    def _date(value: str, field: str) -> date:
        try:
            return date.fromisoformat((value or "").strip())
        except ValueError:
            raise WorkerWorkError(f"Enter a valid {field}.") from None

    def _worker(self, worker_id: int, *, require_active: bool = False):
        worker = self.worker_repository.get_worker(worker_id)
        if worker is None:
            raise WorkerWorkError("That worker no longer exists.")
        if require_active and not worker.is_active:
            raise WorkerWorkError("Reactivate this worker before adding new work records.")
        return worker

    # ------------------------------ attendance ------------------------------
    def _validated_attendance(
        self,
        worker_id: int,
        item: WorkerAttendanceInput,
        *,
        existing_id: int | None = None,
        require_active_worker: bool = False,
    ) -> dict[str, object]:
        worker = self._worker(worker_id, require_active=require_active_worker)
        work_date = self._date(item.work_date, "work date")
        joined = date.fromisoformat(worker.date_added)
        if work_date < joined:
            raise WorkerWorkError("Work date cannot be before the worker's Date Added.")
        if work_date > date.today():
            raise WorkerWorkError("A worked day cannot be recorded in the future.")
        if self.repository.attendance_exists(worker_id, work_date.isoformat(), exclude_id=existing_id):
            raise WorkerWorkError("This worker already has a worked-day record for that date.")

        duration_type = (item.duration_type or "full_day").strip().lower()
        if duration_type not in ATTENDANCE_DURATION_TYPES:
            raise WorkerWorkError("Choose Full day, Half day, or Hours worked.")

        hours_minutes = 0
        if duration_type == "hours":
            hours_text = (item.hours_text or "").strip()
            try:
                hours = Decimal(hours_text)
            except (InvalidOperation, ValueError):
                raise WorkerWorkError("Enter valid hours worked, for example 3.5.") from None
            if hours <= 0 or hours > Decimal("24"):
                raise WorkerWorkError("Hours worked must be more than 0 and no more than 24.")
            hours_minutes = int(
                (hours * Decimal(60)).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
            )
            if hours_minutes <= 0 or hours_minutes > 1440:
                raise WorkerWorkError("Hours worked must be between 1 minute and 24 hours.")

        amount_text = (item.amount_text or "").strip()
        if amount_text:
            try:
                amount_minor = parse_amount_to_minor(amount_text, self.currency_code)
            except MoneyError as error:
                raise WorkerWorkError(str(error)) from None
        elif worker.payment_method == "daily" and worker.normal_rate_minor is not None:
            if duration_type == "full_day":
                amount_minor = int(worker.normal_rate_minor)
            elif duration_type == "half_day":
                # Exact minor-unit arithmetic; .5 of the smallest currency unit
                # rounds up rather than silently losing money.
                amount_minor = (int(worker.normal_rate_minor) + 1) // 2
            else:
                raise WorkerWorkError(
                    "Enter the actual earnings for an hourly work record. "
                    "ChitLog does not assume how many hours make a normal work day."
                )
        elif worker.payment_method == "daily":
            raise WorkerWorkError(
                "Enter earnings for this work record because this daily worker has no normal rate."
            )
        else:
            # Attendance can be informational for job/period/monthly workers.
            amount_minor = 0

        note = " ".join((item.note or "").strip().split())
        if len(note) > 500:
            raise WorkerWorkError("Attendance note must be 500 characters or fewer.")

        return {
            "work_date": work_date.isoformat(),
            "amount_minor": amount_minor,
            "note": note,
            "duration_type": duration_type,
            "hours_minutes": hours_minutes,
        }

    def create_attendance(self, worker_id: int, item: WorkerAttendanceInput) -> int:
        values = self._validated_attendance(worker_id, item, require_active_worker=True)
        return self.repository.create_attendance(worker_id=worker_id, **values)

    def update_attendance(self, attendance_id: int, item: WorkerAttendanceInput) -> None:
        record = self.repository.get_attendance(attendance_id)
        if record is None:
            raise WorkerWorkError("That worked-day record no longer exists.")
        values = self._validated_attendance(
            record.worker_id, item, existing_id=attendance_id
        )
        if not self.repository.update_attendance(attendance_id, **values):
            raise WorkerWorkError("That worked-day record could not be updated.")

    def get_attendance(
        self, attendance_id: int, *, include_deleted: bool = False
    ) -> WorkerAttendanceRecord | None:
        return self.repository.get_attendance(attendance_id, include_deleted=include_deleted)

    def list_attendance_month(
        self, worker_id: int, start_date: str, end_date: str
    ) -> list[WorkerAttendanceRecord]:
        if self.worker_repository.get_worker(worker_id) is None:
            return []
        return self.repository.list_attendance_month(worker_id, start_date, end_date)

    def delete_attendance(self, attendance_id: int) -> bool:
        return self.repository.soft_delete_attendance(attendance_id)

    def restore_attendance(self, attendance_id: int) -> bool:
        record = self.repository.get_attendance(attendance_id, include_deleted=True)
        if record is None or not record.is_deleted:
            return False
        if self.repository.attendance_exists(record.worker_id, record.work_date, exclude_id=record.id):
            raise WorkerWorkError(
                "This worked day cannot be restored because another record now exists for that date."
            )
        return self.repository.restore_attendance(attendance_id)

    # ---------------------------- other earnings ----------------------------
    def _validated(
        self,
        worker_id: int,
        item: WorkerWorkInput,
        *,
        existing_id: int | None = None,
        require_active_worker: bool = False,
    ) -> dict[str, object]:
        worker = self._worker(worker_id, require_active=require_active_worker)

        earning_type = (item.earning_type or "").strip().lower()
        if earning_type == "daily":
            raise WorkerWorkError("Use Worked Day to record attendance and daily earnings.")
        if earning_type not in EARNING_TYPES:
            raise WorkerWorkError("Choose Per Job, Custom Period, or Monthly Salary earnings.")

        start = self._date(item.start_date, "work date")
        end = self._date(item.end_date or item.start_date, "end date")
        joined = date.fromisoformat(worker.date_added)
        if start < joined:
            raise WorkerWorkError("Work date cannot be before the worker's Date Added.")

        if earning_type == "job":
            end = start
        elif earning_type == "monthly":
            start = start.replace(day=1)
            end = start.replace(day=monthrange(start.year, start.month)[1])
        elif end < start:
            raise WorkerWorkError("End date cannot be before the start date.")

        try:
            amount_minor = parse_amount_to_minor((item.amount_text or "").strip(), self.currency_code)
        except MoneyError as error:
            raise WorkerWorkError(str(error)) from None

        description = " ".join((item.description or "").strip().split())
        if len(description) > 500:
            raise WorkerWorkError("Work description must be 500 characters or fewer.")

        month_start = start.isoformat()
        if earning_type == "monthly" and self.repository.monthly_exists(
            worker_id, month_start, exclude_id=existing_id
        ):
            raise WorkerWorkError("A monthly salary earning already exists for this worker and month.")

        return {
            "earning_type": earning_type,
            "start_date": start.isoformat(),
            "end_date": end.isoformat(),
            "amount_minor": amount_minor,
            "description": description,
        }

    def create(self, worker_id: int, item: WorkerWorkInput) -> int:
        values = self._validated(worker_id, item, require_active_worker=True)
        return self.repository.create(worker_id=worker_id, **values)

    def update(self, record_id: int, item: WorkerWorkInput) -> None:
        record = self.repository.get(record_id)
        if record is None:
            raise WorkerWorkError("That earning record no longer exists.")
        if record.earning_type == "daily":
            raise WorkerWorkError("Legacy daily records are now stored as Worked Day attendance.")
        values = self._validated(record.worker_id, item, existing_id=record_id)
        if not self.repository.update(record_id, **values):
            raise WorkerWorkError("That earning record could not be updated.")

    def get(self, record_id: int, *, include_deleted: bool = False) -> WorkerWorkRecord | None:
        return self.repository.get(record_id, include_deleted=include_deleted)

    def list_for_worker(self, worker_id: int) -> list[WorkerWorkRecord]:
        if self.worker_repository.get_worker(worker_id) is None:
            return []
        return [r for r in self.repository.list_for_worker(worker_id) if r.earning_type != "daily"]

    def list_for_worker_month(
        self, worker_id: int, start_date: str, end_date: str
    ) -> list[WorkerWorkRecord]:
        if self.worker_repository.get_worker(worker_id) is None:
            return []
        return self.repository.list_for_worker_month(worker_id, start_date, end_date)

    def month_summary(self, worker_id: int, start_date: str, end_date: str) -> WorkerMonthSummary:
        worker = self.worker_repository.get_worker(worker_id)
        if worker is None:
            return WorkerMonthSummary(0, 0, 0, 0)

        days, attendance_total = self.repository.attendance_summary_month(
            worker_id, start_date, end_date
        )
        full_days, half_days, hourly_minutes = (
            self.repository.attendance_duration_summary_month(
                worker_id, start_date, end_date
            )
        )
        records = self.repository.list_for_worker_month(worker_id, start_date, end_date)
        monthly_records = [r for r in records if r.earning_type == "monthly"]
        extra_total = sum(r.amount_minor for r in records if r.earning_type != "monthly")

        fixed_salary = 0
        if worker.payment_method == "monthly":
            month_start = date.fromisoformat(start_date).replace(day=1)
            joined_month = date.fromisoformat(worker.date_added).replace(day=1)
            if month_start >= joined_month:
                # Existing explicit monthly records from older Step 12 builds are
                # treated as a salary override; otherwise the profile's fixed
                # monthly salary is used automatically. This avoids double pay.
                if monthly_records:
                    fixed_salary = monthly_records[0].amount_minor
                elif worker.normal_rate_minor is not None:
                    fixed_salary = int(worker.normal_rate_minor)
        else:
            # Preserve legacy/manual monthly earning records for non-monthly workers.
            extra_total += sum(r.amount_minor for r in monthly_records)

        return WorkerMonthSummary(
            days,
            attendance_total,
            fixed_salary,
            extra_total,
            full_days,
            half_days,
            hourly_minutes,
        )

    def total_for_worker(self, worker_id: int) -> int:
        return self.repository.total_for_worker(worker_id)

    def delete(self, record_id: int) -> bool:
        return self.repository.soft_delete(record_id)

    def restore(self, record_id: int) -> bool:
        record = self.repository.get(record_id, include_deleted=True)
        if record is None or not record.is_deleted:
            return False
        if record.earning_type == "daily":
            raise WorkerWorkError("Legacy daily records are now stored as Worked Day attendance.")
        if record.earning_type == "monthly" and self.repository.monthly_exists(
            record.worker_id, record.start_date, exclude_id=record.id
        ):
            raise WorkerWorkError(
                "This monthly earning cannot be restored because another monthly record now exists for that month."
            )
        return self.repository.restore(record_id)
