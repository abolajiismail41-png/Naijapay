import json
import logging
import re
import uuid
import time

from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.core.errors import error_body
from app.core.logging import request_id_ctx

log = logging.getLogger(__name__)
_REQ_ID_RE = re.compile(r"^[A-Za-z0-9\-_]{8,64}$")

SECURITY_HEADERS = {
    b"x-content-type-options": b"nosniff",
    b"x-frame-options": b"DENY",
    b"referrer-policy": b"no-referrer",
    b"strict-transport-security": b"max-age=63072000; includeSubDomains",
    b"cache-control": b"no-store",
}


class RequestContextMiddleware:
    """Assigns a request id, adds security headers, and caps declared body size."""

    def __init__(self, app: ASGIApp, max_request_bytes: int) -> None:
        self.app = app
        self.max_request_bytes = max_request_bytes

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        headers = dict(scope["headers"])
        supplied = headers.get(b"x-request-id", b"").decode()
        rid = supplied if _REQ_ID_RE.match(supplied) else uuid.uuid4().hex
        token = request_id_ctx.set(rid)
        started_at = time.perf_counter()
        status_code = 500
        logged = False

        async def send_wrapper(message: Message) -> None:
            nonlocal status_code, logged
            if message["type"] == "http.response.start":
                status_code = int(message.get("status", 500))
                out = list(message.get("headers", []))
                out.append((b"x-request-id", rid.encode()))
                present = {k.lower() for k, _ in out}
                out.extend((k, v) for k, v in SECURITY_HEADERS.items() if k not in present)
                message["headers"] = out
            await send(message)
            if message["type"] == "http.response.body" and not message.get("more_body", False) and not logged:
                logged = True
                duration_ms = round((time.perf_counter() - started_at) * 1000, 2)
                logger = log.warning if status_code >= 500 else log.info
                logger("http_request_complete", extra={
                    "method": scope.get("method", "?"),
                    "path": scope.get("path", ""),
                    "status_code": status_code,
                    "duration_ms": duration_ms,
                })

        try:
            length = int(headers.get(b"content-length", b"0") or 0)
            if length > self.max_request_bytes:
                body = json.dumps(error_body("payload_too_large", "Request is too large.")).encode()
                await send_wrapper({"type": "http.response.start", "status": 413,
                                    "headers": [(b"content-type", b"application/json")]})
                await send_wrapper({"type": "http.response.body", "body": body})
                return
            started = False

            async def tracked_send(message: Message) -> None:
                nonlocal started
                started = started or message["type"] == "http.response.start"
                await send_wrapper(message)

            try:
                await self.app(scope, receive, tracked_send)
            except Exception:
                # Handled here (not by Starlette's outer handler) so the response
                # still carries the request id and security headers.
                log.exception("unhandled_error")
                if not started:
                    body = json.dumps(error_body("internal_error", "Something went wrong on our side.")).encode()
                    await send_wrapper({"type": "http.response.start", "status": 500,
                                        "headers": [(b"content-type", b"application/json")]})
                    await send_wrapper({"type": "http.response.body", "body": body})
        finally:
            request_id_ctx.reset(token)
