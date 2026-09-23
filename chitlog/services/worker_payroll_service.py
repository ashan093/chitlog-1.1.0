"""Centralized Step 14 worker payroll/balance calculations.

The UI must not reimplement these formulas.  A month's remaining due is:

    previous unpaid balance
  + current-period earnings
  - advances
  - other payments already made
  = remaining due

A positive month-end due carries forward only when that worker/month is set to
carry it forward. Excess money given never creates a negative amount due.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from calendar import monthrange

from chitlog.services.worker_payment_service import WorkerPaymentService
from chitlog.services.worker_work_service import WorkerWorkService


@dataclass(frozen=True)
class WorkerPayrollSummary:
    worker_id: int
    month_start: str
    month_end: str
    previous_unpaid_minor: int
    earnings_minor: int
    advances_minor: int
    payments_minor: int
    remaining_due_minor: int
    status: str

    @property
    def money_given_minor(self) -> int:
        return self.advances_minor + self.payments_minor


class WorkerPayrollService:
    """One source of truth for monthly worker payroll balances."""

    def __init__(
        self,
        worker_repository,
        work_service: WorkerWorkService,
        payment_service: WorkerPaymentService,
        payroll_repository=None,
    ):
        self.worker_repository = worker_repository
        self.work_service = work_service
        self.payment_service = payment_service
        self.payroll_repository = payroll_repository

    @staticmethod
    def _month_start(value: str | date) -> date:
        if isinstance(value, date):
            parsed = value
        else:
            try:
                parsed = date.fromisoformat((value or "").strip())
            except ValueError:
                raise ValueError("Enter a valid payroll month.") from None
        return parsed.replace(day=1)

    @staticmethod
    def _bounds(month_start: date) -> tuple[str, str]:
        end = month_start.replace(day=monthrange(month_start.year, month_start.month)[1])
        return month_start.isoformat(), end.isoformat()

    @staticmethod
    def _next_month(value: date) -> date:
        if value.month == 12:
            return date(value.year + 1, 1, 1)
        return date(value.year, value.month + 1, 1)

    @staticmethod
    def calculate_values(
        *,
        previous_unpaid_minor: int,
        earnings_minor: int,
        advances_minor: int,
        payments_minor: int,
    ) -> tuple[int, str]:
        """Pure financial formula used by tests and monthly summaries."""
        previous = max(0, int(previous_unpaid_minor))
        earnings = max(0, int(earnings_minor))
        advances = max(0, int(advances_minor))
        payments = max(0, int(payments_minor))

        obligation = previous + earnings
        money_given = advances + payments
        remaining = max(0, obligation - money_given)

        if remaining == 0:
            status = "Paid"
        elif money_given > 0:
            status = "Partially Paid"
        else:
            status = "Due"
        return remaining, status

    def carry_forward_for_worker(self, worker_id: int, month: str | date) -> bool:
        """Return the saved month-end carry choice.

        Older databases/isolated tests without the repository preserve the original
        Step 14 behavior and therefore default to carrying a positive due forward.
        """
        if self.payroll_repository is None:
            return True
        return self.payroll_repository.carry_forward_for(worker_id, month)

    def set_carry_forward(
        self, worker_id: int, month: str | date, carry_forward: bool
    ) -> None:
        if self.payroll_repository is None:
            return
        self.payroll_repository.set_carry_forward(
            worker_id, month, carry_forward
        )

    def summary_for_worker(
        self, worker_id: int, month: str | date
    ) -> WorkerPayrollSummary:
        worker = self.worker_repository.get_worker(worker_id)
        selected = self._month_start(month)
        start_text, end_text = self._bounds(selected)

        if worker is None:
            return WorkerPayrollSummary(
                worker_id, start_text, end_text, 0, 0, 0, 0, 0, "Paid"
            )

        joined = date.fromisoformat(worker.date_added).replace(day=1)
        previous_due = 0

        # A month before the worker joined has no obligation.
        if selected < joined:
            return WorkerPayrollSummary(
                worker_id, start_text, end_text, 0, 0, 0, 0, 0, "Paid"
            )

        cursor = joined
        while cursor < selected:
            cursor_start, cursor_end = self._bounds(cursor)
            work = self.work_service.month_summary(worker_id, cursor_start, cursor_end)
            paid = self.payment_service.month_totals(worker_id, cursor_start, cursor_end)
            month_remaining, _ = self.calculate_values(
                previous_unpaid_minor=previous_due,
                earnings_minor=work.amount_to_pay_minor,
                advances_minor=paid.advances_minor,
                payments_minor=paid.regular_payments_minor,
            )
            # The user decides independently for every worker and every month
            # whether that month's positive due becomes the next month's
            # previous balance.
            previous_due = (
                month_remaining
                if self.carry_forward_for_worker(worker_id, cursor)
                else 0
            )
            cursor = self._next_month(cursor)

        work = self.work_service.month_summary(worker_id, start_text, end_text)
        paid = self.payment_service.month_totals(worker_id, start_text, end_text)
        remaining, status = self.calculate_values(
            previous_unpaid_minor=previous_due,
            earnings_minor=work.amount_to_pay_minor,
            advances_minor=paid.advances_minor,
            payments_minor=paid.regular_payments_minor,
        )
        return WorkerPayrollSummary(
            worker_id=worker_id,
            month_start=start_text,
            month_end=end_text,
            previous_unpaid_minor=previous_due,
            earnings_minor=work.amount_to_pay_minor,
            advances_minor=paid.advances_minor,
            payments_minor=paid.regular_payments_minor,
            remaining_due_minor=remaining,
            status=status,
        )
