"""Read-only reporting queries over active transaction records."""
from __future__ import annotations

from dataclasses import dataclass

from chitlog.data.database import Database


@dataclass(frozen=True)
class ReportMonthlyTotalsRow:
    income_minor: int
    expense_minor: int
    transaction_count: int


@dataclass(frozen=True)
class ReportCategoryRow:
    category_name: str
    amount_minor: int


@dataclass(frozen=True)
class ReportTrendRow:
    month_key: str
    income_minor: int
    expense_minor: int


class ReportRepository:
    """Parameterized read-only queries used by the Reports module."""

    def __init__(self, database: Database):
        self.database = database

    def monthly_totals(self, start_date: str, end_date: str) -> ReportMonthlyTotalsRow:
        row = self.database.connection.execute(
            "SELECT "
            "COALESCE(SUM(CASE WHEN transaction_type='income' THEN amount_minor ELSE 0 END),0),"
            "COALESCE(SUM(CASE WHEN transaction_type='expense' THEN amount_minor ELSE 0 END),0),"
            "COUNT(*) "
            "FROM transactions "
            "WHERE is_deleted=0 AND transaction_date>=? AND transaction_date<=?",
            (start_date, end_date),
        ).fetchone()
        return ReportMonthlyTotalsRow(int(row[0]), int(row[1]), int(row[2]))

    def expense_categories(self, start_date: str, end_date: str) -> list[ReportCategoryRow]:
        rows = self.database.connection.execute(
            "SELECT c.name,COALESCE(SUM(t.amount_minor),0) "
            "FROM transactions t "
            "JOIN categories c ON c.id=t.category_id "
            "WHERE t.is_deleted=0 AND t.transaction_type='expense' "
            "AND t.transaction_date>=? AND t.transaction_date<=? "
            "GROUP BY c.id,c.name "
            "HAVING SUM(t.amount_minor)>0 "
            "ORDER BY SUM(t.amount_minor) DESC,c.name COLLATE NOCASE",
            (start_date, end_date),
        ).fetchall()
        return [ReportCategoryRow(str(row[0]), int(row[1])) for row in rows]

    def monthly_trend(self, start_date: str, end_date: str) -> list[ReportTrendRow]:
        rows = self.database.connection.execute(
            "SELECT substr(transaction_date,1,7),"
            "COALESCE(SUM(CASE WHEN transaction_type='income' THEN amount_minor ELSE 0 END),0),"
            "COALESCE(SUM(CASE WHEN transaction_type='expense' THEN amount_minor ELSE 0 END),0) "
            "FROM transactions "
            "WHERE is_deleted=0 AND transaction_date>=? AND transaction_date<=? "
            "GROUP BY substr(transaction_date,1,7) "
            "ORDER BY substr(transaction_date,1,7)",
            (start_date, end_date),
        ).fetchall()
        return [
            ReportTrendRow(str(row[0]), int(row[1]), int(row[2]))
            for row in rows
        ]
