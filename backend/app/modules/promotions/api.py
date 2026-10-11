from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_db, ok
from app.modules.audit import service as audit
from app.modules.auth.deps import Principal, current_principal, require_permission
from app.modules.auth.rbac import Permission
from app.modules.promotions.models import PromoCampaign, PromoRedemption
from app.modules.promotions.schemas import PromoCreate, PromoRead, PromoRedeemIn, PromoUpdate
from app.modules.promotions.service import redeem_campaign

router = APIRouter(prefix="/api/v1/promotions", tags=["promotions"])
admin = APIRouter(prefix="/api/v1/admin/promotions", tags=["admin-promotions"])


@router.post("/redeem")
async def redeem(body: PromoRedeemIn, principal: Principal = Depends(current_principal),
                 db: AsyncSession = Depends(get_db)) -> dict:
    # The customer can submit only a code, never a reward amount or user ID.
    result = await redeem_campaign(db, principal.user.id, body.code)
    return ok(result, "Promotion redeemed and wallet credited.")


@admin.get("")
async def list_campaigns(_: Principal = Depends(require_permission(Permission.PRICING_MANAGE)),
                         db: AsyncSession = Depends(get_db)) -> dict:
    rows = list((await db.execute(select(PromoCampaign).order_by(PromoCampaign.created_at.desc()).limit(200))).scalars())
    result = []
    for row in rows:
        used = await db.scalar(select(func.count()).select_from(PromoRedemption).where(PromoRedemption.campaign_id == row.id))
        data = PromoRead.model_validate(row).model_dump(mode="json")
        data["redemptions"] = int(used or 0)
        result.append(data)
    return ok(result, "Promotion campaigns loaded.")


@admin.post("", status_code=201)
async def create_campaign(body: PromoCreate, principal: Principal = Depends(require_permission(Permission.PRICING_MANAGE)),
                          db: AsyncSession = Depends(get_db)) -> dict:
    campaign = PromoCampaign(code=body.code.strip().upper(), name=body.name.strip(),
        description=body.description.strip(), reward_kobo=body.reward_kobo,
        minimum_qualifying_purchase_kobo=body.minimum_qualifying_purchase_kobo,
        max_redemptions=body.max_redemptions, starts_at=body.starts_at, ends_at=body.ends_at,
        active=body.active, created_by_user_id=principal.user.id)
    db.add(campaign)
    try:
        await db.flush()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(status_code=409, detail="A campaign with that code already exists.") from None
    audit.record(db, action="promotion.campaign_created", actor_user_id=principal.user.id,
                 resource_type="promotion", resource_id=campaign.code,
                 meta={"reward_kobo": campaign.reward_kobo, "max_redemptions": campaign.max_redemptions})
    await db.commit()
    await db.refresh(campaign)
    return ok(PromoRead.model_validate(campaign), "Promotion campaign created.")


@admin.patch("/{campaign_id}")
async def update_campaign(campaign_id: str, body: PromoUpdate,
                          principal: Principal = Depends(require_permission(Permission.PRICING_MANAGE)),
                          db: AsyncSession = Depends(get_db)) -> dict:
    import uuid
    try:
        cid = uuid.UUID(campaign_id)
    except ValueError:
        raise HTTPException(status_code=404, detail="Promotion campaign not found.") from None
    campaign = (await db.execute(select(PromoCampaign).where(PromoCampaign.id == cid).with_for_update())).scalar_one_or_none()
    if campaign is None:
        raise HTTPException(status_code=404, detail="Promotion campaign not found.")
    changes = body.model_dump(exclude_unset=True)
    changes = {key: value for key, value in changes.items() if value is not None or key == "ends_at"}
    for key, value in changes.items():
        setattr(campaign, key, value)
    if campaign.starts_at and campaign.ends_at and campaign.ends_at <= campaign.starts_at:
        raise HTTPException(status_code=422, detail="ends_at must be after starts_at.")
    audit.record(db, action="promotion.campaign_updated", actor_user_id=principal.user.id,
                 resource_type="promotion", resource_id=campaign.code, meta=changes)
    await db.commit()
    await db.refresh(campaign)
    return ok(PromoRead.model_validate(campaign), "Promotion campaign updated.")

