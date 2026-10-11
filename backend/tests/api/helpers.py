from typing import Any

from sqlalchemy import text

from tests.conftest import Env

PHONE = "08031234567"
NORMALISED = "+2348031234567"
PASSWORD = "Str0ng-pass!"


async def signup(env: Env, phone: str = PHONE, password: str = PASSWORD) -> dict[str, Any]:
    r = await env.client.post("/api/v1/auth/register",
                              json={"phone": phone, "password": password, "full_name": "Ada Obi"})
    assert r.status_code == 201, r.text
    tokens = r.json()["data"]
    assert tokens.get("access_token") and tokens.get("refresh_token")
    return tokens


def bearer(tokens: dict[str, Any]) -> dict[str, str]:
    return {"Authorization": f"Bearer {tokens['access_token']}"}


async def set_role(env: Env, phone: str, role: str) -> None:
    factory = env.app.state.session_factory  # type: ignore[attr-defined]
    async with factory() as s:
        await s.execute(text("UPDATE users SET role=:r WHERE phone=:p"), {"r": role, "p": phone})
        await s.commit()


async def audit_actions(env: Env) -> list[str]:
    factory = env.app.state.session_factory  # type: ignore[attr-defined]
    async with factory() as s:
        return list((await s.execute(text("SELECT action FROM audit_logs ORDER BY created_at"))).scalars())
