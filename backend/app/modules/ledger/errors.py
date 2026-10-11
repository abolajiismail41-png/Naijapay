from app.core.errors import AppError


class UnbalancedJournalError(AppError):
    status_code, code = 500, "ledger_unbalanced"
    user_message = "Something went wrong on our side."


class IdempotencyConflictError(AppError):
    status_code, code = 409, "idempotency_conflict"
    user_message = "This request reuses a reference with different details."


class JournalNotFoundError(AppError):
    status_code, code = 404, "journal_not_found"
    user_message = "The original transaction was not found."
