import uuid
from enum import StrEnum
from typing import Any

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.ids import uuid7
from app.modules.ledger.models import AccountType, LedgerAccount


class SystemAccount(StrEnum):
    PROCESSOR_CLEARING = "platform:processor_clearing"  # money held for us by the payment processor
    PROVIDER_CLEARING = "platform:provider_clearing"    # owed to bill providers for held purchases
    REVENUE = "platform:revenue"
    FEES = "platform:fees"
    SUSPENSE = "platform:suspense"                      # unresolved discrepancies awaiting finance
    PROVIDER_FLOAT = "platform:provider_float"          # our prepaid balance with the bill provider
    PROVIDER_COST = "platform:provider_cost"            # cost of sales
    DISCOUNTS = "platform:discounts"                    # customer discounts / promotions (contra-revenue)
    SERVICE_FEES = "platform:service_fees"              # fees charged on purchases
    REFERRAL_EXPENSE = "platform:referral_expense"
    REFERRAL_PAYABLE = "platform:referral_payable"


SYSTEM_ACCOUNT_TYPES: dict[SystemAccount, AccountType] = {
    SystemAccount.PROCESSOR_CLEARING: AccountType.ASSET,
    SystemAccount.PROVIDER_CLEARING: AccountType.LIABILITY,
    SystemAccount.REVENUE: AccountType.REVENUE,
    SystemAccount.FEES: AccountType.REVENUE,
    SystemAccount.SUSPENSE: AccountType.LIABILITY,
    SystemAccount.PROVIDER_FLOAT: AccountType.ASSET,
    SystemAccount.PROVIDER_COST: AccountType.EXPENSE,
    SystemAccount.DISCOUNTS: AccountType.EXPENSE,
    SystemAccount.SERVICE_FEES: AccountType.REVENUE,
    SystemAccount.REFERRAL_EXPENSE: AccountType.EXPENSE,
    SystemAccount.REFERRAL_PAYABLE: AccountType.LIABILITY,
}


async def ensure_system_accounts(executor: Any) -> None:
    """Idempotent; `executor` is an AsyncSession or AsyncConnection."""
    for code, typ in SYSTEM_ACCOUNT_TYPES.items():
        await executor.execute(
            insert(LedgerAccount).values(id=uuid7(), code=code.value, type=typ.value)
            .on_conflict_do_nothing(index_elements=["code"]))


async def system_account_id(db: AsyncSession, code: SystemAccount) -> uuid.UUID:
    found = (await db.execute(select(LedgerAccount.id).where(LedgerAccount.code == code.value))
             ).scalar_one_or_none()
    if found is None:
        raise LookupError(f"system ledger account {code.value} is missing; run migrations")
    return found


async def ensure_wallet_account(db: AsyncSession, user_id: uuid.UUID) -> uuid.UUID:
    code = f"wallet:{user_id}"
    await db.execute(
        insert(LedgerAccount).values(id=uuid7(), code=code, type=AccountType.LIABILITY.value,
                                     owner_user_id=user_id)
        .on_conflict_do_nothing(index_elements=["code"]))
    return (await db.execute(select(LedgerAccount.id).where(LedgerAccount.code == code))).scalar_one()
