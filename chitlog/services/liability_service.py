"""Validation and exact-balance calculations for simple liabilities/loans."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from chitlog.core.money import MoneyError, parse_amount_to_minor
from chitlog.data.liability_repository import (
    LiabilityPaymentRecord,
    LiabilityRecord,
    LiabilityRepository,
)


class LiabilityError(ValueError):
    """Safe user-facing liability validation error."""


@dataclass(frozen=True)
class LiabilityInput:
    name: str
    lender: str
    original_amount: str
    start_date: str
    due_date: str | None = None
    notes: str = ""


@dataclass(frozen=True)
class LiabilityPaymentInput:
    payment_date: str
    amount: str
    note: str = ""


@dataclass(frozen=True)
class LiabilitySummary:
    id: int
    name: str
    lender: str
    original_amount_minor: int
    paid_minor: int
    remaining_minor: int
    start_date: str
    due_date: str | None
    notes: str
    status: str


@dataclass(frozen=True)
class LiabilityTotals:
    original_minor: int
    paid_minor: int
    outstanding_minor: int
    open_count: int


class LiabilityService:
    def __init__(self, repository: LiabilityRepository, currency_code: str):
        self.repository = repository
        self.currency_code = currency_code

    @staticmethod
    def _clean_text(value: str, *, field: str, max_length: int, required: bool = False) -> str:
        text = " ".join((value or "").strip().split())
        if required and not text:
            raise LiabilityError(f"Enter {field}.")
        if len(text) > max_length:
            raise LiabilityError(f"{field.capitalize()} must be {max_length} characters or fewer.")
        return text

    @staticmethod
    def _validate_date(value: str, field: str) -> str:
        try:
            parsed = date.fromisoformat(value)
        except (TypeError, ValueError):
            raise LiabilityError(f"Enter a valid {field}.") from None
        return parsed.isoformat()

    def _prepare_input(self, item: LiabilityInput) -> tuple[str, str, int, str, str | None, str]:
        name = self._clean_text(item.name, field="liability name", max_length=120, required=True)
        lender = self._clean_text(item.lender, field="lender", max_length=120)
        notes = self._clean_text(item.notes, field="notes", max_length=1000)
        start_date = self._validate_date(item.start_date, "start date")
        due_date = None
        if item.due_date:
            due_date = self._validate_date(item.due_date, "due date")
            if due_date < start_date:
                raise LiabilityError("Due date cannot be before the start date.")
        try:
            original_minor = parse_amount_to_minor(item.original_amount, self.currency_code)
        except MoneyError as error:
            raise LiabilityError(str(error)) from None
        return name, lender, original_minor, start_date, due_date, notes

    def create_liability(self, item: LiabilityInput) -> int:
        name, lender, original_minor, start_date, due_date, notes = self._prepare_input(item)
        return self.repository.create_liability(
            name=name,
            lender=lender,
            original_amount_minor=original_minor,
            start_date=start_date,
            due_date=due_date,
            notes=notes,
        )

    def update_liability(self, liability_id: int, item: LiabilityInput) -> None:
        existing = self.repository.get_liability(liability_id)
        if existing is None:
            raise LiabilityError("That liability no longer exists.")
        name, lender, original_minor, start_date, due_date, notes = self._prepare_input(item)
        paid = self.repository.total_paid_minor(liability_id)
        if original_minor < paid:
            raise LiabilityError("Original amount cannot be lower than payments already recorded.")
        payments = self.repository.list_payments(liability_id)
        if payments and start_date > min(payment.payment_date for payment in payments):
            raise LiabilityError("Start date cannot be after a payment already recorded for this liability.")
        if not self.repository.update_liability(
            liability_id,
            name=name,
            lender=lender,
            original_amount_minor=original_minor,
            start_date=start_date,
            due_date=due_date,
            notes=notes,
        ):
            raise LiabilityError("That liability no longer exists.")

    def get_summary(self, liability_id: int) -> LiabilitySummary | None:
        record = self.repository.get_liability(liability_id)
        if record is None:
            return None
        return self._summary(record)

    def _summary(self, record: LiabilityRecord) -> LiabilitySummary:
        paid = self.repository.total_paid_minor(record.id)
        remaining = record.original_amount_minor - paid
        if remaining < 0:
            remaining = 0
        return LiabilitySummary(
            id=record.id,
            name=record.name,
            lender=record.lender,
            original_amount_minor=record.original_amount_minor,
            paid_minor=paid,
            remaining_minor=remaining,
            start_date=record.start_date,
            due_date=record.due_date,
            notes=record.notes,
            status="Paid" if remaining == 0 else "Open",
        )

    def list_liabilities(self, status: str | None = None) -> list[LiabilitySummary]:
        normalized = (status or "all").strip().lower()
        if normalized not in {"all", "open", "paid"}:
            raise LiabilityError("Invalid liability filter.")
        items = [self._summary(record) for record in self.repository.list_liabilities()]
        if normalized == "open":
            return [item for item in items if item.remaining_minor > 0]
        if normalized == "paid":
            return [item for item in items if item.remaining_minor == 0]
        return items

    def delete_liability(self, liability_id: int) -> None:
        summary = self.get_summary(liability_id)
        if summary is None:
            raise LiabilityError("That liability no longer exists.")
        if not self.repository.soft_delete_liability(liability_id):
            raise LiabilityError("That liability could not be deleted.")

    def restore_liability(self, liability_id: int) -> None:
        """Undo a soft deletion while preserving the liability and payment history."""
        if not self.repository.restore_liability(liability_id):
            raise LiabilityError("That liability could not be restored.")

    def add_payment(self, liability_id: int, item: LiabilityPaymentInput) -> int:
        summary = self.get_summary(liability_id)
        if summary is None:
            raise LiabilityError("That liability no longer exists.")
        if summary.remaining_minor <= 0:
            raise LiabilityError("This liability is already fully paid.")
        payment_date = self._validate_date(item.payment_date, "payment date")
        if payment_date < summary.start_date:
            raise LiabilityError("Payment date cannot be before the liability start date.")
        note = self._clean_text(item.note, field="payment note", max_length=500)
        try:
            amount_minor = parse_amount_to_minor(item.amount, self.currency_code)
        except MoneyError as error:
            raise LiabilityError(str(error)) from None
        if amount_minor > summary.remaining_minor:
            raise LiabilityError("Payment cannot be greater than the remaining balance.")
        return self.repository.add_payment(
            liability_id=liability_id,
            payment_date=payment_date,
            amount_minor=amount_minor,
            note=note,
        )

    def list_payments(self, liability_id: int) -> list[LiabilityPaymentRecord]:
        if self.repository.get_liability(liability_id) is None:
            raise LiabilityError("That liability no longer exists.")
        return self.repository.list_payments(liability_id)

    def totals(self) -> LiabilityTotals:
        original, paid = self.repository.aggregate_totals()
        items = self.list_liabilities("all")
        outstanding = sum(item.remaining_minor for item in items)
        open_count = sum(1 for item in items if item.remaining_minor > 0)
        return LiabilityTotals(original, paid, outstanding, open_count)
