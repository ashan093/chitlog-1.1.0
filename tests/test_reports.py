"""Step 16 report totals are verified against real database records."""
import secrets

from chitlog.data.database import Database
from chitlog.data.report_repository import ReportRepository
from chitlog.data.transaction_repository import TransactionRepository
from chitlog.services.report_service import ReportService


def test_monthly_report_matches_active_database_records(tmp_path):
    db = Database(
        tmp_path / "test.db",
        secrets.token_bytes(32),
        tmp_path / "snapshots",
    ).open()
    try:
        transactions = TransactionRepository(db)
        income_category = transactions.add_category("income", "Report Test Sales")
        food = transactions.add_category("expense", "Report Test Food")
        bills = transactions.add_category("expense", "Report Test Bills")

        transactions.create_transaction(
            transaction_type="income",
            transaction_date="2026-09-01",
            amount_minor=100_000,
            category_id=income_category,
            description="",
            payment_method="Cash",
        )
        transactions.create_transaction(
            transaction_type="income",
            transaction_date="2026-09-30",
            amount_minor=50_000,
            category_id=income_category,
            description="",
            payment_method="Cash",
        )
        transactions.create_transaction(
            transaction_type="expense",
            transaction_date="2026-09-10",
            amount_minor=25_000,
            category_id=food,
            description="",
            payment_method="Cash",
        )
        transactions.create_transaction(
            transaction_type="expense",
            transaction_date="2026-09-20",
            amount_minor=15_000,
            category_id=bills,
            description="",
            payment_method="Cash",
        )
        deleted_id = transactions.create_transaction(
            transaction_type="expense",
            transaction_date="2026-09-25",
            amount_minor=99_000,
            category_id=food,
            description="deleted",
            payment_method="Cash",
        )
        transactions.soft_delete(deleted_id)

        # Neighboring-month record must not leak into September.
        transactions.create_transaction(
            transaction_type="expense",
            transaction_date="2026-08-31",
            amount_minor=10_000,
            category_id=food,
            description="",
            payment_method="Cash",
        )

        service = ReportService(ReportRepository(db))
        report = service.monthly_report("2026-09-17")

        assert report.month_start == "2026-09-01"
        assert report.month_end == "2026-09-30"
        assert report.income_minor == 150_000
        assert report.expense_minor == 40_000
        assert report.net_minor == 110_000
        assert report.transaction_count == 4

        categories = service.expense_categories("2026-09-01")
        assert [(item.category_name, item.amount_minor) for item in categories] == [
            ("Report Test Food", 25_000),
            ("Report Test Bills", 15_000),
        ]
    finally:
        db.close()


def test_six_month_trend_fills_empty_months_and_respects_boundaries(tmp_path):
    db = Database(
        tmp_path / "test.db",
        secrets.token_bytes(32),
        tmp_path / "snapshots",
    ).open()
    try:
        transactions = TransactionRepository(db)
        income = transactions.add_category("income", "Report Trend Income")
        expense = transactions.add_category("expense", "Report Trend Expense")
        transactions.create_transaction(
            transaction_type="expense",
            transaction_date="2026-08-05",
            amount_minor=10_000,
            category_id=expense,
            description="",
            payment_method=None,
        )
        transactions.create_transaction(
            transaction_type="income",
            transaction_date="2026-09-05",
            amount_minor=30_000,
            category_id=income,
            description="",
            payment_method=None,
        )

        service = ReportService(ReportRepository(db))
        trend = service.monthly_trend("2026-09-01", months=3)

        assert [item.month_start for item in trend] == [
            "2026-07-01",
            "2026-08-01",
            "2026-09-01",
        ]
        assert trend[0].income_minor == 0 and trend[0].expense_minor == 0
        assert trend[1].expense_minor == 10_000
        assert trend[2].income_minor == 30_000
        assert trend[2].net_minor == 30_000
    finally:
        db.close()
