from app.core.errors import AppError


class ProcessorUnavailableError(AppError):
    """Outcome unknown (timeout, 5xx, network). Never treat as a failed payment."""
    status_code, code = 502, "payment_provider_unavailable"
    user_message = "We could not reach the payment provider. You have not been charged. Please try again."


class ProcessorRejectedError(AppError):
    """The processor definitively refused the request."""
    status_code, code = 502, "payment_provider_rejected"
    user_message = "We could not start this payment. You have not been charged."


class AmountOutOfRangeError(AppError):
    status_code, code = 422, "amount_out_of_range"
    user_message = "Amount is outside the allowed funding range."
