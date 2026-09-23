"""Business logic for the first-run setup wizard."""
from __future__ import annotations

from dataclasses import dataclass

from chitlog.core.security import (
    SecurityError,
    SecurityQuestionAnswer,
    hash_secret,
    hash_security_answer,
    validate_secret,
    validate_security_questions,
)
from chitlog.core.settings import AppearanceSettings, THEMES
from chitlog.data.setup_repository import SetupRepository, StoredSetupQuestion


@dataclass(frozen=True)
class CurrencyOption:
    code: str
    symbol: str
    label: str


CURRENCIES: tuple[CurrencyOption, ...] = (
    CurrencyOption("LKR", "Rs", "Sri Lankan Rupee (LKR — Rs)"),
    CurrencyOption("USD", "$", "US Dollar (USD — $)"),
    CurrencyOption("EUR", "€", "Euro (EUR — €)"),
    CurrencyOption("GBP", "£", "British Pound (GBP — £)"),
    CurrencyOption("AUD", "A$", "Australian Dollar (AUD — A$)"),
    CurrencyOption("CAD", "C$", "Canadian Dollar (CAD — C$)"),
    CurrencyOption("INR", "₹", "Indian Rupee (INR — ₹)"),
    CurrencyOption("JPY", "¥", "Japanese Yen (JPY — ¥)"),
)

_CURRENCY_MAP = {item.code: item for item in CURRENCIES}


@dataclass(frozen=True)
class SetupSubmission:
    login_method: str
    secret: str
    confirmation: str
    security_questions: list[SecurityQuestionAnswer]
    currency_code: str
    theme: str


class SetupService:
    def __init__(
        self,
        repository: SetupRepository,
        appearance_settings: AppearanceSettings,
    ):
        self.repository = repository
        self.appearance_settings = appearance_settings

    def is_setup_complete(self) -> bool:
        return self.repository.is_setup_complete()

    def complete_setup(self, submission: SetupSubmission) -> None:
        validate_secret(
            submission.login_method,
            submission.secret,
            submission.confirmation,
        )
        questions = validate_security_questions(submission.security_questions)

        if submission.currency_code not in _CURRENCY_MAP:
            raise SecurityError("Choose a valid currency.")
        if submission.theme not in THEMES:
            raise SecurityError("Choose a valid theme.")

        currency = _CURRENCY_MAP[submission.currency_code]
        self.repository.save_setup(
            login_method=submission.login_method,
            secret_hash=hash_secret(submission.login_method, submission.secret),
            questions=[
                StoredSetupQuestion(
                    position=index,
                    question=item.question,
                    answer_hash=hash_security_answer(item.answer),
                )
                for index, item in enumerate(questions, start=1)
            ],
            currency_code=currency.code,
            currency_symbol=currency.symbol,
            theme=submission.theme,
        )

        try:
            self.appearance_settings.save_theme(submission.theme)
        except OSError:
            # The encrypted database is authoritative. This small preference file
            # is only a convenience for choosing the pre-login appearance.
            pass
