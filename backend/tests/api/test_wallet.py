import asyncio
import uuid

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError, IntegrityError

from app.core.money import Money
from app.modules.ledger import interface as ledger
from app.modules.ledger.interface import IdempotencyConflictError, SystemAccount
from app.modules.wallet.errors import AlreadyReversedError, InsufficientFundsError
from app.modules.wallet.service import WalletService
from tests.api.helpers import bearer, signup

NGN = lambda n: Money.from_naira(n)  # noqa: E731


async def uid(env, tokens) -> uuid.UUID:
    r = await env.client.get("/api/v1/users/me", headers=bearer(tokens))
    return uuid.UUID(r.json()["data"]["id"])


async def fund(env, user_id, amount: Money, ref: str):
    async with env.app.state.session_factory() as s:
        m = await WalletService(s).credit(user_id, amount, reference=ref, kind="test.funding",
                                          source=SystemAccount.PROCESSOR_CLEARING, description="Test funding")
        await s.commit()
        return m


async def debit(env, user_id, amount: Money, ref: str):
    """Returns the Movement, or None if rejected for insufficient funds (like a real caller would)."""
    async with env.app.state.session_factory() as s:
        try:
            m = await WalletService(s).debit(user_id, amount, reference=ref, kind="test.purchase",
                                             destination=SystemAccount.PROVIDER_CLEARING)
            await s.commit()
            return m
        except InsufficientFundsError:
            await s.rollback()
            return None


async def balance(env, user_id) -> int:
    async with env.app.state.session_factory() as s:
        return (await WalletService(s).get_or_create(user_id)).balance_kobo


async def test_wallet_is_created_lazily_and_starts_empty(env) -> None:
    t = await signup(env)
    r = await env.client.get("/api/v1/wallet", headers=bearer(t))
    assert r.status_code == 200
    d = r.json()["data"]
    assert d["balance_kobo"] == 0 and d["balance"] == "0.00" and d["currency"] == "NGN"
    assert (await env.client.get("/api/v1/wallet")).status_code == 401


async def test_credit_then_debit_and_api_shows_exact_amounts(env) -> None:
    t = await signup(env)
    u = await uid(env, t)
    await fund(env, u, NGN("5000.50"), "fund:1")
    assert (await debit(env, u, NGN(1200), "buy:1")).balance == NGN("3800.50")
    d = (await env.client.get("/api/v1/wallet", headers=bearer(t))).json()["data"]
    assert d["balance_kobo"] == 380050 and d["balance"] == "3800.50"
    items = (await env.client.get("/api/v1/wallet/entries", headers=bearer(t))).json()["data"]["items"]
    assert [i["type"] for i in items] == ["out", "in"] and items[0]["amount"] == "1200.00"


async def test_insufficient_funds_changes_nothing(env) -> None:
    u = await uid(env, await signup(env))
    await fund(env, u, NGN(1000), "fund:1")
    assert await debit(env, u, NGN("1000.01"), "buy:1") is None
    assert await balance(env, u) == 100000
    async with env.app.state.session_factory() as s:
        assert await ledger.get_journal_by_reference(s, "buy:1") is None


async def test_credit_is_idempotent_and_conflicting_reuse_is_rejected(env) -> None:
    u = await uid(env, await signup(env))
    a = await fund(env, u, NGN(5000), "fund:dup")
    b = await fund(env, u, NGN(5000), "fund:dup")
    assert a.created and not b.created and a.journal_id == b.journal_id
    assert await balance(env, u) == 500000
    with pytest.raises(IdempotencyConflictError):
        await fund(env, u, NGN(6000), "fund:dup")


async def test_debit_replay_succeeds_after_balance_dropped(env) -> None:
    u = await uid(env, await signup(env))
    await fund(env, u, NGN(5000), "fund:1")
    first = await debit(env, u, NGN(3000), "buy:1")
    replay = await debit(env, u, NGN(3000), "buy:1")  # balance is now 2000 < 3000
    assert first.created and replay is not None and not replay.created
    assert await balance(env, u) == 200000


async def test_two_simultaneous_spends_of_the_same_5000_only_one_wins(env) -> None:
    u = await uid(env, await signup(env))
    await fund(env, u, NGN(5000), "fund:1")
    results = await asyncio.gather(debit(env, u, NGN(5000), "buy:a"), debit(env, u, NGN(5000), "buy:b"))
    assert sorted(r is not None for r in results) == [False, True]
    assert await balance(env, u) == 0


async def test_many_concurrent_debits_never_overspend(env) -> None:
    u = await uid(env, await signup(env))
    await fund(env, u, NGN(5000), "fund:1")
    results = await asyncio.gather(*[debit(env, u, NGN(1000), f"buy:{i}") for i in range(12)])
    assert sum(r is not None for r in results) == 5
    assert await balance(env, u) == 0
    async with env.app.state.session_factory() as s:
        assert (await WalletService(s).verify_integrity(u)).ok


