import logging
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.money import Money
from app.modules.audit import service as audit
from app.modules.providers.base import BillProvider
from app.modules.providers.models import DataPlan, ProviderPrice

log = logging.getLogger(__name__)
_MAX_DISCOUNT_BPS = 2000  # a provider discount above 20% is far more likely a parsing error than a gift


def is_fresh(row: ProviderPrice, max_age_h: int) -> bool:
    """A SYNCED cost older than the limit is untrusted; SEED/MANUAL values are the operator's responsibility."""
    return not (row.source == "SYNCED" and row.synced_at and row.synced_at < datetime.now(UTC) - timedelta(hours=max_age_h))


async def airtime_price(db: AsyncSession, provider_code: str, network: str) -> ProviderPrice | None:
    return (await db.execute(select(ProviderPrice).where(
        ProviderPrice.provider_code == provider_code, ProviderPrice.category == "AIRTIME",
        ProviderPrice.scope_key == network, ProviderPrice.active.is_(True))
        .order_by(ProviderPrice.updated_at.desc()).limit(1))).scalar_one_or_none()


def expected_cost(row: ProviderPrice, face: Money) -> Money:
    """What the provider will charge us for `face` of airtime, from the current catalogue value."""
    if row.kind == "DISCOUNT_BPS":
        return face - face.percent(Decimal(row.value) / 100)
    return Money(row.value)


@dataclass(frozen=True)
class SyncReport:
    updated: int
    unchanged: int
    rejected: int


async def sync_costs(db: AsyncSession, provider: BillProvider, provider_code: str = "inlomax", *,
                     actor_id: object = None) -> SyncReport:
    entries = await provider.fetch_costs()
    now, updated, unchanged, rejected = datetime.now(UTC), 0, 0, 0
    for e in entries:
        if e.kind == "DISCOUNT_BPS" and not 0 <= e.value <= _MAX_DISCOUNT_BPS:
            rejected += 1
            audit.record(db, action="provider_price.rejected", actor_user_id=actor_id,
                         meta={"scope": e.scope_key, "value": e.value})
            continue
        row = (await db.execute(select(ProviderPrice).where(
            ProviderPrice.provider_code == provider_code, ProviderPrice.category == e.category,
            ProviderPrice.scope_key == e.scope_key, ProviderPrice.provider_service_id == e.provider_service_id)
            .with_for_update())).scalars().first()
        if row is None:
            continue  # unknown products are not auto-created: an admin must enable them deliberately
        if row.source == "MANUAL":
            unchanged += 1
            continue  # an explicit admin override is never overwritten by a sync
        if row.value != e.value:
            audit.record(db, action="provider_price.changed", actor_user_id=actor_id, resource_type="provider_price",
                         resource_id=f"{row.category}:{row.scope_key}", before={"value": row.value}, after={"value": e.value})
            row.value, updated = e.value, updated + 1
        else:
            unchanged += 1
        row.source, row.synced_at = "SYNCED", now
    await db.commit()
    return SyncReport(updated, unchanged, rejected)


NETWORKS = ("MTN", "AIRTEL", "GLO", "9MOBILE")


async def data_price(db: AsyncSession, provider_code: str, service_id: str) -> ProviderPrice | None:
    return (await db.execute(select(ProviderPrice).where(
        ProviderPrice.provider_code == provider_code, ProviderPrice.category == "DATA",
        ProviderPrice.provider_service_id == service_id, ProviderPrice.active.is_(True)))).scalar_one_or_none()


@dataclass(frozen=True)
class DataSyncReport:
    created: int
    updated: int
    deactivated: int
    rejected: int
    suspicious: bool


