from decimal import Decimal

import pytest

from app.core.money import Money


def test_from_naira_exact() -> None:
    assert Money.from_naira("5000.50").kobo == 500_050


def test_rejects_float() -> None:
    with pytest.raises(TypeError):
        Money.from_naira(0.1)  # type: ignore[arg-type]
    with pytest.raises(TypeError):
        Money(1.5)  # type: ignore[arg-type]


def test_arithmetic_is_exact() -> None:
    assert (Money(10) + Money(20) - Money(5)).kobo == 25


def test_percent_bankers_rounding() -> None:
    assert Money(250).percent(Decimal("1")).kobo == 2   # 2.5 -> 2
    assert Money(350).percent(Decimal("1")).kobo == 4   # 3.5 -> 4


def test_str_format() -> None:
    assert str(Money.from_naira(1234567)) == "NGN 1,234,567.00"
