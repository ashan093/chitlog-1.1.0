"""Central exact money parsing, storage, and formatting helpers."""
from __future__ import annotations

from decimal import Decimal, InvalidOperation, ROUND_HALF_UP


CURRENCY_MINOR_DIGITS = {
    "JPY": 0,
}
DEFAULT_MINOR_DIGITS = 2
MAX_AMOUNT_MINOR = 999_999_999_999_99


class MoneyError(ValueError):
    """Safe validation error for user-entered monetary values."""


def minor_digits(currency_code: str) -> int:
    return CURRENCY_MINOR_DIGITS.get((currency_code or "").upper(), DEFAULT_MINOR_DIGITS)


def parse_amount_to_minor(value: str, currency_code: str) -> int:
    """Parse a positive amount string into integer minor units.

    No binary floating-point is used. Extra precision is rejected instead of
    being silently rounded, because financial data entry should be explicit.
    """
    text = (value or "").strip().replace(",", "")
    if not text:
        raise MoneyError("Enter an amount.")
    try:
        amount = Decimal(text)
    except InvalidOperation:
        raise MoneyError("Enter a valid amount.") from None
    if not amount.is_finite():
        raise MoneyError("Enter a valid amount.")
    if amount <= 0:
        raise MoneyError("Amount must be greater than zero.")

    digits = minor_digits(currency_code)
    quantum = Decimal(1).scaleb(-digits)
    try:
        quantized = amount.quantize(quantum, rounding=ROUND_HALF_UP)
    except InvalidOperation:
        raise MoneyError("Amount is too large.") from None
    if quantized != amount:
        if digits == 0:
            raise MoneyError("This currency does not use decimal minor units.")
        raise MoneyError(f"Enter no more than {digits} decimal places.")

    scale = Decimal(10) ** digits
    minor = int(quantized * scale)
    if minor > MAX_AMOUNT_MINOR:
        raise MoneyError("Amount is too large.")
    return minor


def minor_to_decimal(minor: int, currency_code: str) -> Decimal:
    if not isinstance(minor, int):
        raise MoneyError("Stored money value is invalid.")
    digits = minor_digits(currency_code)
    return Decimal(minor) / (Decimal(10) ** digits)


def amount_text_from_minor(minor: int, currency_code: str) -> str:
    digits = minor_digits(currency_code)
    value = minor_to_decimal(minor, currency_code)
    return f"{value:.{digits}f}"


def format_minor(minor: int, currency_code: str, symbol: str = "") -> str:
    digits = minor_digits(currency_code)
    value = minor_to_decimal(minor, currency_code)
    number = f"{value:,.{digits}f}"
    return f"{symbol} {number}".strip()
