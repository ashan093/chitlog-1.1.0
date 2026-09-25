"""Parameterized SQLite access for monthly and category budgets."""
from __future__ import annotations

from dataclasses import dataclass

from chitlog.data.database import Database


@dataclass(frozen=True)
class MonthlyBudgetRecord:
    month: str
    amount_minor: int
    carry_forward_enabled: bool


@dataclass(frozen=True)
class CategoryBudgetRecord:
    category_id: int
    category_name: str
    amount_minor: int
    category_active: bool


@dataclass(frozen=True)
class ExpenseCategoryOption:
    id: int
    name: str


class BudgetRepository:
    def __init__(self, database: Database):
        self.database = database

    def get_monthly_budget(self, month: str) -> MonthlyBudgetRecord | None:
        row = self.database.connection.execute(
            "SELECT budget_month,amount_minor,carry_forward_enabled "
            "FROM budgets WHERE budget_month=? AND category_id IS NULL",
            (month,),
        ).fetchone()
        if row is None:
            return None
        return MonthlyBudgetRecord(row[0], int(row[1]), bool(row[2]))

    def upsert_monthly_budget(self, month: str, amount_minor: int, carry_enabled: bool) -> None:
        with self.database.transaction() as connection:
            row = connection.execute(
                "SELECT id FROM budgets WHERE budget_month=? AND category_id IS NULL",
                (month,),
            ).fetchone()
            if row is None:
                connection.execute(
                    "INSERT INTO budgets(budget_month,category_id,amount_minor,carry_forward_enabled) "
                    "VALUES (?,NULL,?,?)",
                    (month, amount_minor, int(carry_enabled)),
                )
            else:
                connection.execute(
                    "UPDATE budgets SET amount_minor=?,carry_forward_enabled=?,"
                    "updated_at=CURRENT_TIMESTAMP WHERE id=?",
                    (amount_minor, int(carry_enabled), row[0]),
                )

    def list_expense_categories(self) -> list[ExpenseCategoryOption]:
        rows = self.database.connection.execute(
            "SELECT id,name FROM categories WHERE kind='expense' AND is_active=1 "
            "ORDER BY CASE WHEN lower(name)='other' THEN 1 ELSE 0 END, name COLLATE NOCASE"
        ).fetchall()
        return [ExpenseCategoryOption(int(row[0]), row[1]) for row in rows]

    def category_is_active_expense(self, category_id: int) -> bool:
        row = self.database.connection.execute(
            "SELECT 1 FROM categories WHERE id=? AND kind='expense' AND is_active=1",
            (category_id,),
        ).fetchone()
        return row is not None

    def list_category_budgets(self, month: str) -> list[CategoryBudgetRecord]:
        rows = self.database.connection.execute(
            "SELECT b.category_id,c.name,b.amount_minor,c.is_active "
            "FROM budgets b JOIN categories c ON c.id=b.category_id "
            "WHERE b.budget_month=? AND b.category_id IS NOT NULL "
            "ORDER BY CASE WHEN lower(c.name)='other' THEN 1 ELSE 0 END, c.name COLLATE NOCASE",
            (month,),
        ).fetchall()
        return [
            CategoryBudgetRecord(int(row[0]), row[1], int(row[2]), bool(row[3]))
            for row in rows
        ]

    def upsert_category_budget(self, month: str, category_id: int, amount_minor: int) -> None:
        with self.database.transaction() as connection:
            row = connection.execute(
                "SELECT id FROM budgets WHERE budget_month=? AND category_id=?",
                (month, category_id),
            ).fetchone()
            if row is None:
                connection.execute(
                    "INSERT INTO budgets(budget_month,category_id,amount_minor,carry_forward_enabled) "
                    "VALUES (?,?,?,0)",
                    (month, category_id, amount_minor),
                )
            else:
                connection.execute(
                    "UPDATE budgets SET amount_minor=?,updated_at=CURRENT_TIMESTAMP WHERE id=?",
                    (amount_minor, row[0]),
                )

    def delete_category_budget(self, month: str, category_id: int) -> bool:
        with self.database.transaction() as connection:
            cursor = connection.execute(
                "DELETE FROM budgets WHERE budget_month=? AND category_id=?",
                (month, category_id),
            )
            return cursor.rowcount == 1

    def month_expense_total(self, month: str) -> int:
        start = month + "-01"
        # Lexicographic ISO date comparison safely covers the selected month.
        if month.endswith("-12"):
            next_month = f"{int(month[:4]) + 1:04d}-01-01"
        else:
            next_month = f"{month[:5]}{int(month[5:7]) + 1:02d}-01"
        row = self.database.connection.execute(
            "SELECT COALESCE(SUM(amount_minor),0) FROM transactions "
            "WHERE is_deleted=0 AND transaction_type='expense' "
            "AND transaction_date>=? AND transaction_date<?",
            (start, next_month),
        ).fetchone()
        return int(row[0])

    def category_expense_totals(self, month: str) -> dict[int, int]:
        start = month + "-01"
        if month.endswith("-12"):
            next_month = f"{int(month[:4]) + 1:04d}-01-01"
        else:
            next_month = f"{month[:5]}{int(month[5:7]) + 1:02d}-01"
        rows = self.database.connection.execute(
            "SELECT category_id,COALESCE(SUM(amount_minor),0) FROM transactions "
            "WHERE is_deleted=0 AND transaction_type='expense' "
            "AND transaction_date>=? AND transaction_date<? GROUP BY category_id",
            (start, next_month),
        ).fetchall()
        return {int(row[0]): int(row[1]) for row in rows}

    def get_carry_in(self, target_month: str) -> int:
        row = self.database.connection.execute(
            "SELECT amount_minor FROM budget_carry_forward WHERE target_month=?",
            (target_month,),
        ).fetchone()
        return int(row[0]) if row else 0

    def upsert_carry_in(self, source_month: str, target_month: str, amount_minor: int) -> None:
        with self.database.transaction() as connection:
            connection.execute(
                "INSERT INTO budget_carry_forward(source_month,target_month,amount_minor) "
                "VALUES (?,?,?) "
                "ON CONFLICT(target_month) DO UPDATE SET "
                "source_month=excluded.source_month,amount_minor=excluded.amount_minor,"
                "updated_at=CURRENT_TIMESTAMP",
                (source_month, target_month, amount_minor),
            )

    def delete_carry_in(self, target_month: str) -> None:
        with self.database.transaction() as connection:
            connection.execute(
                "DELETE FROM budget_carry_forward WHERE target_month=?",
                (target_month,),
            )
