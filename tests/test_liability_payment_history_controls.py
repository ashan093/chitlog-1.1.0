"""Liability payment editing/deletion and liability delete-history choices."""
import secrets

import pytest

from chitlog.data.database import Database
from chitlog.data.liability_repository import LiabilityRepository
from chitlog.data.settings_repository import SettingsRepository
from chitlog.services.liability_service import (
    LiabilityError,
    LiabilityInput,
    LiabilityPaymentInput,
    LiabilityService,
)


@pytest.fixture
def linked(tmp_path):
    db = Database(tmp_path / "test.db", secrets.token_bytes(32), tmp_path / "snapshots").open()
    service = LiabilityService(LiabilityRepository(db), "LKR")
    settings = SettingsRepository(db)
    yield db, service, settings
    db.close()


def make_liability(service):
    return service.create_liability(
        LiabilityInput("Vehicle loan", "Bank", "1000.00", "2026-09-01")
    )


def test_payment_edit_updates_balance_and_linked_expense(linked):
    db, service, _ = linked
    liability_id = make_liability(service)
    payment_id = service.add_payment(
        liability_id, LiabilityPaymentInput("2026-09-10", "250.00", "first")
    )
    service.update_payment(
        payment_id, LiabilityPaymentInput("2026-09-11", "300.00", "edited")
    )
    payment = service.get_payment(payment_id)
    assert payment.payment_date == "2026-09-11"
    assert payment.amount_minor == 30_000
    assert payment.note == "edited"
    summary = service.get_summary(liability_id)
    assert summary.paid_minor == 30_000
    assert summary.remaining_minor == 70_000
    mirror = db.connection.execute(
        "SELECT transaction_date,amount_minor,description,is_deleted "
        "FROM transactions WHERE liability_payment_id=?", (payment_id,)
    ).fetchone()
    assert mirror == (
        "2026-09-11", 30_000, "Liability payment — Vehicle loan — edited", 0
    )


def test_payment_delete_and_undo_sync_expense_and_totals(linked):
    db, service, _ = linked
    liability_id = make_liability(service)
    payment_id = service.add_payment(
        liability_id, LiabilityPaymentInput("2026-09-10", "250.00", "one")
    )
    assert service.delete_payment(payment_id) is True
    assert service.list_payments(liability_id) == []
    assert service.get_summary(liability_id).paid_minor == 0
    assert db.connection.execute(
        "SELECT is_deleted FROM transactions WHERE liability_payment_id=?", (payment_id,)
    ).fetchone()[0] == 1

    assert service.restore_payment(payment_id) is True
    assert len(service.list_payments(liability_id)) == 1
    assert service.get_summary(liability_id).paid_minor == 25_000
    assert db.connection.execute(
        "SELECT is_deleted FROM transactions WHERE liability_payment_id=?", (payment_id,)
    ).fetchone()[0] == 0


def test_delete_liability_can_keep_or_delete_transaction_history(linked):
    db, service, _ = linked

    keep_id = make_liability(service)
    keep_payment = service.add_payment(
        keep_id, LiabilityPaymentInput("2026-09-10", "100.00", "keep")
    )
    service.delete_liability(keep_id, keep_transaction_history=True)
    assert db.connection.execute(
        "SELECT is_deleted FROM transactions WHERE liability_payment_id=?", (keep_payment,)
    ).fetchone()[0] == 0

    service.restore_liability(keep_id)
    service.delete_liability(keep_id, keep_transaction_history=False)
    assert db.connection.execute(
        "SELECT is_deleted FROM transactions WHERE liability_payment_id=?", (keep_payment,)
    ).fetchone()[0] == 1

    service.restore_liability(keep_id)
    assert db.connection.execute(
        "SELECT is_deleted FROM transactions WHERE liability_payment_id=?", (keep_payment,)
    ).fetchone()[0] == 0


def test_settings_toggle_does_not_override_delete_history_choice(linked):
    db, service, settings = linked
    liability_id = make_liability(service)
    payment_id = service.add_payment(
        liability_id, LiabilityPaymentInput("2026-09-10", "100.00", "hidden with liability")
    )
    service.delete_liability(liability_id, keep_transaction_history=False)
    settings.set_liability_payments_in_transactions(False)
    settings.set_liability_payments_in_transactions(True)
    assert db.connection.execute(
        "SELECT is_deleted FROM transactions WHERE liability_payment_id=?", (payment_id,)
    ).fetchone()[0] == 1


def test_deleted_payment_cannot_be_restored_into_overpayment(linked):
    _, service, _ = linked
    liability_id = make_liability(service)
    first = service.add_payment(
        liability_id, LiabilityPaymentInput("2026-09-10", "600.00", "first")
    )
    assert service.delete_payment(first)
    service.add_payment(
        liability_id, LiabilityPaymentInput("2026-09-11", "700.00", "replacement")
    )
    with pytest.raises(LiabilityError, match="exceed the liability balance"):
        service.restore_payment(first)
