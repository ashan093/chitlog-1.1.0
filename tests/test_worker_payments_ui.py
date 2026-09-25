"""One-page worker payment UI source checks."""
from pathlib import Path


def test_payment_and_advance_actions_are_in_main_activity_workspace():
    source=(Path(__file__).resolve().parents[1]/"chitlog/ui/pages/workers.py").read_text(encoding="utf-8")
    assert 'button("+ Payment")' in source
    assert 'button("+ Advance")' in source
    assert "WorkerPaymentDialog" in source
    assert 'force_type="advance" if advance else None' in source
    assert "self.payment_service.list_for_worker_month" in source
    assert '"payment"' in source
