from app.core.errors import AppError


class InsufficientFundsError(AppError):
    status_code, code = 422, "insufficient_funds"
    user_message = "Your wallet balance is too low for this transaction."


class WalletInactiveError(AppError):
    status_code, code = 403, "wallet_inactive"
    user_message = "Your wallet is currently unavailable. Please contact support."


class AlreadyReversedError(AppError):
    status_code, code = 409, "already_reversed"
    user_message = "This transaction has already been reversed."


class ReversalTargetError(AppError):
    status_code, code = 422, "invalid_reversal_target"
    user_message = "This transaction cannot be reversed."
