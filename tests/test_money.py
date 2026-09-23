"""Exact money conversion tests for Step 7."""
import pytest

from chitlog.core.money import MoneyError, amount_text_from_minor, format_minor, parse_amount_to_minor


def test_two_decimal_currency_roundtrip():
    assert parse_amount_to_minor("1,234.56", "LKR") == 123456
    assert amount_text_from_minor(123456, "LKR") == "1234.56"
    assert format_minor(123456, "LKR", "Rs") == "Rs 1,234.56"


def test_jpy_uses_whole_minor_units():
    assert parse_amount_to_minor("1500", "JPY") == 1500
    assert format_minor(1500, "JPY", "¥") == "¥ 1,500"
    with pytest.raises(MoneyError):
        parse_amount_to_minor("1500.5", "JPY")


@pytest.mark.parametrize("value", ["", "abc", "0", "-1", "1.234", "NaN", "Infinity"])
def test_invalid_amounts_rejected(value):
    with pytest.raises(MoneyError):
        parse_amount_to_minor(value, "USD")
