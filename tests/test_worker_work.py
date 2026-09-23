"""Worker monthly attendance and earning integrity tests."""
import secrets

import pytest

from chitlog.data.database import Database
from chitlog.data.worker_repository import WorkerRepository
from chitlog.data.worker_work_repository import WorkerWorkRepository
from chitlog.services.worker_service import WorkerError, WorkerInput, WorkerService
from chitlog.services.worker_work_service import (
    WorkerAttendanceInput,
    WorkerWorkError,
    WorkerWorkInput,
    WorkerWorkService,
)


@pytest.fixture
def services(tmp_path):
    db = Database(tmp_path / "work.db", secrets.token_bytes(32), tmp_path / "snapshots").open()
    workers_repo = WorkerRepository(db)
    workers = WorkerService(workers_repo, "LKR")
    work = WorkerWorkService(WorkerWorkRepository(db), workers_repo, "LKR")
    yield db, workers, work
    db.close()


def make_worker(workers, *, method="daily", rate="2500.00"):
    return workers.create_worker(
        WorkerInput(
            "Worker One",
            "permanent",
            payment_method=method,
            normal_rate=rate,
            date_added="2026-09-01",
        )
    )


def test_daily_attendance_counts_days_and_uses_default_rate(services):
    _db, workers, work = services
    worker_id = make_worker(workers, method="daily", rate="2500.00")
    work.create_attendance(worker_id, WorkerAttendanceInput("2026-09-02", "", "site"))
    work.create_attendance(worker_id, WorkerAttendanceInput("2026-09-05", "3000.00", "long day"))

    records = work.list_attendance_month(worker_id, "2026-09-01", "2026-09-30")
    summary = work.month_summary(worker_id, "2026-09-01", "2026-09-30")
    assert len(records) == 2
    assert summary.days_worked == 2
    assert summary.attendance_amount_minor == 550000
    assert summary.other_earnings_minor == 0
    assert summary.amount_to_pay_minor == 550000


def test_monthly_worker_gets_fixed_salary_plus_extra_earnings(services):
    _db, workers, work = services
    worker_id = make_worker(workers, method="monthly", rate="50000")
    attendance_id = work.create_attendance(
        worker_id, WorkerAttendanceInput("2026-09-03", "", "present")
    )
    work.create(
        worker_id,
        WorkerWorkInput("job", "2026-09-10", "2026-09-10", "2000", "extra work"),
    )
    attendance = work.get_attendance(attendance_id)
    summary = work.month_summary(worker_id, "2026-09-01", "2026-09-30")
    assert attendance.amount_minor == 0
    assert summary.days_worked == 1
    assert summary.attendance_amount_minor == 0
    assert summary.fixed_salary_minor == 5_000_000
    assert summary.other_earnings_minor == 200_000
    assert summary.amount_to_pay_minor == 5_200_000


def test_duplicate_worked_day_is_rejected_and_edit_can_keep_same_date(services):
    _db, workers, work = services
    worker_id = make_worker(workers)
    attendance_id = work.create_attendance(
        worker_id, WorkerAttendanceInput("2026-09-05", "2500", "first")
    )
    with pytest.raises(WorkerWorkError, match="already has"):
        work.create_attendance(worker_id, WorkerAttendanceInput("2026-09-05", "2500", "again"))
    work.update_attendance(
        attendance_id, WorkerAttendanceInput("2026-09-05", "2750", "updated")
    )
    assert work.get_attendance(attendance_id).amount_minor == 275000


def test_other_earning_types_are_kept_separate_from_attendance(services):
    _db, workers, work = services
    worker_id = make_worker(workers, method="job", rate="3500")
    job = work.create(worker_id, WorkerWorkInput("job", "2026-09-03", "2026-09-09", "3500.50", "job"))
    period = work.create(worker_id, WorkerWorkInput("period", "2026-09-04", "2026-09-10", "9000.00", "period"))
    monthly = work.create(worker_id, WorkerWorkInput("monthly", "2026-09-16", "2026-09-16", "50000.00", "salary"))

    assert work.get(job).start_date == work.get(job).end_date == "2026-09-03"
    assert work.get(period).start_date == "2026-09-04" and work.get(period).end_date == "2026-09-10"
    assert work.get(monthly).start_date == "2026-09-01"
    assert work.get(monthly).end_date == "2026-09-30"
    assert work.month_summary(worker_id, "2026-09-01", "2026-09-30").other_earnings_minor == 6_250_050
    with pytest.raises(WorkerWorkError, match="Worked Day"):
        work.create(worker_id, WorkerWorkInput("daily", "2026-09-12", "2026-09-12", "2500"))


def test_legacy_explicit_monthly_record_overrides_profile_salary_without_double_count(services):
    _db, workers, work = services
    worker_id = make_worker(workers, method="monthly", rate="50000")
    work.create(
        worker_id,
        WorkerWorkInput("monthly", "2026-09-03", "2026-09-03", "51000", "legacy override"),
    )
    summary = work.month_summary(worker_id, "2026-09-01", "2026-09-30")
    assert summary.fixed_salary_minor == 5_100_000
    assert summary.other_earnings_minor == 0
    assert summary.amount_to_pay_minor == 5_100_000


