import pytest
from fastapi import APIRouter
from httpx import ASGITransport, AsyncClient

from app.core.config import Settings
from app.core.errors import ConflictError
from app.main import create_app


@pytest.fixture
def app():
    s = Settings(_env_file=None, environment="test", database_url="postgresql+asyncpg://u:p@localhost/x",
                 redis_url="redis://localhost:6379/0", jwt_secret="a", encryption_key="b",
                 webhook_secret="c", max_request_bytes=2048)
    application = create_app(s)
    r = APIRouter()

    @r.get("/_boom")
    async def boom() -> None:
        raise RuntimeError("secret internals")

    @r.get("/_conflict")
    async def conflict() -> None:
        raise ConflictError()

    @r.post("/_typed")
    async def typed(n: int) -> dict[str, int]:
        return {"n": n}

    application.include_router(r)
    return application


@pytest.fixture
async def client(app):
    async with AsyncClient(transport=ASGITransport(app=app, raise_app_exceptions=False),
                           base_url="http://t") as c:
        yield c


async def test_live_ok_with_request_id_and_security_headers(client) -> None:
    r = await client.get("/health/live")
    assert r.status_code == 200
    assert r.headers["x-request-id"]
    assert r.headers["x-content-type-options"] == "nosniff"


async def test_valid_request_id_is_propagated(client) -> None:
    r = await client.get("/health/live", headers={"X-Request-ID": "abcd1234-req"})
    assert r.headers["x-request-id"] == "abcd1234-req"


async def test_invalid_request_id_is_replaced(client) -> None:
    r = await client.get("/health/live", headers={"X-Request-ID": "bad id\t!"})
    assert r.headers["x-request-id"] != "bad id\t!"


async def test_unhandled_error_leaks_nothing(client) -> None:
    r = await client.get("/_boom")
    body = r.json()
    assert r.status_code == 500 and body["success"] is False and r.headers["x-request-id"] == body["error"]["request_id"]
    assert "secret internals" not in r.text and body["error"]["request_id"]


async def test_domain_error_envelope(client) -> None:
    r = await client.get("/_conflict")
    assert r.status_code == 409 and r.json()["error"]["code"] == "conflict"


async def test_validation_error_envelope(client) -> None:
    r = await client.post("/_typed?n=abc")
    assert r.status_code == 422 and r.json()["error"]["code"] == "validation_error"


async def test_oversized_body_rejected(client) -> None:
    r = await client.post("/_typed?n=1", content=b"x" * 5000, headers={"Content-Type": "text/plain"})
    assert r.status_code == 413


async def test_ready_reports_degraded_without_leaking(client) -> None:
    r = await client.get("/health/ready")
    assert r.status_code == 503
    assert set(r.json()) == {"status", "database", "redis"}
