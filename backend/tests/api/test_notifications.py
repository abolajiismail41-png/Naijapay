from tests.api.helpers import bearer, signup


async def test_notification_preferences_and_inbox_are_private(env) -> None:
    tokens = await signup(env)
    headers = bearer(tokens)
    assert (await env.client.get("/api/v1/notifications", headers=headers)).status_code == 200
    prefs = await env.client.get("/api/v1/notifications/preferences", headers=headers)
    assert prefs.status_code == 200
    assert prefs.json()["data"]["in_app_enabled"] is True
    assert prefs.json()["data"]["email_enabled"] is False
    saved = await env.client.patch("/api/v1/notifications/preferences", headers=headers,
                                   json={"email_enabled": True, "email_address": "ada@example.com"})
    assert saved.status_code == 200
    assert saved.json()["data"]["email_enabled"] is True
    assert (await env.client.get("/api/v1/notifications")).status_code == 401


async def test_email_notifications_require_a_destination(env) -> None:
    tokens = await signup(env)
    r = await env.client.patch("/api/v1/notifications/preferences", headers=bearer(tokens),
                               json={"email_enabled": True})
    assert r.status_code == 422