async def sync_data_plans(db: AsyncSession, provider: BillProvider, provider_code: str = "inlomax", *,
                          actor_id: object = None) -> DataSyncReport:
    """New plans arrive UNLISTED; costs of existing plans follow the provider (MANUAL overrides excepted)."""
    entries = await provider.fetch_data_plans()
    valid = [e for e in entries if e.cost_kobo > 0 and e.network in NETWORKS]
    rejected = len(entries) - len(valid)
    if not valid:  # an empty or garbled answer must never switch the catalogue off
        audit.record(db, action="data_plan.sync_empty", actor_user_id=actor_id, meta={"received": len(entries)})
        await db.commit()
        return DataSyncReport(0, 0, 0, rejected, False)
    now, created, updated = datetime.now(UTC), 0, 0
    plans = {p.provider_service_id: p for p in (await db.execute(select(DataPlan).where(
        DataPlan.provider_code == provider_code))).scalars()}
    prices = {p.provider_service_id: p for p in (await db.execute(select(ProviderPrice).where(
        ProviderPrice.provider_code == provider_code, ProviderPrice.category == "DATA"))).scalars()}
    for e in valid:
        plan, price = plans.get(e.provider_service_id), prices.get(e.provider_service_id)
        if plan is None:
            db.add(DataPlan(provider_code=provider_code, provider_service_id=e.provider_service_id, network=e.network,
                            name=e.name, data_type=e.data_type, validity=e.validity, listed=False, active=True))
            audit.record(db, action="data_plan.discovered", actor_user_id=actor_id, resource_type="data_plan",
                         resource_id=e.provider_service_id, after={"network": e.network, "name": e.name, "cost_kobo": e.cost_kobo})
            created += 1
        else:
            plan.network, plan.name, plan.data_type, plan.validity, plan.active = (
                e.network, e.name, e.data_type, e.validity, True)
        if price is None:
            db.add(ProviderPrice(provider_code=provider_code, category="DATA", scope_key=e.provider_service_id,
                                 provider_service_id=e.provider_service_id, kind="FIXED_KOBO", value=e.cost_kobo,
                                 source="SYNCED", synced_at=now, active=True))
        elif price.source != "MANUAL":
            if price.value != e.cost_kobo:
                audit.record(db, action="provider_price.changed", actor_user_id=actor_id, resource_type="provider_price",
                             resource_id=f"DATA:{e.provider_service_id}", before={"value": price.value}, after={"value": e.cost_kobo})
                price.value, updated = e.cost_kobo, updated + 1
            price.source, price.synced_at, price.active = "SYNCED", now, True
    returned = {e.provider_service_id for e in valid}
    vanished = [p for sid, p in plans.items() if sid not in returned and p.active]
    active_known = [p for p in plans.values() if p.active]
    suspicious = bool(active_known) and len(vanished) * 2 > len(active_known)  # most of the catalogue vanished at once
    deactivated = 0
    if suspicious:
        audit.record(db, action="data_plan.sync_suspicious", actor_user_id=actor_id,
                     meta={"vanished": len(vanished), "known": len(plans)})
    else:
        for p in vanished:
            p.active = False
            if (pr := prices.get(p.provider_service_id)) is not None:
                pr.active = False
            audit.record(db, action="data_plan.removed", actor_user_id=actor_id, resource_type="data_plan",
                         resource_id=p.provider_service_id)
            deactivated += 1
    await db.commit()
    return DataSyncReport(created, updated, deactivated, rejected, suspicious)


async def electricity_price(db: AsyncSession, provider_code: str, service_id: str) -> ProviderPrice | None:
    return (await db.execute(select(ProviderPrice).where(
        ProviderPrice.provider_code == provider_code, ProviderPrice.category == "ELECTRICITY",
        ProviderPrice.provider_service_id == service_id, ProviderPrice.active.is_(True)))).scalar_one_or_none()


async def education_price(db: AsyncSession, provider_code: str, service_id: str) -> ProviderPrice | None:
    return (await db.execute(select(ProviderPrice).where(
        ProviderPrice.provider_code == provider_code, ProviderPrice.category == "EDUCATION",
        ProviderPrice.provider_service_id == service_id, ProviderPrice.active.is_(True)))).scalar_one_or_none()


async def tv_price(db: AsyncSession, provider_code: str, service_id: str) -> ProviderPrice | None:
    return (await db.execute(select(ProviderPrice).where(
        ProviderPrice.provider_code == provider_code, ProviderPrice.category == "TV",
        ProviderPrice.provider_service_id == service_id, ProviderPrice.active.is_(True)))).scalar_one_or_none()
