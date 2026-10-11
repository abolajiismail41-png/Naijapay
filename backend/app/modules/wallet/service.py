import uuid
from dataclasses import dataclass
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm.attributes import set_committed_value

from app.core.ids import uuid7
from app.core.money import Money
from app.modules.ledger import interface as ledger
from app.modules.ledger.interface import Direction, EntryLine, SystemAccount
from app.modules.wallet.errors import (
    AlreadyReversedError, InsufficientFundsError, ReversalTargetError, WalletInactiveError,
)
from app.modules.wallet.models import Wallet


@dataclass(frozen=True)
class Movement:
    wallet_id: uuid.UUID
    journal_id: uuid.UUID
    reference: str
    created: bool  # False = idempotent replay, balance was not touched again
    amount: Money
    balance: Money


@dataclass(frozen=True)
class IntegrityReport:
    cached_kobo: int
    ledger_kobo: int

    @property
    def ok(self) -> bool:
        return self.cached_kobo == self.ledger_kobo


class WalletService:
    """Moves money in and out of a wallet. Never commits: callers own the transaction, so a
    purchase can debit the wallet and create its transaction record atomically."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def get_or_create(self, user_id: uuid.UUID) -> Wallet:
        q = select(Wallet).where(Wallet.user_id == user_id)
        wallet = (await self.db.execute(q)).scalar_one_or_none()
        if wallet:
            return wallet
        account_id = await ledger.ensure_wallet_account(self.db, user_id)
        await self.db.execute(
            insert(Wallet).values(id=uuid7(), user_id=user_id, ledger_account_id=account_id,
                                  balance_kobo=0, version=0, status="ACTIVE")
            .on_conflict_do_nothing(index_elements=["user_id"]))
        return (await self.db.execute(q)).scalar_one()

    async def _locked(self, user_id: uuid.UUID) -> Wallet:
        wallet = await self.get_or_create(user_id)
        q = select(Wallet).where(Wallet.id == wallet.id).with_for_update()
        locked = (await self.db.execute(q.execution_options(populate_existing=True))).scalar_one()
        if locked.status != "ACTIVE":
            raise WalletInactiveError()
        return locked

    async def _apply_balance(self, wallet: Wallet, delta_kobo: int) -> None:
        """Atomic guarded update; the CHECK constraint is the last line of defence."""
        new = (await self.db.execute(
            update(Wallet)
            .where(Wallet.id == wallet.id, Wallet.balance_kobo + delta_kobo >= 0)
            .values(balance_kobo=Wallet.balance_kobo + delta_kobo, version=Wallet.version + 1)
            .returning(Wallet.balance_kobo))).scalar_one_or_none()
        if new is None:
            raise InsufficientFundsError()
        set_committed_value(wallet, "balance_kobo", new)

    @staticmethod
    def _check_amount(amount: Money) -> None:
        if not amount.is_positive():
            raise ValueError("amount must be positive")

    async def credit(self, user_id: uuid.UUID, amount: Money, *, reference: str, kind: str,
                     source: SystemAccount, description: str = "", fee: Money | None = None,
                     meta: dict[str, Any] | None = None) -> Movement:
        """Credit the wallet by `amount`. With a fee, the payer's total (amount + fee) is debited from
        `source`, the wallet gets `amount`, and the fee is booked to platform fee income."""
        self._check_amount(amount)
        wallet = await self._locked(user_id)
        fee = fee or Money(0)
        lines = [EntryLine(await ledger.system_account_id(self.db, source), Direction.DEBIT, amount + fee),
                 EntryLine(wallet.ledger_account_id, Direction.CREDIT, amount)]
        if fee.is_positive():
            lines.append(EntryLine(await ledger.system_account_id(self.db, SystemAccount.FEES),
                                   Direction.CREDIT, fee))
        posted = await ledger.post_journal(self.db, reference=reference, kind=kind, lines=lines,
                                           description=description, meta=meta)
        if posted.created:
            await self._apply_balance(wallet, amount.kobo)
        return Movement(wallet.id, posted.id, reference, posted.created, amount, Money(wallet.balance_kobo))

    async def debit(self, user_id: uuid.UUID, amount: Money, *, reference: str, kind: str,
                    destination: SystemAccount, description: str = "",
                    meta: dict[str, Any] | None = None) -> Movement:
        self._check_amount(amount)
        wallet = await self._locked(user_id)
        # A replay of an already-applied debit must succeed even though the balance is now lower.
        is_replay = await ledger.get_journal_by_reference(self.db, reference) is not None
        if not is_replay and wallet.balance_kobo < amount.kobo:
            raise InsufficientFundsError()
        lines = [EntryLine(wallet.ledger_account_id, Direction.DEBIT, amount),
                 EntryLine(await ledger.system_account_id(self.db, destination), Direction.CREDIT, amount)]
        posted = await ledger.post_journal(self.db, reference=reference, kind=kind, lines=lines,
                                           description=description, meta=meta)
        if posted.created:
            await self._apply_balance(wallet, -amount.kobo)
        return Movement(wallet.id, posted.id, reference, posted.created, amount, Money(wallet.balance_kobo))

    async def reverse(self, original_reference: str, *, reference: str, reason: str = "") -> Movement:
        """Post the mirror image of an earlier wallet journal. A journal can be reversed once."""
        original = await ledger.get_journal_by_reference(self.db, original_reference)
        if original is None:
            raise ledger.JournalNotFoundError()
        lines = await ledger.journal_lines(self.db, original.id)
        wallet_ids = set((await self.db.execute(
            select(Wallet.id, Wallet.user_id, Wallet.ledger_account_id)
            .where(Wallet.ledger_account_id.in_({ln.account_id for ln in lines})))).all())
        if len(wallet_ids) != 1:
            raise ReversalTargetError()
        _, user_id, account_id = next(iter(wallet_ids))
        wallet = await self._locked(user_id)
        wallet_line = next(ln for ln in lines if ln.account_id == account_id)

        prior = await ledger.find_reversal(self.db, original.id)
        if prior is not None and prior.reference != reference:
            raise AlreadyReversedError()
        # Reversing a debit returns money; reversing a credit (e.g. a refunded funding) removes it.
        delta = wallet_line.amount.kobo if wallet_line.direction is Direction.DEBIT else -wallet_line.amount.kobo
        if prior is None and delta < 0 and wallet.balance_kobo < -delta:
            raise InsufficientFundsError()
        mirrored = [EntryLine(ln.account_id, ln.direction.opposite, ln.amount) for ln in lines]
        posted = await ledger.post_journal(
            self.db, reference=reference, kind="reversal", lines=mirrored, description=reason,
            meta={"reverses": original_reference}, reverses=original.id)
        if posted.created:
            await self._apply_balance(wallet, delta)
        return Movement(wallet.id, posted.id, reference, posted.created, wallet_line.amount,
                        Money(wallet.balance_kobo))

    async def verify_integrity(self, user_id: uuid.UUID) -> IntegrityReport:
        wallet = await self.get_or_create(user_id)
        await self.db.refresh(wallet)
        return IntegrityReport(wallet.balance_kobo, await ledger.account_net_credit(self.db, wallet.ledger_account_id))
