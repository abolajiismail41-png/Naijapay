import asyncio
from datetime import timedelta

import jwt
from sqlalchemy import text

from app.core.security import encode_token
from tests.api.helpers import NORMALISED, PASSWORD, PHONE, audit_actions, bearer, set_role, signup

A = "/api/v1/auth"


async def test_register_verify_login_and_me(env) -> None:
    tokens = await signup(env)
    me = await env.client.get("/api/v1/users/me", headers=bearer(tokens))
    assert me.status_code == 200 and me.json()["data"]["phone"] == NORMALISED
    assert me.json()["data"]["role"] == "USER" and me.json()["data"]["has_pin"] is False
    r = await env.client.post(f"{A}/login", json={"phone": PHONE, "password": PASSWORD})
    assert r.status_code == 200 and r.json()["data"]["refresh_token"]


async def test_registration_logs_user_in_without_otp_and_phone_remains_unverified(env) -> None:
    r = await env.client.post(f"{A}/register", json={"phone": PHONE, "password": PASSWORD, "full_name": "Ada Obi"})
    assert r.status_code == 201 and r.json()["data"]["access_token"]
    assert await env.redis.get(f"dev:otp:{NORMALISED}") is None
    login = await env.client.post(f"{A}/login", json={"phone": PHONE, "password": PASSWORD})
    assert login.status_code == 200
    me = await env.client.get("/api/v1/users/me", headers=bearer(r.json()["data"]))
    assert me.status_code == 200
    async with env.app.state.session_factory() as s:
        verified_at = (await s.execute(text("SELECT phone_verified_at FROM users WHERE phone=:p"), {"p": NORMALISED})).scalar_one()
    assert verified_at is None


async def test_register_existing_verified_phone_is_indistinguishable_and_sends_no_code(env) -> None:
    await signup(env)
    await env.redis.delete(f"dev:otp:{NORMALISED}")
    r = await env.client.post(f"{A}/register", json={"phone": PHONE, "password": "An0ther-pass!", "full_name": "Eve"})
    assert r.status_code == 409
    assert await env.redis.get(f"dev:otp:{NORMALISED}") is None
    ok = await env.client.post(f"{A}/login", json={"phone": PHONE, "password": PASSWORD})
    assert ok.status_code == 200  # the original password still works


async def test_unknown_user_and_wrong_password_look_identical(env) -> None:
    await signup(env)
    a = await env.client.post(f"{A}/login", json={"phone": PHONE, "password": "wrong-password"})
    b = await env.client.post(f"{A}/login", json={"phone": "08099999999", "password": "wrong-password"})
    assert a.status_code == b.status_code == 401
    assert a.json()["error"]["code"] == b.json()["error"]["code"] == "invalid_credentials"


async def test_account_lockout_after_repeated_failures(env) -> None:
    await signup(env)
    for _ in range(5):
        assert (await env.client.post(f"{A}/login", json={"phone": PHONE, "password": "bad-password"})).status_code == 401
    r = await env.client.post(f"{A}/login", json={"phone": PHONE, "password": PASSWORD})
    assert r.status_code == 429 and r.json()["error"]["code"] == "account_locked"
    assert "auth.login_failed" in await audit_actions(env)


async def test_otp_verification_endpoint_rejects_codes_not_requested(env) -> None:
    await signup(env)
    r = await env.client.post(f"{A}/verify-phone", json={"phone": PHONE, "code": "123456"})
    assert r.status_code == 400


async def test_registration_rate_limit_and_duplicate_account_protection(env) -> None:
    body = {"phone": PHONE, "password": PASSWORD, "full_name": "Ada Obi"}
    codes = [(await env.client.post(f"{A}/register", json=body)).status_code for _ in range(4)]
    assert codes == [201, 409, 409, 429]


