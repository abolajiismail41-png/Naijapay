import uuid
from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.audit import service as audit
from app.modules.services.errors import PricingUnavailableError
from app.modules.services.models import PricingRule
from app.modules.services.pricing import RuleParams

_FIELDS = ("category", "provider_code", "scope_key", "tier", "method", "markup_bps", "markup_kobo",
           "custom_price_kobo", "fee_kobo", "discount_bps", "discount_kobo", "referral_bps", "rounding_kobo",
           "cap_at_face", "allow_subsidy", "subsidy_reason", "note")


def rule_dict(rule: PricingRule) -> dict[str, Any]:
    return {f: getattr(rule, f) for f in _FIELDS} | {"version": rule.version}


def params_of(rule: PricingRule) -> RuleParams:
    return RuleParams(rule.method, rule.markup_bps, rule.markup_kobo, rule.custom_price_kobo, rule.fee_kobo,
                      rule.discount_bps, rule.discount_kobo, rule.referral_bps, rule.cap_at_face, rule.allow_subsidy,
                      rule.rounding_kobo)


async def load_rules(db: AsyncSession, category: str) -> list[PricingRule]:
    return list((await db.execute(select(PricingRule).where(
        PricingRule.category == category, PricingRule.active.is_(True)))).scalars())


def pick_rule(rules: Sequence[PricingRule], provider_code: str, scope_keys: Sequence[str],
              tier: str = "DEFAULT") -> PricingRule:
    """Most specific active rule wins. `scope_keys` is ordered most- to least-specific
    (e.g. PLAN:100, MTN:SME, MTN); a rule with no scope is the category default."""
    def score(r: PricingRule) -> tuple[int, int]:
        rank = 0 if r.scope_key is None else len(scope_keys) - scope_keys.index(r.scope_key)
        return (rank * 100 + (r.provider_code is not None) * 10 + (tier != "DEFAULT" and r.tier == tier), r.version)
    ok = [r for r in rules if (r.scope_key is None or r.scope_key in scope_keys)
          and (r.provider_code is None or r.provider_code == provider_code) and r.tier in (tier, "DEFAULT")]
    if not ok:
        raise PricingUnavailableError(scope=list(scope_keys))
    return max(ok, key=score)


async def resolve_rule(db: AsyncSession, category: str, provider_code: str, scope_keys: Sequence[str],
                       tier: str = "DEFAULT") -> PricingRule:
    return pick_rule(await load_rules(db, category), provider_code, scope_keys, tier)


async def create_rule_version(db: AsyncSession, actor_id: uuid.UUID, data: dict[str, Any]) -> PricingRule:
    existing = (await db.execute(select(PricingRule).where(
        PricingRule.category == data["category"], PricingRule.tier == data["tier"], PricingRule.active.is_(True),
        PricingRule.provider_code.is_not_distinct_from(data.get("provider_code")),
        PricingRule.scope_key.is_not_distinct_from(data.get("scope_key"))).with_for_update())).scalar_one_or_none()
    before, version = None, 1
    if existing is not None:
        before, version = rule_dict(existing), existing.version + 1
        existing.active, existing.deactivated_at = False, datetime.now(UTC)
        await db.flush()  # free the unique "one active rule per scope" slot first
    rule = PricingRule(**{k: data.get(k) for k in _FIELDS if k in data}, version=version, created_by=actor_id, active=True)
    db.add(rule)
    await db.flush()
    audit.record(db, action="pricing.rule_changed", actor_user_id=actor_id, resource_type="pricing_rule",
                 resource_id=str(rule.id), before=before, after=rule_dict(rule))
    return rule
