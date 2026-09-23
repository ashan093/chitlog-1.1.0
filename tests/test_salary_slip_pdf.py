"""Step 15 salary-slip PDF generation tests."""
import secrets
from pathlib import Path

from PySide6.QtWidgets import QApplication

from chitlog.data.database import Database
from chitlog.data.worker_repository import WorkerRepository
from chitlog.data.worker_work_repository import WorkerWorkRepository
from chitlog.data.worker_payment_repository import WorkerPaymentRepository
from chitlog.data.worker_payroll_repository import WorkerPayrollRepository
from chitlog.services.worker_service import WorkerInput, WorkerService
from chitlog.services.worker_work_service import WorkerAttendanceInput, WorkerWorkService
from chitlog.services.worker_payment_service import WorkerPaymentInput, WorkerPaymentService
from chitlog.services.worker_payroll_service import WorkerPayrollService
from chitlog.services.salary_slip_service import SalarySlipPdfService


def test_generate_selected_worker_salary_slips(tmp_path):
    app = QApplication.instance() or QApplication([])
    db = Database(
        tmp_path / "test.db", secrets.token_bytes(32), tmp_path / "snapshots"
    ).open()
    try:
        repo = WorkerRepository(db)
        workers = WorkerService(repo, "LKR")
        work = WorkerWorkService(WorkerWorkRepository(db), repo, "LKR")
        payments = WorkerPaymentService(WorkerPaymentRepository(db), repo, "LKR")
        payroll = WorkerPayrollService(
            repo, work, payments, WorkerPayrollRepository(db)
        )

        first = workers.create_worker(
            WorkerInput(
                "Kamal",
                "permanent",
                phone="0712345678",
                payment_method="daily",
                normal_rate="2500",
                date_added="2026-09-01",
            )
        )
        second = workers.create_worker(
            WorkerInput(
                "Nimal",
                "temporary",
                payment_method="monthly",
                normal_rate="50000",
                date_added="2026-09-01",
            )
        )
        work.create_attendance(
            first, WorkerAttendanceInput("2026-09-05", "", "site work")
        )
        work.create_attendance(
            first,
            WorkerAttendanceInput("2026-09-08", "", "half shift", "half_day", ""),
        )
        work.create_attendance(
            first,
            WorkerAttendanceInput("2026-09-09", "1000", "short shift", "hours", "3.5"),
        )
        payments.create(
            first, WorkerPaymentInput("2026-09-05", "1000", "partial", "partial")
        )

        output = tmp_path / "salary-slips.pdf"
        pdf = SalarySlipPdfService(
            workers, payroll, "LKR", "Rs", logo_path=None
        )
        worked_days = pdf._worked_days(first, pdf._month_start("2026-09-01"))
        assert [record.work_date for record in worked_days] == [
            "2026-09-05",
            "2026-09-08",
            "2026-09-09",
        ]
        assert worked_days[0].duration_type == "full_day"
        assert worked_days[0].amount_minor == 250000
        assert worked_days[1].duration_type == "half_day"
        assert worked_days[1].amount_minor == 125000
        assert worked_days[2].duration_type == "hours"
        assert worked_days[2].hours_minutes == 210
        assert worked_days[2].amount_minor == 100000

        count = pdf.generate(output, [first, second], "2026-09-01")

        assert count == 2
        assert output.exists()
        assert output.stat().st_size > 1000
        assert output.read_bytes()[:4] == b"%PDF"
    finally:
        db.close()
