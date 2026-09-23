"""Step 14 carry-forward choice and payroll calculation tests."""
from types import SimpleNamespace

from chitlog.services.worker_payroll_service import WorkerPayrollService
from chitlog.services.worker_work_service import WorkerMonthSummary
from chitlog.data.worker_payment_repository import WorkerPaymentMonthTotals


class FakeWorkerRepository:
    def get_worker(self, worker_id):
        if worker_id != 1:
            return None
        return SimpleNamespace(id=1, date_added="2026-08-10")


class FakeWorkService:
    def __init__(self):
        self.values = {
            "2026-08-01": 20_000,
            "2026-09-01": 50_000,
            "2026-10-01": 30_000,
        }

    def month_summary(self, worker_id, start_date, end_date):
        return WorkerMonthSummary(
            days_worked=0,
            attendance_amount_minor=0,
            fixed_salary_minor=0,
            other_earnings_minor=self.values.get(start_date, 0),
        )


class FakePaymentService:
    def __init__(self):
        self.values = {
            "2026-08-01": WorkerPaymentMonthTotals(5_000, 0),
            "2026-09-01": WorkerPaymentMonthTotals(20_000, 10_000),
            "2026-10-01": WorkerPaymentMonthTotals(45_000, 0),
        }

    def month_totals(self, worker_id, start_date, end_date):
        return self.values.get(start_date, WorkerPaymentMonthTotals(0, 0))


class FakeCarryRepository:
    def __init__(self):
        self.choices = {}

    def carry_forward_for(self, worker_id, month):
        month_start = WorkerPayrollService._month_start(month).isoformat()
        return self.choices.get((worker_id, month_start), True)

    def set_carry_forward(self, worker_id, month, carry_forward):
        month_start = WorkerPayrollService._month_start(month).isoformat()
        self.choices[(worker_id, month_start)] = bool(carry_forward)


def test_default_keeps_legacy_carry_forward_behavior():
    service = WorkerPayrollService(
        FakeWorkerRepository(), FakeWorkService(), FakePaymentService()
    )
    september = service.summary_for_worker(1, "2026-09-01")
    assert september.previous_unpaid_minor == 15_000
    assert september.remaining_due_minor == 35_000


def test_user_can_stop_one_workers_one_month_balance_from_carrying():
    choices = FakeCarryRepository()
    service = WorkerPayrollService(
        FakeWorkerRepository(),
        FakeWorkService(),
        FakePaymentService(),
        choices,
    )

    # August leaves Rs 15,000 due, but the user decides not to carry it.
    service.set_carry_forward(1, "2026-08-01", False)
    september = service.summary_for_worker(1, "2026-09-01")
    assert september.previous_unpaid_minor == 0
    assert september.remaining_due_minor == 20_000

    # September can independently be carried again.
    service.set_carry_forward(1, "2026-09-01", True)
    october = service.summary_for_worker(1, "2026-10-01")
    assert october.previous_unpaid_minor == 20_000
    assert october.remaining_due_minor == 5_000


def test_carry_choice_is_independent_for_each_month():
    choices = FakeCarryRepository()
    service = WorkerPayrollService(
        FakeWorkerRepository(),
        FakeWorkService(),
        FakePaymentService(),
        choices,
    )
    service.set_carry_forward(1, "2026-08-01", False)
    assert service.carry_forward_for_worker(1, "2026-08-01") is False
    assert service.carry_forward_for_worker(1, "2026-09-01") is True


def test_formula_never_creates_negative_due():
    remaining, status = WorkerPayrollService.calculate_values(
        previous_unpaid_minor=0,
        earnings_minor=10_000,
        advances_minor=20_000,
        payments_minor=5_000,
    )
    assert remaining == 0
    assert status == "Paid"
