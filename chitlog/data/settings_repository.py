"""Encrypted persistence used by the completed Settings page."""
from __future__ import annotations

from dataclasses import dataclass

from chitlog.data.database import Database


@dataclass(frozen=True)
class StoredSettingsSnapshot:
    theme: str
    currency_code: str
    currency_symbol: str
    login_method: str
    secret_hash: str
    recovery_questions: tuple[str, str]


@dataclass(frozen=True)
class StoredRecoveryQuestion:
    position: int
    question: str
    answer_hash: str


class SettingsRepository:
    """Read/write only settings and authentication configuration.

    Financial records are never modified here.
    """

    _MONEY_RELATED_TABLES = (
        "transactions",
        "budgets",
        "budget_carry_forward",
        "liabilities",
        "liability_payments",
        "workers",
        "worker_work_records",
        "worker_attendance",
        "worker_payments",
        "worker_payroll_carry_forward",
    )

    def __init__(self, database: Database):
        self.database = database

    def _setting(self, key: str) -> str | None:
        row = self.database.connection.execute(
            "SELECT value FROM application_settings WHERE key=?",
            (key,),
        ).fetchone()
        return row[0] if row else None

    def load_snapshot(self) -> StoredSettingsSnapshot:
        auth = self.database.connection.execute(
            "SELECT login_method, secret_hash FROM auth_profile WHERE id=1"
        ).fetchone()
        if auth is None:
            raise RuntimeError("Authentication is not configured.")

        questions = self.database.connection.execute(
            "SELECT question FROM security_questions ORDER BY position"
        ).fetchall()
        if len(questions) != 2:
            raise RuntimeError("Account recovery is not configured correctly.")

        return StoredSettingsSnapshot(
            theme=self._setting("theme") or "light",
            currency_code=self._setting("currency_code") or "LKR",
            currency_symbol=self._setting("currency_symbol") or "Rs",
            login_method=str(auth[0]),
            secret_hash=str(auth[1]),
            recovery_questions=(str(questions[0][0]), str(questions[1][0])),
        )


    def worker_payments_in_transactions(self) -> bool:
        """Whether worker payments/advances should appear as transaction expenses."""
        value = self._setting("worker_payments_in_transactions")
        return value != "0"

    def set_worker_payments_in_transactions(self, enabled: bool) -> None:
        """Persist the preference and immediately show/hide linked worker expenses."""
        with self.database.transaction() as connection:
            connection.execute(
                "INSERT INTO application_settings(key,value) VALUES (?,?) "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value, "
                "updated_at=CURRENT_TIMESTAMP",
                ("worker_payments_in_transactions", "1" if enabled else "0"),
            )
            if enabled:
                connection.execute(
                    "UPDATE transactions SET "
                    "is_deleted=COALESCE((SELECT wp.is_deleted FROM worker_payments wp "
                    "WHERE wp.id=transactions.source_id),1), "
                    "deleted_at=CASE WHEN COALESCE((SELECT wp.is_deleted FROM worker_payments wp "
                    "WHERE wp.id=transactions.source_id),1)=0 THEN NULL ELSE CURRENT_TIMESTAMP END, "
                    "updated_at=CURRENT_TIMESTAMP "
                    "WHERE source_type='worker_payment'"
                )
            else:
                connection.execute(
                    "UPDATE transactions SET is_deleted=1, "
                    "deleted_at=COALESCE(deleted_at,CURRENT_TIMESTAMP), "
                    "updated_at=CURRENT_TIMESTAMP "
                    "WHERE source_type='worker_payment' AND is_deleted=0"
                )

    def liability_payments_in_transactions(self) -> bool:
        """Whether liability payments should appear as transaction expenses."""
        value = self._setting("liability_payments_in_transactions")
        return value != "0"

    def set_liability_payments_in_transactions(self, enabled: bool) -> None:
        """Persist the preference without overriding liability/payment deletion choices."""
        with self.database.transaction() as connection:
            connection.execute(
                "INSERT INTO application_settings(key,value) VALUES (?,?) "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value, "
                "updated_at=CURRENT_TIMESTAMP",
                ("liability_payments_in_transactions", "1" if enabled else "0"),
            )
            if enabled:
                eligible = (
                    "EXISTS (SELECT 1 FROM liability_payments lp "
                    "JOIN liabilities l ON l.id=lp.liability_id "
                    "WHERE lp.id=transactions.liability_payment_id "
                    "AND lp.is_deleted=0 "
                    "AND (l.is_deleted=0 OR l.keep_transaction_history_on_delete=1))"
                )
                connection.execute(
                    "UPDATE transactions SET is_deleted=0,deleted_at=NULL,"
                    "updated_at=CURRENT_TIMESTAMP "
                    "WHERE liability_payment_id IS NOT NULL AND is_deleted=1 AND " + eligible
                )
                connection.execute(
                    "UPDATE transactions SET is_deleted=1,"
                    "deleted_at=COALESCE(deleted_at,CURRENT_TIMESTAMP),"
                    "updated_at=CURRENT_TIMESTAMP "
                    "WHERE liability_payment_id IS NOT NULL AND is_deleted=0 AND NOT " + eligible
                )
            else:
                connection.execute(
                    "UPDATE transactions SET is_deleted=1,"
                    "deleted_at=COALESCE(deleted_at,CURRENT_TIMESTAMP),"
                    "updated_at=CURRENT_TIMESTAMP "
                    "WHERE liability_payment_id IS NOT NULL AND is_deleted=0"
                )

    def update_currency(self, code: str, symbol: str) -> None:
        """Persist the display/input currency without touching financial rows."""
        with self.database.transaction() as connection:
            connection.executemany(
                "INSERT INTO application_settings(key,value) VALUES (?,?) "
                "ON CONFLICT(key) DO UPDATE SET "
                "value=excluded.value, updated_at=CURRENT_TIMESTAMP",
                (
                    ("currency_code", code),
                    ("currency_symbol", symbol),
                ),
            )

    def update_credentials(self, login_method: str, secret_hash: str) -> None:
        with self.database.transaction() as connection:
            cursor = connection.execute(
                "UPDATE auth_profile "
                "SET login_method=?, secret_hash=?, updated_at=CURRENT_TIMESTAMP "
                "WHERE id=1",
                (login_method, secret_hash),
            )
            if cursor.rowcount != 1:
                raise RuntimeError("Authentication is not configured.")

    def replace_recovery_questions(
        self,
        questions: list[StoredRecoveryQuestion],
    ) -> None:
        if len(questions) != 2:
            raise ValueError("Exactly two recovery questions are required.")
        with self.database.transaction() as connection:
            connection.execute("DELETE FROM security_questions")
            connection.executemany(
                "INSERT INTO security_questions(position,question,answer_hash) "
                "VALUES (?,?,?)",
                [
                    (item.position, item.question, item.answer_hash)
                    for item in questions
                ],
            )

    def has_financial_records(self) -> bool:
        """Conservative guard for currency minor-unit precision changes.

        A change between currencies with different minor-unit precision is only
        safe before financial/worker data exists. Switching between two
        currencies that use the same precision is presentation-only and leaves
        every stored integer amount untouched.
        """
        connection = self.database.connection
        tables = {
            str(row[0])
            for row in connection.execute(
                "SELECT name FROM sqlite_master "
                "WHERE type='table' AND name NOT LIKE 'sqlite_%'"
            ).fetchall()
        }
        for table in self._MONEY_RELATED_TABLES:
            if table not in tables:
                continue
            row = connection.execute(
                f'SELECT 1 FROM "{table}" LIMIT 1'
            ).fetchone()
            if row is not None:
                return True
        return False
