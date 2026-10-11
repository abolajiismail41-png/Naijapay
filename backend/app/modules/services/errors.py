from app.core.errors import AppError


class PricingBlockedError(AppError):
    """Customer price would fall below provider cost. Customer sees a neutral message only."""
    status_code, code = 503, "service_unavailable"
    user_message = "This service is temporarily unavailable. Please try again later."


class PricingUnavailableError(AppError):
    status_code, code = 503, "service_unavailable"
    user_message = "This service is temporarily unavailable. Please try again later."


class PriceChangedError(AppError):
    status_code, code = 409, "price_changed"
    user_message = "The price has changed. Please review the new price and confirm again."
