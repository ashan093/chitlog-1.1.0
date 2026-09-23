"""Liability business-logic tests use encrypted disposable databases only."""
import secrets

import pytest

from chitlog.data.database import Database
from chitlog.data.liability_repository import LiabilityRepository
from chitlog.services.liability_service import (
    LiabilityError,
    LiabilityInput,
    LiabilityPaymentInput,
    LiabilityService,
)


@pytest.fixture
def service(tmp_path):
    db = Database(tmp_path / "test.db", secrets.token_bytes(32), tmp_path / "snapshots").open()
    instance = LiabilityService(LiabilityRepository(db), "LKR")
    yield instance
    db.close()


def make_liability(service, amount="100000.00"):
    return service.create_liability(
        LiabilityInput(
            name="Vehicle loan",
            lender="Local lender",
            original_amount=amount,
            start_date="2026-09-01",
            due_date="2027-09-01",
            notes="simple loan",
        )
    )


def test_create_and_payment_balance(service):
    liability_id = make_liability(service)
    summary = service.get_summary(liability_id)
    assert summary.original_amount_minor == 10_000_000
    assert summary.paid_minor == 0
    assert summary.remaining_minor == 10_000_000
    assert summary.status == "Open"

    service.add_payment(
        liability_id,
        LiabilityPaymentInput("2026-09-16", "25000.00", "first payment"),
    )
    summary = service.get_summary(liability_id)
    assert summary.paid_minor == 2_500_000
    assert summary.remaining_minor == 7_500_000
    assert summary.status == "Open"

    service.add_payment(
        liability_id,
        LiabilityPaymentInput("2026-10-16", "75000.00", "final payment"),
    )
    summary = service.get_summary(liability_id)
    assert summary.remaining_minor == 0
    assert summary.status == "Paid"


def test_payment_cannot_overpay_or_continue_after_paid(service):
    liability_id = make_liability(service, "100.00")
    with pytest.raises(LiabilityError, match="greater than the remaining"):
        service.add_payment(liability_id, LiabilityPaymentInput("2026-09-16", "100.01"))
    service.add_payment(liability_id, LiabilityPaymentInput("2026-09-16", "100.00"))
    with pytest.raises(LiabilityError, match="already fully paid"):
        service.add_payment(liability_id, LiabilityPaymentInput("2026-09-17", "1.00"))


def test_edit_cannot_reduce_original_below_paid(service):
    liability_id = make_liability(service, "500.00")
    service.add_payment(liability_id, LiabilityPaymentInput("2026-09-16", "300.00"))
    with pytest.raises(LiabilityError, match="lower than payments"):
        service.update_liability(
            liability_id,
            LiabilityInput(
                name="Vehicle loan",
                lender="Local lender",
                original_amount="299.99",
                start_date="2026-09-01",
            ),
        )
    service.update_liability(
        liability_id,
        LiabilityInput(
            name="Updated loan",
            lender="Updated lender",
            original_amount="600.00",
            start_date="2026-09-01",
        ),
    )
    summary = service.get_summary(liability_id)
    assert summary.name == "Updated loan"
    assert summary.original_amount_minor == 60_000
    assert summary.remaining_minor == 30_000


def test_dates_amounts_and_input_are_validated(service):
    with pytest.raises(LiabilityError, match="Due date cannot"):
        service.create_liability(
            LiabilityInput("Loan", "", "100.00", "2026-09-10", "2026-09-01")
        )
    with pytest.raises(LiabilityError):
        service.create_liability(LiabilityInput("Loan", "", "abc", "2026-09-10"))
    with pytest.raises(LiabilityError):
        service.create_liability(LiabilityInput("", "", "100.00", "2026-09-10"))

    marker = "'); DROP TABLE liabilities; -- <script>safe</script>"
    liability_id = service.create_liability(
        LiabilityInput(marker, marker, "10.00", "2026-09-10", notes=marker)
    )
    summary = service.get_summary(liability_id)
    assert summary.name == marker
    assert summary.lender == marker
    assert summary.notes == marker


def test_totals_and_filters(service):
    first = make_liability(service, "100.00")
    second = service.create_liability(
        LiabilityInput("Small debt", "Friend", "50.00", "2026-09-01")
    )
    service.add_payment(first, LiabilityPaymentInput("2026-09-10", "100.00"))
    service.add_payment(second, LiabilityPaymentInput("2026-09-10", "20.00"))

    assert [item.id for item in service.list_liabilities("paid")] == [first]
    assert [item.id for item in service.list_liabilities("open")] == [second]
    totals = service.totals()
    assert totals.original_minor == 15_000
    assert totals.paid_minor == 12_000
    assert totals.outstanding_minor == 3_000
    assert totals.open_count == 1


def test_payment_date_cannot_precede_liability_start(service):
    liability_id = service.create_liability(
        LiabilityInput("July loan", "Bank", "1000.00", "2026-07-01")
    )
    with pytest.raises(LiabilityError, match="before the liability start date"):
        service.add_payment(
            liability_id,
            LiabilityPaymentInput("2026-06-01", "100.00", "too early"),
        )
    assert service.list_payments(liability_id) == []


def test_edit_start_date_cannot_move_after_existing_payment(service):
    liability_id = service.create_liability(
        LiabilityInput("Loan", "Bank", "1000.00", "2026-07-01")
    )
    service.add_payment(
        liability_id,
        LiabilityPaymentInput("2026-07-15", "100.00", "first"),
    )
    with pytest.raises(LiabilityError, match="after a payment already recorded"):
        service.update_liability(
            liability_id,
            LiabilityInput("Loan", "Bank", "1000.00", "2026-08-01"),
        )
    assert service.get_summary(liability_id).start_date == "2026-07-01"


def test_delete_liability_is_soft_and_excluded_from_totals(service):
    liability_id = make_liability(service, "1000.00")
    service.add_payment(
        liability_id,
        LiabilityPaymentInput("2026-09-16", "250.00", "keep history"),
    )
    assert service.totals().open_count == 1
    service.delete_liability(liability_id)
    assert service.get_summary(liability_id) is None
    assert service.list_liabilities("all") == []
    totals = service.totals()
    assert totals.original_minor == 0
    assert totals.paid_minor == 0
    assert totals.outstanding_minor == 0
    assert totals.open_count == 0
    # Payment history is retained in the database instead of destructively removed.
    stored = service.repository.database.connection.execute(
        "SELECT COUNT(*) FROM liability_payments WHERE liability_id=?", (liability_id,)
    ).fetchone()[0]
    deleted = service.repository.database.connection.execute(
        "SELECT is_deleted,deleted_at FROM liabilities WHERE id=?", (liability_id,)
    ).fetchone()
    assert stored == 1
    assert deleted[0] == 1 and deleted[1]


def test_soft_delete_can_be_restored_with_payment_history(service):
    liability_id = service.create_liability(
        LiabilityInput("Undo loan", "Bank", "1000.00", "2026-09-01")
    )
    service.add_payment(
        liability_id, LiabilityPaymentInput("2026-09-10", "250.00", "kept payment")
    )
    service.delete_liability(liability_id)
    assert service.get_summary(liability_id) is None
    assert service.totals().open_count == 0
    service.restore_liability(liability_id)
    summary = service.get_summary(liability_id)
    assert summary is not None
    assert summary.paid_minor == 25000
    assert summary.remaining_minor == 75000
    assert len(service.list_payments(liability_id)) == 1
