import hashlib
import json
import uuid
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Any

from sqlalchemy import case, func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.ids import uuid7
from app.core.money import Money
from app.modules.ledger.errors import IdempotencyConflictError, UnbalancedJournalError
from app.modules.ledger.models import LedgerEntry, LedgerJournal


class Direction(StrEnum):
    DEBIT = "D"
    CREDIT = "C"

    @property
    def opposite(self) -> "Direction":
        return Direction.CREDIT if self is Direction.DEBIT else Direction.DEBIT


@dataclass(frozen=True)
class EntryLine:
    account_id: uuid.UUID
    direction: Direction
    amount: Money


@dataclass(frozen=True)
class PostedJournal:
    id: uuid.UUID
    reference: str
    created: bool  # False means this was an idempotent replay and nothing new was written


@dataclass(frozen=True)
class EntryView:
    id: uuid.UUID
    direction: Direction
    amount: Money
    kind: str
    description: str
    created_at: datetime


def validate_lines(lines: list[EntryLine]) -> None:
    if len(lines) < 2 or any(not ln.amount.is_positive() for ln in lines):
        raise UnbalancedJournalError()
    debits = sum(ln.amount.kobo for ln in lines if ln.direction is Direction.DEBIT)
    credits = sum(ln.amount.kobo for ln in lines if ln.direction is Direction.CREDIT)
    if debits != credits:
        raise UnbalancedJournalError(debits=debits, credits=credits)


def hash_request(kind: str, lines: list[EntryLine]) -> str:
    canon = sorted((str(ln.account_id), ln.direction.value, ln.amount.kobo) for ln in lines)
    return hashlib.sha256(json.dumps([kind, canon]).encode()).hexdigest()


async def get_journal_by_reference(db: AsyncSession, reference: str) -> LedgerJournal | None:
    return (await db.execute(select(LedgerJournal).where(LedgerJournal.reference == reference))
            ).scalar_one_or_none()


async def post_journal(
    db: AsyncSession, *, reference: str, kind: str, lines: list[EntryLine], description: str = "",
    meta: dict[str, Any] | None = None, reverses: uuid.UUID | None = None,
) -> PostedJournal:
    """Write one balanced journal. Same reference + same payload is a safe replay; same reference
    with a different payload is rejected. Does not commit."""
    validate_lines(lines)
    req_hash = hash_request(kind, lines)
    new_id = uuid7()
    inserted = (await db.execute(
        insert(LedgerJournal)
        .values(id=new_id, reference=reference, kind=kind, request_hash=req_hash,
                description=description[:200], reverses_journal_id=reverses, meta=meta)
        .on_conflict_do_nothing(index_elements=["reference"]).returning(LedgerJournal.id))
    ).scalar_one_or_none()
    if inserted is None:
        existing = await get_journal_by_reference(db, reference)
        assert existing is not None
        if existing.request_hash != req_hash:
            raise IdempotencyConflictError(reference=reference)
        return PostedJournal(existing.id, reference, created=False)
    db.add_all([LedgerEntry(journal_id=new_id, account_id=ln.account_id, direction=ln.direction.value,
                            amount_kobo=ln.amount.kobo) for ln in lines])
    await db.flush()
    return PostedJournal(new_id, reference, created=True)


async def journal_lines(db: AsyncSession, journal_id: uuid.UUID) -> list[EntryLine]:
    rows = (await db.execute(select(LedgerEntry).where(LedgerEntry.journal_id == journal_id))).scalars()
    return [EntryLine(r.account_id, Direction(r.direction), Money(r.amount_kobo)) for r in rows]


async def find_reversal(db: AsyncSession, journal_id: uuid.UUID) -> LedgerJournal | None:
    return (await db.execute(select(LedgerJournal).where(LedgerJournal.reverses_journal_id == journal_id))
            ).scalar_one_or_none()


async def account_net_credit(db: AsyncSession, account_id: uuid.UUID) -> int:
    signed = case((LedgerEntry.direction == "C", LedgerEntry.amount_kobo), else_=-LedgerEntry.amount_kobo)
    return int((await db.execute(
        select(func.coalesce(func.sum(signed), 0)).where(LedgerEntry.account_id == account_id))).scalar_one())


async def trial_balance_diff(db: AsyncSession) -> int:
    """Total debits minus total credits across the whole ledger. Must always be 0."""
    signed = case((LedgerEntry.direction == "D", LedgerEntry.amount_kobo), else_=-LedgerEntry.amount_kobo)
    return int((await db.execute(select(func.coalesce(func.sum(signed), 0)))).scalar_one())


async def entries_for_account(db: AsyncSession, account_id: uuid.UUID, limit: int,
                              before_id: uuid.UUID | None = None) -> list[EntryView]:
    """Keyset pagination on the time-ordered UUIDv7 id: stable and index-friendly."""
    q = (select(LedgerEntry, LedgerJournal.kind, LedgerJournal.description)
         .join(LedgerJournal, LedgerJournal.id == LedgerEntry.journal_id)
         .where(LedgerEntry.account_id == account_id))
    if before_id is not None:
        q = q.where(LedgerEntry.id < before_id)
    rows = (await db.execute(q.order_by(LedgerEntry.id.desc()).limit(limit))).all()
    return [EntryView(e.id, Direction(e.direction), Money(e.amount_kobo), kind, desc, e.created_at)
            for e, kind, desc in rows]


async def owned_accounts_net_credit(db: AsyncSession) -> int:
    """Total owed to customers: net credit across every user-owned (wallet) account."""
    from app.modules.ledger.models import LedgerAccount
    signed = case((LedgerEntry.direction == "C", LedgerEntry.amount_kobo), else_=-LedgerEntry.amount_kobo)
    q = (select(func.coalesce(func.sum(signed), 0)).join(LedgerAccount, LedgerAccount.id == LedgerEntry.account_id)
         .where(LedgerAccount.owner_user_id.is_not(None)))
    return int((await db.execute(q)).scalar_one())
