from datetime import UTC, datetime
from enum import StrEnum

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError
from app.modules.transactions.models import Transaction, TransactionEvent


class TxnStatus(StrEnum):
    INITIATED = "INITIATED"
    PENDING = "PENDING"          # funds held, provider not called yet
    PROCESSING = "PROCESSING"    # provider call in flight or accepted
    SUCCESSFUL = "SUCCESSFUL"
    FAILED = "FAILED"
    UNKNOWN = "UNKNOWN"          # outcome unknown: NEVER refunded automatically
    REFUNDED = "REFUNDED"
    REVERSED = "REVERSED"


S = TxnStatus
ALLOWED: dict[TxnStatus, frozenset[TxnStatus]] = {
    S.INITIATED: frozenset({S.PENDING, S.FAILED}),
    S.PENDING: frozenset({S.PROCESSING, S.FAILED}),
    S.PROCESSING: frozenset({S.SUCCESSFUL, S.FAILED, S.UNKNOWN}),
    S.UNKNOWN: frozenset({S.SUCCESSFUL, S.FAILED, S.PROCESSING}),
    S.FAILED: frozenset({S.REFUNDED}),
    S.SUCCESSFUL: frozenset({S.REVERSED}),
    S.REFUNDED: frozenset(),
    S.REVERSED: frozenset(),
}
SETTLED = frozenset({S.SUCCESSFUL, S.FAILED, S.REFUNDED, S.REVERSED})
_COMPLETING = frozenset({S.SUCCESSFUL, S.REFUNDED, S.REVERSED})


class InvalidTransitionError(AppError):
    status_code, code = 500, "invalid_transition"
    user_message = "Something went wrong on our side."


def transition(db: AsyncSession, txn: Transaction, to: TxnStatus, note: str = "") -> None:
    frm = TxnStatus(txn.status)
    if to not in ALLOWED[frm]:
        raise InvalidTransitionError(transaction=txn.reference, frm=frm.value, to=to.value)
    txn.status = to.value
    if to in _COMPLETING:
        txn.completed_at = datetime.now(UTC)
    db.add(TransactionEvent(transaction_id=txn.id, from_status=frm.value, to_status=to.value, note=note[:200]))
