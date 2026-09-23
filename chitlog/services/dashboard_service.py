"""Dashboard calculations built from authoritative transaction records."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from calendar import monthrange

from chitlog.data.transaction_repository import TransactionRecord, TransactionRepository


@dataclass(frozen=True)
class DashboardSummary:
    current_balance_minor: int
    month_income_minor: int
    month_expense_minor: int
    month_net_minor: int
    month_label: str


class DashboardService:
    """Read-only dashboard calculations plus non-destructive recent-item hiding."""

    def __init__(self, repository: TransactionRepository):
        self.repository = repository

    def summary(self, today: date | None = None) -> DashboardSummary:
        today = today or date.today()
        month_start = today.replace(day=1)
        month_end = today.replace(day=monthrange(today.year, today.month)[1])

        all_income, all_expense = self.repository.totals()
        month_income, month_expense = self.repository.totals_between(
            month_start.isoformat(),
            month_end.isoformat(),
        )

        return DashboardSummary(
            current_balance_minor=all_income - all_expense,
            month_income_minor=month_income,
            month_expense_minor=month_expense,
            month_net_minor=month_income - month_expense,
            month_label=today.strftime("%B %Y"),
        )

    def recent_activity(self, limit: int = 8) -> list[TransactionRecord]:
        limit = max(1, min(int(limit), 20))
        return self.repository.list_recent_activity(limit=limit)

    def hide_from_recent(self, transaction_id: int) -> bool:
        """Hide only from Dashboard Recent Activity; never delete the transaction."""
        return self.repository.dismiss_recent(transaction_id)

    def restore_to_recent(self, transaction_id: int) -> bool:
        """Undo Hide from Recent; the underlying transaction is unchanged."""
        return self.repository.restore_recent(transaction_id)
