"""Worker profile business logic tests."""
import secrets

import pytest

from chitlog.data.database import Database
from chitlog.data.worker_repository import WorkerRepository
from chitlog.services.worker_service import WorkerError, WorkerInput, WorkerService


@pytest.fixture
def service(tmp_path):
    db = Database(tmp_path / "workers.db", secrets.token_bytes(32), tmp_path / "snapshots").open()
    svc = WorkerService(WorkerRepository(db), "LKR")
    yield svc
    db.close()


def test_permanent_and_temporary_profiles_persist_and_filter(service):
    permanent = service.create_worker(
        WorkerInput("Kamal", "permanent", "0711111111", "Town", "", "monthly", "50000.00", "2026-09-01")
    )
    temporary = service.create_worker(
        WorkerInput("Nimal", "temporary", "0722222222", "", "returns seasonally", "daily", "2500.00", "2026-09-02")
    )
    active = service.list_workers(status="active")
    assert {item.id for item in active} == {permanent, temporary}
    assert [item.id for item in service.list_workers(worker_type="temporary")] == [temporary]
    assert service.get_worker(permanent).normal_rate_minor == 5_000_000
    counts = service.counts()
    assert counts.total == 2 and counts.active == 2 and counts.inactive == 0 and counts.temporary == 1


def test_deactivate_and_reactivate_keeps_temporary_worker(service):
    worker_id = service.create_worker(
        WorkerInput("Return Worker", "temporary", payment_method="daily", normal_rate="1200", date_added="2026-09-03")
    )
    service.deactivate_worker(worker_id)
    assert service.get_worker(worker_id).is_active is False
    assert service.list_workers(status="active") == []
    assert [item.id for item in service.list_workers(status="inactive")] == [worker_id]
    service.reactivate_worker(worker_id)
    assert service.get_worker(worker_id).is_active is True


def test_worker_update_and_search(service):
    worker_id = service.create_worker(
        WorkerInput("Old Name", "temporary", "0770000000", payment_method="job", date_added="2026-09-04")
    )
    service.update_worker(
        worker_id,
        WorkerInput("New Name", "permanent", "0770000000", "Address", "note", "period", "3000.00", "2026-09-04"),
    )
    item = service.get_worker(worker_id)
    assert item.name == "New Name"
    assert item.worker_type == "permanent"
    assert item.payment_method == "period"
    assert item.normal_rate_minor == 300000
    assert [worker.id for worker in service.list_workers(search="New")] == [worker_id]
    assert [worker.id for worker in service.list_workers(search="0770")] == [worker_id]


def test_worker_text_is_data_and_optional_rate_can_be_blank_for_job_worker(service):
    text = "'); DROP TABLE workers; -- <script>alert(1)</script>"
    worker_id = service.create_worker(
        WorkerInput(text, "temporary", notes=text, payment_method="job", normal_rate="", date_added="2026-09-05")
    )
    item = service.get_worker(worker_id)
    assert item.name == text
    assert item.notes == text
    assert item.normal_rate_minor is None
    assert len(service.list_workers(status="all")) == 1


def test_daily_and_monthly_workers_require_a_saved_rate(service):
    with pytest.raises(WorkerError, match="daily rate"):
        service.create_worker(
            WorkerInput("Daily", "temporary", payment_method="daily", normal_rate="", date_added="2026-09-05")
        )
    with pytest.raises(WorkerError, match="monthly salary"):
        service.create_worker(
            WorkerInput("Monthly", "permanent", payment_method="monthly", normal_rate="", date_added="2026-09-05")
        )


@pytest.mark.parametrize(
    "item",
    [
        WorkerInput("", "permanent", payment_method="daily", normal_rate="100", date_added="2026-09-01"),
        WorkerInput("Name", "unknown", payment_method="daily", normal_rate="100", date_added="2026-09-01"),
        WorkerInput("Name", "permanent", payment_method="unknown", normal_rate="100", date_added="2026-09-01"),
        WorkerInput("Name", "permanent", payment_method="daily", normal_rate="0", date_added="2026-09-01"),
        WorkerInput("Name", "permanent", payment_method="daily", normal_rate="abc", date_added="2026-09-01"),
        WorkerInput("Name", "permanent", payment_method="daily", normal_rate="100", date_added="bad-date"),
        WorkerInput("Name", "permanent", payment_method="daily", normal_rate="100", date_added="2099-01-01"),
    ],
)
def test_invalid_worker_inputs_are_rejected(service, item):
    with pytest.raises(WorkerError):
        service.create_worker(item)


def test_permanent_delete_removes_worker_even_when_inactive(service):
    worker_id = service.create_worker(
        WorkerInput("Remove Me", "temporary", payment_method="daily", normal_rate="1200", date_added="2026-09-06")
    )
    service.deactivate_worker(worker_id)
    assert service.get_worker(worker_id) is not None
    service.delete_worker_permanently(worker_id)
    assert service.get_worker(worker_id) is None
    counts = service.counts()
    assert counts.total == 0 and counts.active == 0 and counts.inactive == 0


def test_permanent_delete_is_blocked_when_worker_has_history(service):
    worker_id = service.create_worker(
        WorkerInput("Has History", "permanent", payment_method="monthly", normal_rate="50000", date_added="2026-09-07")
    )
    database = service.repository.database
    with database.transaction() as connection:
        connection.execute(
            "INSERT INTO worker_work_records("
            "worker_id,earning_type,start_date,end_date,amount_minor,description"
            ") VALUES (?,?,?,?,?,?)",
            (worker_id, "monthly", "2026-09-01", "2026-09-30", 100000, "history"),
        )
    with pytest.raises(WorkerError, match="cannot be permanently deleted"):
        service.delete_worker_permanently(worker_id)
    assert service.get_worker(worker_id) is not None


def test_permanent_delete_allows_worker_when_only_soft_deleted_work_history_remains(service):
    worker_id = service.create_worker(
        WorkerInput(
            "Deleted History",
            "temporary",
            payment_method="job",
            date_added="2026-09-01",
        )
    )
    database = service.repository.database
    with database.transaction() as connection:
        cursor = connection.execute(
            "INSERT INTO worker_work_records("
            "worker_id,earning_type,start_date,end_date,amount_minor,description"
            ") VALUES (?,?,?,?,?,?)",
            (worker_id, "job", "2026-09-10", "2026-09-10", 100000, "old work"),
        )
        record_id = int(cursor.lastrowid)
        connection.execute(
            "UPDATE worker_work_records SET is_deleted=1,deleted_at=CURRENT_TIMESTAMP "
            "WHERE id=?",
            (record_id,),
        )

    assert service.permanent_delete_status(worker_id) == "deletable"
    service.delete_worker_permanently(worker_id)
    assert service.get_worker(worker_id) is None
    assert database.connection.execute(
        "SELECT COUNT(*) FROM worker_work_records WHERE id=?", (record_id,)
    ).fetchone()[0] == 0
    assert database.connection.execute("PRAGMA foreign_key_check").fetchall() == []
