"""What other modules may use from `services`."""
import logging
import uuid
from collections.abc import Sequence
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.money import Money
from app.modules.services.errors import PriceChangedError, PricingBlockedError, PricingUnavailableError
from app.modules.services.models import PricingRule, PricingSnapshot
from app.modules.services.pricing import PriceBreakdown, compute, compute_scaled
from app.modules.services.rules import load_rules, params_of, pick_rule

log = logging.getLogger(__name__)


async def price_for(db: AsyncSession, *, category: str, provider_code: str, scope_keys: Sequence[str], cost: Money,
                    face: Money | None, tier: str = "DEFAULT", referral_applicable: bool = False,
                    quantity: int = 1) -> tuple[PriceBreakdown, PricingRule]:
    """`cost` is per unit; the breakdown returned is for `quantity` units."""
    rule = pick_rule(await load_rules(db, category), provider_code, scope_keys, tier)
    return compute_scaled(cost, params_of(rule), quantity=quantity, face=face, referral_applicable=referral_applicable), rule


async def price_many(db: AsyncSession, *, category: str, provider_code: str,
                     items: Sequence[tuple[Any, ...]], tier: str = "DEFAULT") -> list[PriceBreakdown | None]:
    """Price a whole catalogue with one rules query. None = no rule or the price would be below cost."""
    rules, out = await load_rules(db, category), []
    for scope_keys, cost, *rest in items:   # optional third element: the face value (needed by FACE_VALUE rules)
        try:
            out.append(compute(cost, params_of(pick_rule(rules, provider_code, scope_keys, tier)),
                               face=rest[0] if rest else None))
        except (PricingBlockedError, PricingUnavailableError):
            out.append(None)
    return out


def add_snapshot(db: AsyncSession, *, transaction_id: uuid.UUID, rule: PricingRule, b: PriceBreakdown,
                 provider_code: str, cost_source: str) -> None:
    db.add(PricingSnapshot(
        transaction_id=transaction_id, rule_id=rule.id, rule_version=rule.version, method=rule.method,
        provider_code=provider_code, cost_source=cost_source, cost_kobo=b.cost.kobo, markup_kobo=b.markup.kobo,
        fee_kobo=b.fee.kobo, list_price_kobo=b.list_price.kobo, discount_kobo=b.discount.kobo,
        customer_price_kobo=b.customer_price.kobo, referral_commission_kobo=b.referral_commission.kobo,
        processing_cost_kobo=b.processing_cost.kobo,
        gross_profit_before_discount_kobo=b.gross_profit_before_discount.kobo,
        gross_profit_kobo=b.gross_profit.kobo, net_contribution_kobo=b.net_contribution.kobo,
        margin_pct=b.margin_pct, capped=b.capped, subsidized=b.below_cost))


__all__ = ["PriceChangedError", "PricingBlockedError", "PricingUnavailableError", "add_snapshot", "price_for",
           "price_many"]
