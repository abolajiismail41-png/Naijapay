"""Money is integer kobo. Floats are rejected everywhere."""
from __future__ import annotations

from dataclasses import dataclass
from decimal import ROUND_HALF_EVEN, Decimal

KOBO_PER_NAIRA = 100
CURRENCY = "NGN"


@dataclass(frozen=True, slots=True, order=True)
class Money:
    kobo: int

    def __post_init__(self) -> None:
        if isinstance(self.kobo, bool) or not isinstance(self.kobo, int):
            raise TypeError("Money.kobo must be an int")

    @classmethod
    def from_naira(cls, value: Decimal | int | str) -> Money:
        if isinstance(value, float):
            raise TypeError("floats are not allowed for money")
        d = Decimal(value)
        return cls(int((d * KOBO_PER_NAIRA).to_integral_value(rounding=ROUND_HALF_EVEN)))

    @property
    def naira(self) -> Decimal:
        return Decimal(self.kobo) / KOBO_PER_NAIRA

    def __add__(self, other: Money) -> Money:
        return Money(self.kobo + other.kobo)

    def __sub__(self, other: Money) -> Money:
        return Money(self.kobo - other.kobo)

    def __neg__(self) -> Money:
        return Money(-self.kobo)

    def times(self, n: int) -> Money:
        if isinstance(n, bool) or not isinstance(n, int):
            raise TypeError("quantity must be an int")
        return Money(self.kobo * n)

    def percent(self, rate: Decimal) -> Money:
        """Deterministic percentage with banker's rounding to whole kobo."""
        return Money(int((Decimal(self.kobo) * rate / 100).to_integral_value(ROUND_HALF_EVEN)))

    def is_positive(self) -> bool:
        return self.kobo > 0

    def naira_str(self) -> str:
        return f"{self.naira.quantize(Decimal('0.01'))}"

    def __str__(self) -> str:
        return f"{CURRENCY} {self.naira:,.2f}"