async def test_concurrent_duplicate_credits_apply_once(env) -> None:
    u = await uid(env, await signup(env))
    results = await asyncio.gather(*[fund(env, u, NGN(2500), "fund:same") for _ in range(10)])
    assert sum(r.created for r in results) == 1
    assert await balance(env, u) == 250000


async def test_concurrent_first_access_creates_one_wallet(env) -> None:
    u = await uid(env, await signup(env))

    async def touch() -> uuid.UUID:
        async with env.app.state.session_factory() as s:
            w = await WalletService(s).get_or_create(u)
            await s.commit()
            return w.id

    ids = await asyncio.gather(*[touch() for _ in range(8)])
    assert len(set(ids)) == 1


async def test_reversal_rules(env) -> None:
    u = await uid(env, await signup(env))
    await fund(env, u, NGN(5000), "fund:1")
    await debit(env, u, NGN(2000), "buy:1")

    async def reverse(orig: str, ref: str):
        async with env.app.state.session_factory() as s:
            m = await WalletService(s).reverse(orig, reference=ref, reason="provider failed")
            await s.commit()
            return m

    m = await reverse("buy:1", "rev:buy:1")
    assert m.created and m.balance == NGN(5000)
    assert not (await reverse("buy:1", "rev:buy:1")).created          # same ref: replay
    with pytest.raises(AlreadyReversedError):
        await reverse("buy:1", "rev:buy:1:again")                      # different ref: refused
    await debit(env, u, NGN(5000), "buy:2")                            # spend everything
    with pytest.raises(InsufficientFundsError):
        await reverse("fund:1", "rev:fund:1")                          # cannot claw back spent money
    assert await balance(env, u) == 0


async def test_ledger_stays_balanced_and_wallet_matches_ledger(env) -> None:
    u = await uid(env, await signup(env))
    await fund(env, u, NGN(9000), "fund:1")
    for i in range(4):
        await debit(env, u, NGN(1500), f"buy:{i}")
    async with env.app.state.session_factory() as s:
        assert await ledger.trial_balance_diff(s) == 0
        report = await WalletService(s).verify_integrity(u)
        assert report.ok and report.cached_kobo == 300000


async def test_integrity_check_detects_tampering(env) -> None:
    u = await uid(env, await signup(env))
    await fund(env, u, NGN(1000), "fund:1")
    async with env.app.state.session_factory() as s:
        await s.execute(text("UPDATE wallets SET balance_kobo = balance_kobo + 1"))
        await s.commit()
    async with env.app.state.session_factory() as s:
        assert not (await WalletService(s).verify_integrity(u)).ok


async def test_database_refuses_unbalanced_journals_mutation_and_negative_balances(env) -> None:
    u = await uid(env, await signup(env))
    await fund(env, u, NGN(1000), "fund:1")
    factory = env.app.state.session_factory
    async with factory() as s:
        acct = await ledger.system_account_id(s, SystemAccount.REVENUE)
        jid = uuid.uuid4()
        await s.execute(text("INSERT INTO ledger_journals (id, reference, kind, request_hash) "
                             "VALUES (:i, 'raw:bad', 'raw', 'x')"), {"i": jid})
        await s.execute(text("INSERT INTO ledger_entries (id, journal_id, account_id, direction, amount_kobo) "
                             "VALUES (gen_random_uuid(), :j, :a, 'D', 100)"), {"j": jid, "a": acct})
        with pytest.raises(DBAPIError, match="unbalanced"):
            await s.commit()
    for stmt in ("UPDATE ledger_entries SET amount_kobo = 1", "DELETE FROM ledger_journals",
                 "TRUNCATE ledger_entries"):
        async with factory() as s:
            with pytest.raises(DBAPIError, match="append-only"):
                await s.execute(text(stmt))
    async with factory() as s:
        with pytest.raises(IntegrityError):
            await s.execute(text("UPDATE wallets SET balance_kobo = -1"))


async def test_entries_pagination_and_user_isolation(env) -> None:
    ta = await signup(env)
    tb = await signup(env, phone="08087654321")
    ua, ub = await uid(env, ta), await uid(env, tb)
    for i in range(5):
        await fund(env, ua, NGN(100 + i), f"fund:a:{i}")
    await fund(env, ub, NGN(777), "fund:b:0")
    seen, cursor = [], None
    for _ in range(5):
        url = "/api/v1/wallet/entries?limit=2" + (f"&cursor={cursor}" if cursor else "")
        data = (await env.client.get(url, headers=bearer(ta))).json()["data"]
        seen += [i["amount_kobo"] for i in data["items"]]
        cursor = data["next_cursor"]
        if not cursor:
            break
    assert seen == [10400, 10300, 10200, 10100, 10000]  # newest first, no gaps or repeats
    b_items = (await env.client.get("/api/v1/wallet/entries", headers=bearer(tb))).json()["data"]["items"]
    assert [i["amount_kobo"] for i in b_items] == [77700]
    assert (await env.client.get("/api/v1/wallet/entries?limit=0", headers=bearer(ta))).status_code == 422