def test_monthly_salary_is_unique_per_worker_month(services):
    _db, workers, work = services
    worker_id = make_worker(workers, method="monthly", rate="50000")
    first = work.create(worker_id, WorkerWorkInput("monthly", "2026-09-03", "2026-09-03", "50000"))
    with pytest.raises(WorkerWorkError, match="already exists"):
        work.create(worker_id, WorkerWorkInput("monthly", "2026-09-20", "2026-09-20", "51000"))
    assert work.delete(first)
    second = work.create(worker_id, WorkerWorkInput("monthly", "2026-09-10", "2026-09-10", "51000"))
    with pytest.raises(WorkerWorkError, match="cannot be restored"):
        work.restore(first)
    assert work.get(second).amount_minor == 5_100_000


def test_attendance_soft_delete_and_undo_change_month_summary(services):
    _db, workers, work = services
    worker_id = make_worker(workers)
    attendance_id = work.create_attendance(worker_id, WorkerAttendanceInput("2026-09-05", "2500"))
    assert work.month_summary(worker_id, "2026-09-01", "2026-09-30").days_worked == 1
    assert work.delete_attendance(attendance_id)
    assert work.month_summary(worker_id, "2026-09-01", "2026-09-30").days_worked == 0
    assert work.restore_attendance(attendance_id)
    assert work.month_summary(worker_id, "2026-09-01", "2026-09-30").days_worked == 1


def test_dates_and_inactive_worker_are_validated(services):
    _db, workers, work = services
    worker_id = make_worker(workers)
    with pytest.raises(WorkerWorkError, match="before the worker"):
        work.create_attendance(worker_id, WorkerAttendanceInput("2026-08-31", "2500"))
    with pytest.raises(WorkerWorkError, match="End date"):
        work.create(worker_id, WorkerWorkInput("period", "2026-09-10", "2026-09-09", "100"))
    workers.deactivate_worker(worker_id)
    with pytest.raises(WorkerWorkError, match="Reactivate"):
        work.create_attendance(worker_id, WorkerAttendanceInput("2026-09-10", "2500"))


def test_worker_with_attendance_history_cannot_be_permanently_deleted(services):
    _db, workers, work = services
    worker_id = make_worker(workers)
    work.create_attendance(worker_id, WorkerAttendanceInput("2026-09-12", "2500", "worked"))
    with pytest.raises(WorkerError, match="cannot be permanently deleted"):
        workers.delete_worker_permanently(worker_id)
    assert workers.get_worker(worker_id) is not None


def test_worker_date_added_cannot_move_after_attendance(services):
    _db, workers, work = services
    worker_id = make_worker(workers)
    work.create_attendance(worker_id, WorkerAttendanceInput("2026-09-05", "2500"))
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


def test_half_day_defaults_to_half_daily_rate_and_is_reported(services):
    _db, workers, work = services
    worker_id = make_worker(workers, method="daily", rate="2500.00")
    attendance_id = work.create_attendance(
        worker_id,
        WorkerAttendanceInput(
            "2026-09-06",
            "",
            "half shift",
            "half_day",
            "",
        ),
    )
    record = work.get_attendance(attendance_id)
    assert record.duration_type == "half_day"
    assert record.hours_minutes == 0
    assert record.amount_minor == 125000

    summary = work.month_summary(worker_id, "2026-09-01", "2026-09-30")
    assert summary.days_worked == 1
    assert summary.full_days == 0
    assert summary.half_days == 1
    assert summary.hourly_minutes == 0
    assert summary.amount_to_pay_minor == 125000


def test_hourly_attendance_stores_minutes_and_uses_explicit_amount(services):
    _db, workers, work = services
    worker_id = make_worker(workers, method="daily", rate="2500.00")
    attendance_id = work.create_attendance(
        worker_id,
        WorkerAttendanceInput(
            "2026-09-07",
            "900.00",
            "three and a half hours",
            "hours",
            "3.5",
        ),
    )
    record = work.get_attendance(attendance_id)
    assert record.duration_type == "hours"
    assert record.hours_minutes == 210
    assert record.amount_minor == 90000

    summary = work.month_summary(worker_id, "2026-09-01", "2026-09-30")
    assert summary.days_worked == 1
    assert summary.full_days == 0
    assert summary.half_days == 0
    assert summary.hourly_minutes == 210
    assert summary.amount_to_pay_minor == 90000


def test_hourly_daily_worker_requires_explicit_amount_because_no_day_hours_are_assumed(services):
    _db, workers, work = services
    worker_id = make_worker(workers, method="daily", rate="2500.00")
    with pytest.raises(WorkerWorkError, match="actual earnings"):
        work.create_attendance(
            worker_id,
            WorkerAttendanceInput(
                "2026-09-07",
                "",
                "hours only",
                "hours",
                "3.5",
            ),
        )


def test_existing_style_attendance_defaults_to_full_day(services):
    _db, workers, work = services
    worker_id = make_worker(workers, method="daily", rate="2500.00")
    attendance_id = work.create_attendance(
        worker_id, WorkerAttendanceInput("2026-09-08", "", "legacy-style input")
    )
    record = work.get_attendance(attendance_id)
    assert record.duration_type == "full_day"
    assert record.hours_minutes == 0
    assert record.amount_minor == 250000
