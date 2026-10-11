from dataclasses import dataclass
from decimal import Decimal

from app.core.config import Settings
from app.core.money import Money


@dataclass(frozen=True)
class FundingFeePolicy:
    """fee = min(cap, percent * amount + flat), with the flat part waived for small amounts."""

    percent: Decimal
    flat: Money
    flat_waived_below: Money
    cap: Money

    @classmethod
    def from_settings(cls, s: Settings) -> "FundingFeePolicy":
        return cls(s.funding_fee_percent, Money(s.funding_fee_flat_kobo),
                   Money(s.funding_fee_flat_waived_below_kobo), Money(s.funding_fee_cap_kobo))

    def fee_for(self, amount: Money) -> Money:
        flat = Money(0) if amount < self.flat_waived_below else self.flat
        return min(amount.percent(self.percent) + flat, self.cap)

