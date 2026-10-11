import asyncio
import json

from app.core.middleware import RequestContextMiddleware


def test_middleware_adds_request_id_security_headers_and_logs_completion(caplog):
    messages = []

    async def app(scope, receive, send):
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b'{"ok":true}', "more_body": False})

    middleware = RequestContextMiddleware(app, max_request_bytes=1024)
    scope = {
        "type": "http",
        "method": "GET",
        "path": "/health/ready",
        "headers": [(b"x-request-id", b"test-request-123")],
    }

    async def receive():
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(message):
        messages.append(message)

    caplog.set_level("INFO", logger="app.core.middleware")
    asyncio.run(middleware(scope, receive, send))

    response_start = next(m for m in messages if m["type"] == "http.response.start")
    headers = dict(response_start["headers"])
    assert headers[b"x-request-id"] == b"test-request-123"
    assert headers[b"x-content-type-options"] == b"nosniff"
    assert any("http_request_complete" in r.message for r in caplog.records)
    record = next(r for r in caplog.records if r.message == "http_request_complete")
    assert record.status_code == 200
    assert record.method == "GET"
    assert record.path == "/health/ready"
    assert record.duration_ms >= 0


def test_middleware_rejects_declared_oversized_body():
    messages = []

    async def app(scope, receive, send):
        raise AssertionError("oversized request must not reach the app")

    middleware = RequestContextMiddleware(app, max_request_bytes=4)
    scope = {"type": "http", "method": "POST", "path": "/test", "headers": [(b"content-length", b"5")]}

    async def receive():
        return {"type": "http.request", "body": b"12345", "more_body": False}

    async def send(message):
        messages.append(message)

    asyncio.run(middleware(scope, receive, send))
    response_start = next(m for m in messages if m["type"] == "http.response.start")
    response_body = next(m for m in messages if m["type"] == "http.response.body")
    assert response_start["status"] == 413
    assert json.loads(response_body["body"])["error"]["code"] == "payload_too_large"
