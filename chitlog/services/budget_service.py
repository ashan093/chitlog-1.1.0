"""Exact monthly budget calculations and idempotent carry-forward logic."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from chitlog.core.money import MoneyError, parse_amount_to_minor
from chitlog.data.budget_repository import BudgetRepository, ExpenseCategoryOption


class BudgetError(ValueError):
    """Safe validation/business-rule error for budgeting."""


@dataclass(frozen=True)
class CategoryBudgetStatus:
    category_id: int
    category_name: str
    budget_minor: int
    spent_minor: int
    remaining_minor: int
    used_percent: int
    category_active: bool


@dataclass(frozen=True)
class BudgetMonthStatus:
    month: str
    base_budget_minor: int
    carry_in_minor: int
    effective_budget_minor: int
    spent_minor: int
    remaining_minor: int
    used_percent: int
    carry_forward_enabled: bool
    category_budgets: tuple[CategoryBudgetStatus, ...]


class BudgetService:
    def __init__(self, repository: BudgetRepository, currency_code: str):
        self.repository = repository
        self.currency_code = (currency_code or "LKR").upper()

    @staticmethod
    def _validate_month(month: str) -> str:
        value = (month or "").strip()
        try:
            parsed = date.fromisoformat(value + "-01")
        except (TypeError, ValueError):
            raise BudgetError("Choose a valid budget month.") from None
        return f"{parsed.year:04d}-{parsed.month:02d}"

    @staticmethod
    def previous_month(month: str) -> str:
        year, number = (int(part) for part in month.split("-"))
        if number == 1:
            return f"{year - 1:04d}-12"
        return f"{year:04d}-{number - 1:02d}"

    @staticmethod
    def next_month(month: str) -> str:
        year, number = (int(part) for part in month.split("-"))
        if number == 12:
            return f"{year + 1:04d}-01"
        return f"{year:04d}-{number + 1:02d}"

    @staticmethod
    def _percent(spent_minor: int, budget_minor: int) -> int:
        if budget_minor <= 0:
            return 0
        return max(0, (spent_minor * 100 + budget_minor // 2) // budget_minor)

    def _parse_amount(self, amount_text: str) -> int:
        try:
            return parse_amount_to_minor(amount_text, self.currency_code)
        except MoneyError as error:
            raise BudgetError(str(error)) from None

    def list_expense_categories(self) -> list[ExpenseCategoryOption]:
        return self.repository.list_expense_categories()

    def set_monthly_budget(self, month: str, amount_text: str, carry_enabled: bool) -> None:
        month = self._validate_month(month)
        amount_minor = self._parse_amount(amount_text)
        self.repository.upsert_monthly_budget(month, amount_minor, bool(carry_enabled))
        # Keep the immediately following derived carry record synchronized. This
        # never edits the historical base budget; it only updates derived carry-in.
        self._sync_carry_in(self.next_month(month))

    def set_category_budget(self, month: str, category_id: int, amount_text: str) -> None:
        month = self._validate_month(month)
        if not self.repository.category_is_active_expense(category_id):
            raise BudgetError("Choose an active expense category.")
        amount_minor = self._parse_amount(amount_text)
        self.repository.upsert_category_budget(month, category_id, amount_minor)

    def remove_category_budget(self, month: str, category_id: int) -> bool:
        month = self._validate_month(month)
        return self.repository.delete_category_budget(month, category_id)

    def _sync_carry_in(self, target_month: str) -> int:
        target_month = self._validate_month(target_month)
        source_month = self.previous_month(target_month)
        source = self.repository.get_monthly_budget(source_month)
        if source is None or not source.carry_forward_enabled:
            self.repository.delete_carry_in(target_month)
            return 0

        source_carry = self.repository.get_carry_in(source_month)
        source_spent = self.repository.month_expense_total(source_month)
        available = source.amount_minor + source_carry
        carry_amount = max(available - source_spent, 0)
        self.repository.upsert_carry_in(source_month, target_month, carry_amount)
        return carry_amount

    def status(self, month: str) -> BudgetMonthStatus:
        month = self._validate_month(month)
        carry_in = self._sync_carry_in(month)
        monthly = self.repository.get_monthly_budget(month)
        base_budget = monthly.amount_minor if monthly else 0
        carry_enabled = monthly.carry_forward_enabled if monthly else False
        effective = base_budget + carry_in
        spent = self.repository.month_expense_total(month)
        remaining = effective - spent

        category_spent = self.repository.category_expense_totals(month)
        category_statuses: list[CategoryBudgetStatus] = []
        for item in self.repository.list_category_budgets(month):
            item_spent = category_spent.get(item.category_id, 0)
            category_statuses.append(
                CategoryBudgetStatus(
                    category_id=item.category_id,
                    category_name=item.category_name,
                    budget_minor=item.amount_minor,
                    spent_minor=item_spent,
                    remaining_minor=item.amount_minor - item_spent,
                    used_percent=self._percent(item_spent, item.amount_minor),
                    category_active=item.category_active,
                )
            )

        return BudgetMonthStatus(
            month=month,
            base_budget_minor=base_budget,
            carry_in_minor=carry_in,
            effective_budget_minor=effective,
            spent_minor=spent,
            remaining_minor=remaining,
            used_percent=self._percent(spent, effective),
            carry_forward_enabled=carry_enabled,
            category_budgets=tuple(category_statuses),
        )
