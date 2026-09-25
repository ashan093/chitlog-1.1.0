"""Validated business logic for categories and financial transactions."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
import sqlcipher3 as sql

from chitlog.core.money import MoneyError, parse_amount_to_minor
from chitlog.data.transaction_repository import (
    CategoryRecord,
    TransactionRecord,
    TransactionRepository,
)


class TransactionError(ValueError):
    """Safe validation/business-rule error for the transactions module."""


@dataclass(frozen=True)
class TransactionInput:
    transaction_type: str
    transaction_date: str
    amount_text: str
    category_id: int
    description: str = ""
    payment_method: str | None = None


class TransactionService:
    def __init__(self, repository: TransactionRepository, currency_code: str):
        self.repository = repository
        self.currency_code = (currency_code or "LKR").upper()

    @staticmethod
    def _validate_kind(kind: str) -> str:
        value = (kind or "").strip().lower()
        if value not in {"income", "expense"}:
            raise TransactionError("Choose Income or Expense.")
        return value

    @staticmethod
    def _clean_category_name(name: str) -> str:
        value = " ".join((name or "").strip().split())
        if not value:
            raise TransactionError("Enter a category name.")
        if len(value) > 80:
            raise TransactionError("Category name must be 80 characters or fewer.")
        return value

    @staticmethod
    def _clean_description(value: str) -> str:
        value = (value or "").strip()
        if len(value) > 500:
            raise TransactionError("Description must be 500 characters or fewer.")
        return value

    @staticmethod
    def _clean_payment_method(value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = " ".join(value.strip().split())
        if not cleaned:
            return None
        if len(cleaned) > 80:
            raise TransactionError("Payment method must be 80 characters or fewer.")
        return cleaned

    @staticmethod
    def _validate_date(value: str) -> str:
        try:
            parsed = date.fromisoformat(value)
        except (TypeError, ValueError):
            raise TransactionError("Choose a valid date.") from None
        return parsed.isoformat()

    def list_categories(self, kind: str | None = None, *, include_inactive: bool = False) -> list[CategoryRecord]:
        if kind is not None:
            kind = self._validate_kind(kind)
        return self.repository.list_categories(kind, include_inactive=include_inactive)

    def add_category(self, kind: str, name: str) -> int:
        kind = self._validate_kind(kind)
        name = self._clean_category_name(name)
        try:
            return self.repository.add_category(kind, name)
        except sql.IntegrityError:
            raise TransactionError("A category with that name already exists for this type.") from None

    def rename_category(self, category_id: int, name: str) -> None:
        category = self.repository.get_category(category_id)
        if category is None:
            raise TransactionError("The selected category no longer exists.")
        name = self._clean_category_name(name)
        try:
            self.repository.rename_category(category_id, name)
        except sql.IntegrityError:
            raise TransactionError("A category with that name already exists for this type.") from None

    def set_category_active(self, category_id: int, active: bool) -> None:
        category = self.repository.get_category(category_id)
        if category is None:
            raise TransactionError("The selected category no longer exists.")
        self.repository.set_category_active(category_id, active)

    def _validated_input(self, value: TransactionInput) -> tuple[str, str, int, int, str, str | None]:
        kind = self._validate_kind(value.transaction_type)
        transaction_date = self._validate_date(value.transaction_date)
        try:
            amount_minor = parse_amount_to_minor(value.amount_text, self.currency_code)
        except MoneyError as error:
            raise TransactionError(str(error)) from None
        category = self.repository.get_category(value.category_id)
        if category is None:
            raise TransactionError("Choose a valid category.")
        if category.kind != kind:
            raise TransactionError("The selected category does not match the transaction type.")
        if not category.is_active:
            raise TransactionError("The selected category is archived. Choose an active category.")
        description = self._clean_description(value.description)
        payment_method = self._clean_payment_method(value.payment_method)
        return kind, transaction_date, amount_minor, category.id, description, payment_method

    def create_transaction(self, value: TransactionInput) -> int:
        kind, transaction_date, amount_minor, category_id, description, payment_method = self._validated_input(value)
        return self.repository.create_transaction(
            transaction_type=kind,
            transaction_date=transaction_date,
            amount_minor=amount_minor,
            category_id=category_id,
            description=description,
            payment_method=payment_method,
        )

    def is_worker_payment_expense(self, transaction_id: int) -> bool:
        source = self.repository.source_for(transaction_id)
        return source is not None and source[0] == "worker_payment"

    def is_liability_payment_expense(self, transaction_id: int) -> bool:
        return self.repository.liability_payment_for(transaction_id) is not None

    def linked_expense_reference(self, transaction_id: int) -> tuple[str, int] | None:
        """Return the authoritative payment record behind a linked expense."""
        source = self.repository.source_for(transaction_id)
        if source is not None and source[0] == "worker_payment" and source[1] is not None:
            return ("worker_payment", int(source[1]))
        liability_payment_id = self.repository.liability_payment_for(transaction_id)
        if liability_payment_id is not None:
            return ("liability_payment", int(liability_payment_id))
        return None

    def linked_expense_source(self, transaction_id: int) -> str | None:
        reference = self.linked_expense_reference(transaction_id)
        return reference[0] if reference is not None else None

    def update_transaction(self, transaction_id: int, value: TransactionInput) -> None:
        if self.repository.get_transaction(transaction_id) is None:
            raise TransactionError("The selected transaction no longer exists.")
        source = self.linked_expense_source(transaction_id)
        if source == "worker_payment":
            raise TransactionError("Worker payment expenses are managed from the Workers page.")
        if source == "liability_payment":
            raise TransactionError("Liability payment expenses are managed from the Liabilities page.")
        kind, transaction_date, amount_minor, category_id, description, payment_method = self._validated_input(value)
        self.repository.update_transaction(
            transaction_id,
            transaction_type=kind,
            transaction_date=transaction_date,
            amount_minor=amount_minor,
            category_id=category_id,
            description=description,
            payment_method=payment_method,
        )

    def get_transaction(self, transaction_id: int) -> TransactionRecord | None:
        return self.repository.get_transaction(transaction_id)

    def list_transactions(
        self,
        *,
        transaction_type: str | None = None,
        search: str = "",
        category_id: int | None = None,
        start_date: str | None = None,
        end_date: str | None = None,
        limit: int = 200,
    ) -> list[TransactionRecord]:
        if transaction_type is not None:
            transaction_type = self._validate_kind(transaction_type)
        if category_id is not None and self.repository.get_category(category_id) is None:
            raise TransactionError("The selected category no longer exists.")
        if start_date is not None:
            start_date = self._validate_date(start_date)
        if end_date is not None:
            end_date = self._validate_date(end_date)
        if start_date is not None and end_date is not None and start_date > end_date:
            raise TransactionError("The start date must not be after the end date.")
        limit = max(1, min(int(limit), 500))
        return self.repository.list_transactions(
            transaction_type=transaction_type,
            search=search[:120],
            category_id=category_id,
            start_date=start_date,
            end_date=end_date,
            limit=limit,
        )

    def delete_transaction(self, transaction_id: int) -> bool:
        if self.linked_expense_source(transaction_id) is not None:
            return False
        return self.repository.soft_delete(transaction_id)

    def undo_delete(self, transaction_id: int) -> bool:
        if self.linked_expense_source(transaction_id) is not None:
            return False
        return self.repository.restore(transaction_id)

    def totals(self) -> tuple[int, int, int]:
        income, expense = self.repository.totals()
        return income, expense, income - expense
