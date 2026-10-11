import hashlib
import json
import logging
from typing import Any

from fastapi import APIRouter, Depends, Request
from redis.asyncio import Redis
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import ratelimit
from app.core.deps import client_ip, get_db, get_redis, ok
from app.core.errors import AppError, UnauthorizedError
from app.core.ids import uuid7
from app.modules.payments.models import WebhookEvent

log = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v1/webhooks", tags=["webhooks"])


class BadWebhookError(AppError):
    status_code, code, user_message = 400, "bad_webhook", "Invalid webhook payload."


@router.post("/paystack")
async def paystack_webhook(request: Request, db: AsyncSession = Depends(get_db),
                           redis: Redis = Depends(get_redis)) -> dict[str, Any]:
    """Authenticate, store, enqueue, acknowledge. Money is only moved later, by the worker, after
    re-verifying the transaction with the processor: nothing in this body is trusted."""
    await ratelimit.hit(redis, f"rl:wh:{client_ip(request)}", 600, 60)
    raw = await request.body()
    if not request.app.state.payment_processor.verify_webhook_signature(
            raw, request.headers.get("x-paystack-signature", "")):
        log.warning("webhook_bad_signature", extra={"ip": client_ip(request)})
        raise UnauthorizedError("Invalid signature.")
    try:
        payload = json.loads(raw)
        event_type = str(payload["event"])[:40]
        data = payload.get("data") or {}
        assert isinstance(data, dict)
    except (ValueError, KeyError, AssertionError, TypeError):
        raise BadWebhookError() from None
    ref = data.get("reference")
    key = f"{event_type}:{data.get('id') or hashlib.sha256(raw).hexdigest()}"[:120]
    new_id = uuid7()
    inserted = (await db.execute(
        insert(WebhookEvent).values(id=new_id, source="paystack", event_key=key, event_type=event_type,
                                    reference=ref if isinstance(ref, str) else None, payload=payload)
        .on_conflict_do_nothing(constraint="uq_webhook_events_source_event_key")
        .returning(WebhookEvent.id))).scalar_one_or_none()
    event_id = inserted
    if event_id is None:  # duplicate delivery: only re-enqueue if we never finished it
        existing = (await db.execute(select(WebhookEvent).where(
            WebhookEvent.source == "paystack", WebhookEvent.event_key == key))).scalar_one()
        if existing.status in ("PROCESSED", "IGNORED"):
            await db.commit()
            return ok(message="duplicate")
        event_id = existing.id
    await db.commit()
    try:
        request.app.state.dispatcher.enqueue_webhook(event_id)
    except Exception:  # noqa: BLE001  the sweeper will pick the stored event up
        log.exception("webhook_enqueue_failed", extra={"event_id": str(event_id)})
    return ok(message="received")
