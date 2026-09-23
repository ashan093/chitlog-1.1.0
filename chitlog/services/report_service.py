"""Centralized monthly financial report calculations."""
from __future__ import annotations

from calendar import monthrange
from dataclasses import dataclass
from datetime import date

from chitlog.data.report_repository import (
    ReportCategoryRow,
    ReportRepository,
)


class ReportError(ValueError):
    """Safe reporting validation error."""


@dataclass(frozen=True)
class MonthlyReport:
    month_start: str
    month_end: str
    income_minor: int
    expense_minor: int
    net_minor: int
    transaction_count: int


@dataclass(frozen=True)
class ExpenseCategoryReport:
    category_name: str
    amount_minor: int


@dataclass(frozen=True)
class MonthlyTrendPoint:
    month_start: str
    label: str
    income_minor: int
    expense_minor: int
    net_minor: int


class ReportService:
    """Financial reports derived only from active transaction records."""

    def __init__(self, repository: ReportRepository):
        self.repository = repository

    @staticmethod
    def _month_start(value: str | date) -> date:
        if isinstance(value, date):
            parsed = value
        else:
            try:
                parsed = date.fromisoformat((value or "").strip())
            except (TypeError, ValueError):
                raise ReportError("Choose a valid report month.") from None
        return parsed.replace(day=1)

    @staticmethod
    def _month_bounds(month_start: date) -> tuple[str, str]:
        last_day = monthrange(month_start.year, month_start.month)[1]
        return (
            month_start.isoformat(),
            month_start.replace(day=last_day).isoformat(),
        )

    @staticmethod
    def _shift_month(month_start: date, offset: int) -> date:
        month_index = month_start.year * 12 + (month_start.month - 1) + offset
        year, zero_based_month = divmod(month_index, 12)
        return date(year, zero_based_month + 1, 1)

    def monthly_report(self, month: str | date) -> MonthlyReport:
        month_start = self._month_start(month)
        start_date, end_date = self._month_bounds(month_start)
        row = self.repository.monthly_totals(start_date, end_date)
        return MonthlyReport(
            month_start=start_date,
            month_end=end_date,
            income_minor=row.income_minor,
            expense_minor=row.expense_minor,
            net_minor=row.income_minor - row.expense_minor,
            transaction_count=row.transaction_count,
        )

    def expense_categories(self, month: str | date) -> list[ExpenseCategoryReport]:
        month_start = self._month_start(month)
        start_date, end_date = self._month_bounds(month_start)
        return [
            ExpenseCategoryReport(row.category_name, row.amount_minor)
            for row in self.repository.expense_categories(start_date, end_date)
        ]

    def monthly_trend(
        self, month: str | date, *, months: int = 6
    ) -> list[MonthlyTrendPoint]:
        month_start = self._month_start(month)
        months = max(1, min(int(months), 12))
        first_month = self._shift_month(month_start, -(months - 1))
        start_date, _ = self._month_bounds(first_month)
        _, end_date = self._month_bounds(month_start)

        rows = {
            row.month_key: row
            for row in self.repository.monthly_trend(start_date, end_date)
        }

        result: list[MonthlyTrendPoint] = []
        for offset in range(months):
            current = self._shift_month(first_month, offset)
            key = current.strftime("%Y-%m")
            row = rows.get(key)
            income = row.income_minor if row else 0
            expense = row.expense_minor if row else 0
            result.append(
                MonthlyTrendPoint(
                    month_start=current.isoformat(),
                    label=current.strftime("%b"),
                    income_minor=income,
                    expense_minor=expense,
                    net_minor=income - expense,
                )
            )
        return result
