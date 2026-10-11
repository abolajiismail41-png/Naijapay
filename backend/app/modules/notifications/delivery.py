from __future__ import annotations

import asyncio
import smtplib
from datetime import UTC, datetime, timedelta
from email.message import EmailMessage

import httpx
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.modules.notifications.models import Notification, NotificationDelivery
from app.modules.notifications.service import delivery_retry_time


async def _send_email(settings: Settings, to: str, subject: str, body: str) -> str:
    if not settings.smtp_host or not settings.smtp_from_email:
        raise UnconfiguredChannel("email_not_configured")
    msg = EmailMessage()
    msg["Subject"], msg["From"], msg["To"] = subject, settings.smtp_from_email, to
    msg.set_content(body)

    def send() -> None:
        with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=10) as smtp:
            smtp.ehlo()
            if settings.smtp_starttls:
                smtp.starttls()
                smtp.ehlo()
            if settings.smtp_username:
                smtp.login(settings.smtp_username, settings.smtp_password.get_secret_value())
            smtp.send_message(msg)
    await asyncio.to_thread(send)
    return "smtp_accepted"


async def _send_sms(settings: Settings, http: httpx.AsyncClient, to: str, body: str) -> str:
    api_key = settings.termii_api_key.get_secret_value()
    if not api_key or not settings.termii_sender_id:
        raise UnconfiguredChannel("sms_not_configured")
    response = await http.post(f"{settings.termii_base_url.rstrip('/')}/api/sms/send", json={
        "api_key": api_key, "to": to.lstrip("+"), "from": settings.termii_sender_id,
        "sms": body, "type": "plain", "channel": "generic",
    }, timeout=httpx.Timeout(10.0, connect=3.0))
    if response.status_code >= 500 or response.status_code in (408, 429):
        raise RetryableDeliveryError(f"termii_http_{response.status_code}")
    if response.status_code >= 400:
        raise PermanentDeliveryError(f"termii_http_{response.status_code}")
    data = response.json()
    if not isinstance(data, dict) or str(data.get("code", "")).lower() not in ("ok", "200", "0"):
        # Treat undocumented response formats as retryable, never as a confirmed delivery.
        raise RetryableDeliveryError("termii_unexpected_response")
    return str(data.get("message_id") or data.get("messageId") or "termii_accepted")[:120]


class UnconfiguredChannel(Exception):
    pass


class RetryableDeliveryError(Exception):
    pass


class PermanentDeliveryError(Exception):
    pass


async def deliver_due(db: AsyncSession, settings: Settings, http: httpx.AsyncClient, limit: int = 50) -> int:
    now = datetime.now(UTC)
    # Recover jobs claimed by a worker that died after committing SENDING but before recording a result.
    await db.execute(update(NotificationDelivery).where(
        NotificationDelivery.status == "SENDING",
        NotificationDelivery.updated_at < now - timedelta(minutes=5),
    ).values(status="PENDING", next_attempt_at=now))
    await db.commit()
    rows = list((await db.execute(select(NotificationDelivery).where(
        NotificationDelivery.status == "PENDING", NotificationDelivery.next_attempt_at <= now
    ).order_by(NotificationDelivery.created_at).with_for_update(skip_locked=True).limit(limit))).scalars())
    if not rows:
        return 0
    # Claim work before network I/O so another worker cannot send the same delivery concurrently.
    for row in rows:
        row.status = "SENDING"
        row.attempts += 1
    await db.commit()

    for row in rows:
        event = await db.get(Notification, row.notification_id)
        if event is None:
            row.status, row.last_error_code = "DEAD", "notification_missing"
            continue
        try:
            if row.channel == "EMAIL":
                reference = await _send_email(settings, row.destination, event.title, event.body)
            elif row.channel == "SMS":
                reference = await _send_sms(settings, http, row.destination, f"{event.title}: {event.body}")
            else:
                raise UnconfiguredChannel("push_not_configured")
            row.status, row.provider_reference = "SENT", reference
            row.delivered_at, row.last_error_code = datetime.now(UTC), None
        except UnconfiguredChannel as exc:
            row.status, row.last_error_code = "BLOCKED", str(exc)
        except PermanentDeliveryError as exc:
            row.status, row.last_error_code = "DEAD", str(exc)[:80]
        except (RetryableDeliveryError, httpx.HTTPError, TimeoutError, OSError, smtplib.SMTPException) as exc:
            if row.attempts >= settings.notification_max_attempts:
                row.status = "DEAD"
            else:
                row.status, row.next_attempt_at = "PENDING", delivery_retry_time(row.attempts)
            row.last_error_code = type(exc).__name__
        except Exception as exc:  # defensive boundary: transport failures never roll back financial work
            if row.attempts >= settings.notification_max_attempts:
                row.status = "DEAD"
            else:
                row.status, row.next_attempt_at = "PENDING", delivery_retry_time(row.attempts)
            row.last_error_code = type(exc).__name__
    await db.commit()
    return len(rows)
