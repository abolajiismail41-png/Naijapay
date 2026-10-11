from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.audit import service as audit
from app.modules.electricity.models import ElectricityDisco
from app.modules.providers.base import BillProvider
from app.modules.providers.models import ProviderPrice


@dataclass(frozen=True)
class ElectricitySyncReport:
    discos_created: int
    prices_created: int
    prices_updated: int
    rejected: int


async def sync_electricity(db: AsyncSession, provider: BillProvider, provider_code: str = "inlomax", *,
                           actor_id: object = None) -> ElectricitySyncReport:
    """Best-effort discovery. New discos arrive UNLISTED; nothing is ever deactivated automatically, and an
    admin can correct the provider mapping by hand (the provider response shape is not fully verified)."""
    entries = await provider.fetch_electricity()
    valid = [e for e in entries if e.disco_code and e.meter_type in ("PREPAID", "POSTPAID") and 0 <= e.discount_bps <= 2000]
    now, d_new, p_new, p_upd = datetime.now(UTC), 0, 0, 0
    for e in valid:
        disco = (await db.execute(select(ElectricityDisco).where(
            ElectricityDisco.provider_code == provider_code, ElectricityDisco.code == e.disco_code))).scalar_one_or_none()
        if disco is None:
            disco = ElectricityDisco(provider_code=provider_code, code=e.disco_code, name=e.name,
                                     provider_disco_code=e.provider_disco_code, listed=False, active=True)
            db.add(disco)
            audit.record(db, action="electricity_disco.discovered", actor_user_id=actor_id, resource_type="electricity_disco",
                         resource_id=e.disco_code, after={"name": e.name})
            d_new += 1
        attr = "prepaid_service_id" if e.meter_type == "PREPAID" else "postpaid_service_id"
        if getattr(disco, attr) != e.service_id:
            if getattr(disco, attr):
                audit.record(db, action="electricity_disco.service_id_changed", actor_user_id=actor_id, resource_type="electricity_disco",
                             resource_id=e.disco_code, before={attr: getattr(disco, attr)}, after={attr: e.service_id})
            setattr(disco, attr, e.service_id)
        price = (await db.execute(select(ProviderPrice).where(
            ProviderPrice.provider_code == provider_code, ProviderPrice.category == "ELECTRICITY",
            ProviderPrice.provider_service_id == e.service_id))).scalar_one_or_none()
        if price is None:
            db.add(ProviderPrice(provider_code=provider_code, category="ELECTRICITY", scope_key=e.service_id,
                                 provider_service_id=e.service_id, kind="DISCOUNT_BPS", value=e.discount_bps,
                                 source="SYNCED", synced_at=now, active=True))
            p_new += 1
        elif price.source != "MANUAL":
            if price.value != e.discount_bps:
                audit.record(db, action="provider_price.changed", actor_user_id=actor_id, resource_type="provider_price",
                             resource_id=f"ELECTRICITY:{e.service_id}", before={"value": price.value}, after={"value": e.discount_bps})
                price.value, p_upd = e.discount_bps, p_upd + 1
            price.source, price.synced_at, price.active = "SYNCED", now, True
        await db.flush()
    await db.commit()
    return ElectricitySyncReport(d_new, p_new, p_upd, len(entries) - len(valid))
