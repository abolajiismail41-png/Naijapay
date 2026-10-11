from tests.api.helpers import bearer, set_role, signup


async def test_referral_code_can_be_shared_and_attribution_is_recorded(env) -> None:
    referrer = await signup(env, "08031234567")
    headers = bearer(referrer)
    profile = await env.client.get("/api/v1/referrals/me", headers=headers)
    assert profile.status_code == 200, profile.text
    code = profile.json()["data"]["code"]
    assert code.startswith("NJP")

    registered = await env.client.post("/api/v1/auth/register", json={
        "phone": "08031234568", "password": "Str0ng-pass!", "full_name": "Bola User", "referral_code": code,
    })
    assert registered.status_code == 201, registered.text
    assert registered.json()["data"]["access_token"]

    updated = await env.client.get("/api/v1/referrals/me", headers=headers)
    assert updated.json()["data"]["total_invites"] == 1
    assert updated.json()["data"]["pending_invites"] == 1


async def test_promo_redemption_credits_wallet_once(env) -> None:
    admin_tokens = await signup(env, "08031234569")
    await set_role(env, "+2348031234569", "SUPER_ADMIN")
    admin_headers = bearer(admin_tokens)
    campaign = await env.client.post("/api/v1/admin/promotions", headers=admin_headers, json={
        "code": "WELCOME100", "name": "Welcome reward", "description": "Test campaign",
        "reward_kobo": 10000, "max_redemptions": 10, "active": True,
    })
    assert campaign.status_code == 201, campaign.text

    user_tokens = await signup(env, "08031234570")
    headers = bearer(user_tokens)
    redeemed = await env.client.post("/api/v1/promotions/redeem", headers=headers, json={"code": "welcome100"})
    assert redeemed.status_code == 200, redeemed.text
    wallet = await env.client.get("/api/v1/wallet", headers=headers)
    assert wallet.status_code == 200, wallet.text
    assert wallet.json()["data"]["balance_kobo"] == 10000
    replay = await env.client.post("/api/v1/promotions/redeem", headers=headers, json={"code": "WELCOME100"})
    assert replay.status_code == 409
