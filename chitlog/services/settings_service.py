"""Business rules for Step 20 Settings completion."""
from __future__ import annotations

from dataclasses import dataclass

from chitlog.core.money import minor_digits
from chitlog.core.security import (
    SecurityError,
    SecurityQuestionAnswer,
    hash_secret,
    hash_security_answer,
    validate_secret,
    validate_security_questions,
    verify_secret,
)
from chitlog.core.settings import THEMES
from chitlog.data.settings_repository import (
    SettingsRepository,
    StoredRecoveryQuestion,
)
from chitlog.services.setup_service import CURRENCIES, CurrencyOption


class SettingsError(ValueError):
    """Safe validation error for Settings actions."""


@dataclass(frozen=True)
class SettingsSnapshot:
    theme: str
    currency_code: str
    currency_symbol: str
    login_method: str
    recovery_questions: tuple[str, str]


class SettingsService:
    """Central Settings business logic.

    This service never performs FX conversion and never stores plaintext login
    secrets or recovery answers.
    """

    def __init__(self, repository: SettingsRepository):
        self.repository = repository
        self._currencies = {item.code: item for item in CURRENCIES}

    @property
    def currencies(self) -> tuple[CurrencyOption, ...]:
        return CURRENCIES

    @property
    def themes(self) -> tuple[str, ...]:
        return THEMES

    def snapshot(self) -> SettingsSnapshot:
        stored = self.repository.load_snapshot()
        theme = stored.theme if stored.theme in THEMES else "light"
        return SettingsSnapshot(
            theme=theme,
            currency_code=stored.currency_code,
            currency_symbol=stored.currency_symbol,
            login_method=stored.login_method,
            recovery_questions=stored.recovery_questions,
        )

    def change_currency(self, code: str) -> CurrencyOption:
        code = (code or "").strip().upper()
        currency = self._currencies.get(code)
        if currency is None:
            raise SettingsError("Choose a valid currency.")

        current = self.repository.load_snapshot()
        if current.currency_code == currency.code:
            return currency

        old_digits = minor_digits(current.currency_code)
        new_digits = minor_digits(currency.code)
        if (
            old_digits != new_digits
            and self.repository.has_financial_records()
        ):
            raise SettingsError(
                "This currency uses different decimal precision from your current "
                "currency. ChitLog will not reinterpret existing financial records. "
                "Choose a currency with the same precision, or change precision only "
                "before financial/worker records are created."
            )

        self.repository.update_currency(currency.code, currency.symbol)
        return currency

    def change_credentials(
        self,
        *,
        current_secret: str,
        login_method: str,
        new_secret: str,
        confirmation: str,
    ) -> str:
        stored = self.repository.load_snapshot()
        if not verify_secret(stored.secret_hash, current_secret or ""):
            raise SettingsError("Current PIN/password is incorrect.")

        try:
            validate_secret(login_method, new_secret, confirmation)
            new_hash = hash_secret(login_method, new_secret)
        except SecurityError as error:
            raise SettingsError(str(error)) from None

        self.repository.update_credentials(login_method, new_hash)
        return login_method

    def change_recovery_questions(
        self,
        *,
        current_secret: str,
        questions: list[SecurityQuestionAnswer],
    ) -> tuple[str, str]:
        stored = self.repository.load_snapshot()
        if not verify_secret(stored.secret_hash, current_secret or ""):
            raise SettingsError("Current PIN/password is incorrect.")

        try:
            cleaned = validate_security_questions(questions)
        except SecurityError as error:
            raise SettingsError(str(error)) from None

        self.repository.replace_recovery_questions(
            [
                StoredRecoveryQuestion(
                    position=index,
                    question=item.question,
                    answer_hash=hash_security_answer(item.answer),
                )
                for index, item in enumerate(cleaned, start=1)
            ]
        )
        return (cleaned[0].question, cleaned[1].question)
