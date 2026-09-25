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

    def _include_in_transactions(self) -> bool:
        row = self.repository.database.connection.execute(
            "SELECT value FROM application_settings WHERE key=?",
            ("liability_payments_in_transactions",),
        ).fetchone()
        return row is None or str(row[0]) != "0"

    @staticmethod
    def _expense_category_id(connection) -> int:
        row = connection.execute(
            "SELECT id FROM categories WHERE kind='expense' "
            "ORDER BY CASE WHEN lower(name)='bills' THEN 0 ELSE 1 END,id LIMIT 1"
        ).fetchone()
        if row is None:
            raise LiabilityError("No expense category is available for liability payments.")
        return int(row[0])

    def _sync_transaction_expense(self, payment_id: int, *, connection=None) -> None:
        """Keep one linked expense aligned with the authoritative liability payment.

        Visibility depends on three independent states: the global Settings toggle,
        whether the payment itself is deleted, and—when its liability is deleted—
        whether the user chose to keep or remove linked Transaction history.
        """
        tx = connection if connection is not None else self.repository.database.connection
        payment = self.repository.get_payment(
            payment_id, include_deleted=True, connection=tx
        )
        if payment is None:
            return
        liability = tx.execute(
            "SELECT name,is_deleted,keep_transaction_history_on_delete,deleted_at "
            "FROM liabilities WHERE id=?",
            (payment.liability_id,),
        ).fetchone()
        if liability is None:
            return

        liability_name = str(liability[0])
        liability_deleted = bool(liability[1])
        keep_history = bool(liability[2])
        liability_deleted_at = liability[3]
        category_id = self._expense_category_id(tx)
        description = f"Liability payment — {liability_name}"
        if payment.note:
            description += f" — {payment.note}"
        description = description[:500]

        visible = (
            self._include_in_transactions()
            and not payment.is_deleted
            and (not liability_deleted or keep_history)
        )
        deleted = 0 if visible else 1
        hidden_at = None if visible else (
            payment.deleted_at
            or liability_deleted_at
            or payment.updated_at
            or payment.created_at
        )

        def sync(write_connection) -> None:
            linked = write_connection.execute(
                "SELECT id,transaction_type,transaction_date,amount_minor,category_id,description,"
                "payment_method,is_deleted,deleted_at FROM transactions "
                "WHERE liability_payment_id=?",
                (payment_id,),
            ).fetchone()
            target = (
                "expense",
                payment.payment_date,
                int(payment.amount_minor),
                category_id,
                description,
                "Liability Payment",
                int(deleted),
                hidden_at,
            )
            if linked is None:
                write_connection.execute(
                    "INSERT INTO transactions("
                    "transaction_type,transaction_date,amount_minor,category_id,description,"
                    "payment_method,is_deleted,deleted_at,source_type,source_id,liability_payment_id"
                    ") VALUES ('expense',?,?,?,?,?,?,?,?,?,?)",
                    (
                        payment.payment_date,
                        payment.amount_minor,
                        category_id,
                        description,
                        "Liability Payment",
                        deleted,
                        hidden_at,
                        "manual",
                        None,
                        payment_id,
                    ),
                )
                return
            current = (
                str(linked[1]),
                str(linked[2]),
                int(linked[3]),
                int(linked[4]),
                str(linked[5]),
                str(linked[6] or ""),
                int(linked[7]),
                linked[8],
            )
            if current == target:
                return
            write_connection.execute(
                "UPDATE transactions SET transaction_type='expense',transaction_date=?,"
                "amount_minor=?,category_id=?,description=?,payment_method='Liability Payment',"
                "is_deleted=?,deleted_at=?,updated_at=CURRENT_TIMESTAMP WHERE id=?",
                (
                    payment.payment_date,
                    payment.amount_minor,
                    category_id,
                    description,
                    deleted,
                    hidden_at,
                    int(linked[0]),
                ),
            )

        if connection is not None:
            sync(connection)
        else:
            with self.repository.database.transaction() as write_connection:
                sync(write_connection)

    def reconcile_transaction_expenses(self) -> None:
        """Repair missing/orphaned mirrors while preserving delete-history choices."""
        with self.repository.database.transaction() as tx:
            payment_ids = [
                int(row[0])
                for row in tx.execute("SELECT id FROM liability_payments ORDER BY id").fetchall()
            ]
            for payment_id in payment_ids:
                self._sync_transaction_expense(payment_id, connection=tx)
            tx.execute(
                "DELETE FROM transactions WHERE liability_payment_id IS NOT NULL "
                "AND NOT EXISTS (SELECT 1 FROM liability_payments lp "
                "WHERE lp.id=transactions.liability_payment_id)"
            )

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
        with self.repository.database.transaction() as tx:
            if not self.repository.update_liability(
                liability_id,
                name=name,
                lender=lender,
                original_amount_minor=original_minor,
                start_date=start_date,
                due_date=due_date,
                notes=notes,
                connection=tx,
            ):
                raise LiabilityError("That liability no longer exists.")
            for payment in self.repository.list_payments(
                liability_id, include_deleted=True, connection=tx
            ):
                self._sync_transaction_expense(payment.id, connection=tx)

    def get_summary(self, liability_id: int) -> LiabilitySummary | None:
        record = self.repository.get_liability(liability_id)
        if record is None:
            return None
        return self._summary(record)

    def _summary(self, record: LiabilityRecord) -> LiabilitySummary:
        paid = self.repository.total_paid_minor(record.id)
        remaining = max(0, record.original_amount_minor - paid)
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

    def delete_liability(
        self,
        liability_id: int,
        *,
        keep_transaction_history: bool = True,
    ) -> None:
        summary = self.get_summary(liability_id)
        if summary is None:
            raise LiabilityError("That liability no longer exists.")
        with self.repository.database.transaction() as tx:
            if not self.repository.soft_delete_liability(
                liability_id,
                keep_transaction_history=keep_transaction_history,
                connection=tx,
            ):
                raise LiabilityError("That liability could not be deleted.")
            for payment in self.repository.list_payments(
                liability_id, include_deleted=True, connection=tx
            ):
                self._sync_transaction_expense(payment.id, connection=tx)

    def restore_liability(self, liability_id: int) -> None:
        """Undo liability deletion and restore eligible linked expense visibility."""
        with self.repository.database.transaction() as tx:
            if not self.repository.restore_liability(liability_id, connection=tx):
                raise LiabilityError("That liability could not be restored.")
            for payment in self.repository.list_payments(
                liability_id, include_deleted=True, connection=tx
            ):
                self._sync_transaction_expense(payment.id, connection=tx)

    def _prepare_payment(
        self,
        liability_id: int,
        item: LiabilityPaymentInput,
        *,
        replacing_amount_minor: int = 0,
    ) -> tuple[str, int, str]:
        summary = self.get_summary(liability_id)
        if summary is None:
            raise LiabilityError("That liability no longer exists.")
        payment_date = self._validate_date(item.payment_date, "payment date")
        if payment_date < summary.start_date:
            raise LiabilityError("Payment date cannot be before the liability start date.")
        note = self._clean_text(item.note, field="payment note", max_length=500)
        try:
            amount_minor = parse_amount_to_minor(item.amount, self.currency_code)
        except MoneyError as error:
            raise LiabilityError(str(error)) from None
        maximum = summary.remaining_minor + int(replacing_amount_minor)
        if amount_minor > maximum:
            raise LiabilityError("Payment cannot be greater than the remaining balance.")
        return payment_date, amount_minor, note

    def add_payment(self, liability_id: int, item: LiabilityPaymentInput) -> int:
        summary = self.get_summary(liability_id)
        if summary is None:
            raise LiabilityError("That liability no longer exists.")
        if summary.remaining_minor <= 0:
            raise LiabilityError("This liability is already fully paid.")
        payment_date, amount_minor, note = self._prepare_payment(liability_id, item)
        with self.repository.database.transaction() as tx:
            payment_id = self.repository.add_payment(
                liability_id=liability_id,
                payment_date=payment_date,
                amount_minor=amount_minor,
                note=note,
                connection=tx,
            )
            self._sync_transaction_expense(payment_id, connection=tx)
        return payment_id

    def get_payment(
        self, payment_id: int, *, include_deleted: bool = False
    ) -> LiabilityPaymentRecord | None:
        return self.repository.get_payment(payment_id, include_deleted=include_deleted)

    def update_payment(self, payment_id: int, item: LiabilityPaymentInput) -> None:
        existing = self.repository.get_payment(payment_id)
        if existing is None:
            raise LiabilityError("That liability payment no longer exists.")
        payment_date, amount_minor, note = self._prepare_payment(
            existing.liability_id,
            item,
            replacing_amount_minor=existing.amount_minor,
        )
        with self.repository.database.transaction() as tx:
            if not self.repository.update_payment(
                payment_id,
                payment_date=payment_date,
                amount_minor=amount_minor,
                note=note,
                connection=tx,
            ):
                raise LiabilityError("That liability payment could not be updated.")
            self._sync_transaction_expense(payment_id, connection=tx)

    def delete_payment(self, payment_id: int) -> bool:
        existing = self.repository.get_payment(payment_id)
        if existing is None:
            return False
        with self.repository.database.transaction() as tx:
            changed = self.repository.soft_delete_payment(payment_id, connection=tx)
            if changed:
                self._sync_transaction_expense(payment_id, connection=tx)
            return changed

    def restore_payment(self, payment_id: int) -> bool:
        existing = self.repository.get_payment(payment_id, include_deleted=True)
        if existing is None or not existing.is_deleted:
            return False

        # A liability may itself be deleted while its Transaction history is kept.
        # In that state the historical payment can still be deleted/restored from
        # Transactions even though the Liabilities page no longer shows the parent.
        liability_state = self.repository.database.connection.execute(
            "SELECT is_deleted,keep_transaction_history_on_delete FROM liabilities WHERE id=?",
            (existing.liability_id,),
        ).fetchone()
        if liability_state is None:
            raise LiabilityError("The liability for this payment no longer exists.")
        liability_deleted = bool(liability_state[0])
        keep_history = bool(liability_state[1])

        if liability_deleted:
            if not keep_history:
                raise LiabilityError("Restore the liability before restoring this payment.")
        else:
            summary = self.get_summary(existing.liability_id)
            if summary is None:
                raise LiabilityError("Restore the liability before restoring this payment.")
            if existing.amount_minor > summary.remaining_minor:
                raise LiabilityError(
                    "This payment cannot be restored because it would exceed the liability balance."
                )

        with self.repository.database.transaction() as tx:
            changed = self.repository.restore_payment(payment_id, connection=tx)
            if changed:
                self._sync_transaction_expense(payment_id, connection=tx)
            return changed

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