async def test_refresh_rotation_and_reuse_detection(env) -> None:
    t1 = await signup(env)
    r = await env.client.post(f"{A}/refresh", json={"refresh_token": t1["refresh_token"]})
    assert r.status_code == 200
    t2 = r.json()["data"]
    assert t2["refresh_token"] != t1["refresh_token"]
    replay = await env.client.post(f"{A}/refresh", json={"refresh_token": t1["refresh_token"]})
    assert replay.status_code == 401
    after = await env.client.post(f"{A}/refresh", json={"refresh_token": t2["refresh_token"]})
    assert after.status_code == 401  # whole family revoked
    assert (await env.client.get("/api/v1/users/me", headers=bearer(t2))).status_code == 401
    assert "auth.refresh_reuse_detected" in await audit_actions(env)


async def test_concurrent_refresh_yields_exactly_one_success(env) -> None:
    t = await signup(env)
    results = await asyncio.gather(*[
        env.client.post(f"{A}/refresh", json={"refresh_token": t["refresh_token"]}) for _ in range(2)])
    assert sorted(r.status_code for r in results) == [200, 401]


async def test_logout_kills_access_token_immediately(env) -> None:
    t = await signup(env)
    assert (await env.client.post(f"{A}/logout", headers=bearer(t))).status_code == 200
    assert (await env.client.get("/api/v1/users/me", headers=bearer(t))).status_code == 401
    assert (await env.client.post(f"{A}/refresh", json={"refresh_token": t["refresh_token"]})).status_code == 401


async def test_sessions_list_and_revoke_other_device(env) -> None:
    t1 = await signup(env)
    t2 = (await env.client.post(f"{A}/login", json={"phone": PHONE, "password": PASSWORD},
                                headers={"X-Device-Label": "Pixel 7"})).json()["data"]
    sessions = (await env.client.get(f"{A}/sessions", headers=bearer(t1))).json()["data"]
    assert len(sessions) == 2 and sum(s["current"] for s in sessions) == 1
    other = next(s for s in sessions if not s["current"])
    assert (await env.client.delete(f"{A}/sessions/{other['id']}", headers=bearer(t1))).status_code == 200
    assert (await env.client.get("/api/v1/users/me", headers=bearer(t2))).status_code == 401
    assert (await env.client.get("/api/v1/users/me", headers=bearer(t1))).status_code == 200


async def test_password_reset_revokes_sessions_and_hides_account_existence(env) -> None:
    t = await signup(env)
    unknown = await env.client.post(f"{A}/password/reset/request", json={"phone": "08099999999"})
    known = await env.client.post(f"{A}/password/reset/request", json={"phone": PHONE})
    assert unknown.status_code == known.status_code == 202 and unknown.json() == known.json()
    code = await env.redis.get(f"dev:otp:{NORMALISED}")
    r = await env.client.post(f"{A}/password/reset/confirm",
                              json={"phone": PHONE, "code": code, "new_password": "N3w-password!"})
    assert r.status_code == 200
    assert (await env.client.get("/api/v1/users/me", headers=bearer(t))).status_code == 401
    assert (await env.client.post(f"{A}/login", json={"phone": PHONE, "password": PASSWORD})).status_code == 401
    assert (await env.client.post(f"{A}/login", json={"phone": PHONE, "password": "N3w-password!"})).status_code == 200


async def test_pin_set_verify_lockout_and_weak_pin(env) -> None:
    t = await signup(env)
    h = bearer(t)
    assert (await env.client.post(f"{A}/pin/set", headers=h, json={"password": "bad", "pin": "4821"})).status_code == 401
    assert (await env.client.post(f"{A}/pin/set", headers=h, json={"password": PASSWORD, "pin": "1234"})).status_code == 422
    assert (await env.client.post(f"{A}/pin/set", headers=h, json={"password": PASSWORD, "pin": "4821"})).status_code == 200
    assert (await env.client.post(f"{A}/pin/set", headers=h, json={"password": PASSWORD, "pin": "5937"})).status_code == 409
    ok = await env.client.post(f"{A}/pin/verify", headers=h, json={"pin": "4821"})
    assert ok.status_code == 200 and ok.json()["data"]["pin_token"]
    for _ in range(5):
        assert (await env.client.post(f"{A}/pin/verify", headers=h, json={"pin": "0000"})).status_code == 400
    locked = await env.client.post(f"{A}/pin/verify", headers=h, json={"pin": "4821"})
    assert locked.status_code == 429 and locked.json()["error"]["code"] == "pin_locked"


