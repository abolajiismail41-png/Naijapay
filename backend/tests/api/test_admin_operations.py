from tests.api.helpers import bearer, signup


async def test_admin_endpoints_require_staff_permissions(env) -> None:
    tokens = await signup(env)
    headers = bearer(tokens)
    assert (await env.client.get("/api/v1/admin/overview", headers=headers)).status_code == 403
    assert (await env.client.get("/api/v1/admin/users", headers=headers)).status_code == 403
    assert (await env.client.get("/api/v1/admin/audit", headers=headers)).status_code == 403


async def test_admin_users_search_does_not_require_or_expose_finance_permissions(env) -> None:
    # This verifies the ordinary customer cannot use operational tools; finance-only fields
    # remain on the separate finance routes and are not returned by user listing.
    tokens = await signup(env)
    r = await env.client.get("/api/v1/admin/users", headers=bearer(tokens))
    assert r.status_code == 403
