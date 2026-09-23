"""Real-database checks for per-worker/month carry-forward choices."""
import secrets

from chitlog.data.database import Database
from chitlog.data.worker_payroll_repository import WorkerPayrollRepository
from chitlog.data.worker_repository import WorkerRepository
from chitlog.services.worker_service import WorkerInput, WorkerService


def test_carry_choice_defaults_true_and_persists_by_worker_and_month(tmp_path):
    db = Database(
        tmp_path / "test.db", secrets.token_bytes(32), tmp_path / "snapshots"
    ).open()
    try:
        worker_repo = WorkerRepository(db)
        workers = WorkerService(worker_repo, "LKR")
        worker_id = workers.create_worker(
            WorkerInput(
                "Kamal",
                "permanent",
                payment_method="daily",
                normal_rate="2500",
                date_added="2026-08-01",
            )
        )
        repo = WorkerPayrollRepository(db)

        assert repo.carry_forward_for(worker_id, "2026-08-01") is True
        repo.set_carry_forward(worker_id, "2026-08-01", False)
        assert repo.carry_forward_for(worker_id, "2026-08-15") is False
        assert repo.carry_forward_for(worker_id, "2026-09-01") is True

        repo.set_carry_forward(worker_id, "2026-08-01", True)
        assert repo.carry_forward_for(worker_id, "2026-08-01") is True
    finally:
        db.close()
