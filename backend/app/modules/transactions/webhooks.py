import hashlib
import hmac
import json
import logging
from typing import Any

from fastapi import APIRouter, Depends, Request
from redis.asyncio import Redis
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import ratelimit
from app.core.config import Settings
from app.core.deps import client_ip, get_app_settings, get_db, get_redis, ok
from app.core.errors import AppError, NotFoundError
from app.core.ids import uuid7
from app.modules.payments.models import WebhookEvent

log = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v1/webhooks", tags=["webhooks"])


class BadWebhookError(AppError):
    status_code, code, user_message = 400, "bad_webhook", "Invalid webhook payload."


@router.post("/inlomax/{token}")
async def inlomax_webhook(token: str, request: Request, db: AsyncSession = Depends(get_db),
                          redis: Redis = Depends(get_redis), settings: Settings = Depends(get_app_settings)) -> dict[str, Any]:
    """Inlomax documents no webhook signature, so the URL carries a secret token and the body is only a hint:
    the worker re-checks the real status with the provider API before changing anything."""
    secret = settings.inlomax_webhook_token.get_secret_value()
    if not secret or not hmac.compare_digest(token, secret):
        log.warning("inlomax_webhook_bad_token", extra={"ip": client_ip(request)})
        raise NotFoundError("Not found.")  # indistinguishable from a missing route
    await ratelimit.hit(redis, f"rl:wh:inl:{client_ip(request)}", 600, 60)
    raw = await request.body()
    try:
        payload = json.loads(raw)
        data = payload["data"]
        ref = str(data["reference"])[:80]
        status = str(data.get("status") or payload.get("status") or "")[:20]
        assert isinstance(data, dict) and ref
    except (ValueError, KeyError, AssertionError, TypeError):
        raise BadWebhookError() from None
    key = f"{ref}:{status}"[:120]
    event_id = (await db.execute(
        insert(WebhookEvent).values(id=uuid7(), source="inlomax", event_key=key, event_type="transaction.status",
                                    reference=ref, payload=payload)
        .on_conflict_do_nothing(constraint="uq_webhook_events_source_event_key").returning(WebhookEvent.id))
    ).scalar_one_or_none()
    if event_id is None:
        existing = (await db.execute(select(WebhookEvent).where(
            WebhookEvent.source == "inlomax", WebhookEvent.event_key == key))).scalar_one()
        if existing.status in ("PROCESSED", "IGNORED"):
            await db.commit()
            return ok(message="duplicate")
        event_id = existing.id
    await db.commit()
    try:
        request.app.state.dispatcher.enqueue_provider_webhook(event_id)
    except Exception:  # noqa: BLE001  the sweeper will pick it up
        log.exception("provider_webhook_enqueue_failed")
    return ok(message="received")