async def test_pin_stored_hashed_not_plain(env) -> None:
    t = await signup(env)
    await env.client.post(f"{A}/pin/set", headers=bearer(t), json={"password": PASSWORD, "pin": "4821"})
    async with env.app.state.session_factory() as s:
        row = (await s.execute(text("SELECT pin_hash, password_hash FROM user_credentials"))).one()
    assert row.pin_hash.startswith("$argon2id$") and "4821" not in row.pin_hash
    assert row.password_hash.startswith("$argon2id$")


async def test_unauthenticated_and_forged_tokens_rejected(env) -> None:
    assert (await env.client.get("/api/v1/users/me")).status_code == 401
    assert (await env.client.get("/api/v1/users/me", headers={"Authorization": "Bearer junk"})).status_code == 401
    t = await signup(env)
    claims = jwt.decode(t["access_token"], options={"verify_signature": False})
    forged = jwt.encode(claims, None, algorithm="none")
    assert (await env.client.get("/api/v1/users/me", headers={"Authorization": f"Bearer {forged}"})).status_code == 401
    wrong_key = jwt.encode(claims, "x" * 40, algorithm="HS256")
    assert (await env.client.get("/api/v1/users/me", headers={"Authorization": f"Bearer {wrong_key}"})).status_code == 401
    expired = encode_token("test-jwt-secret", "access", claims["sub"], timedelta(seconds=-5), sid=claims["sid"])
    assert (await env.client.get("/api/v1/users/me", headers={"Authorization": f"Bearer {expired}"})).status_code == 401
    # a refresh token or PIN token must never work as an access token
    pin_tok = encode_token("test-jwt-secret", "pin", claims["sub"], timedelta(minutes=1))
    assert (await env.client.get("/api/v1/users/me", headers={"Authorization": f"Bearer {pin_tok}"})).status_code == 401
    assert (await env.client.get("/api/v1/users/me", headers={"Authorization": f"Bearer {t['refresh_token']}"})).status_code == 401


async def test_rbac_enforced_server_side_and_admin_is_not_finance(env) -> None:
    t = await signup(env)
    url = "/_needs_refund_approve"
    assert (await env.client.get(url, headers=bearer(t))).status_code == 403
    await set_role(env, NORMALISED, "ADMIN")
    assert (await env.client.get(url, headers=bearer(t))).status_code == 403
    await set_role(env, NORMALISED, "FINANCE")
    assert (await env.client.get(url, headers=bearer(t))).status_code == 200  # role change applies instantly
    assert "authz.denied" in await audit_actions(env)


async def test_audit_log_is_append_only(env) -> None:
    await signup(env)
    async with env.app.state.session_factory() as s:
        for stmt in ("UPDATE audit_logs SET action='x'", "DELETE FROM audit_logs", "TRUNCATE audit_logs"):
            try:
                await s.execute(text(stmt))
                raise AssertionError(f"{stmt} should have been blocked")
            except Exception as exc:  # noqa: BLE001
                assert "append-only" in str(exc)
                await s.rollback()


async def test_unknown_fields_and_bad_phone_rejected(env) -> None:
    r = await env.client.post(f"{A}/login", json={"phone": PHONE, "password": "x", "role": "ADMIN"})
    assert r.status_code == 422
    r = await env.client.post(f"{A}/register", json={"phone": "12345", "password": PASSWORD, "full_name": "Ada Obi"})
    assert r.status_code == 422
