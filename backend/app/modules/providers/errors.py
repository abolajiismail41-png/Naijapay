from app.core.errors import AppError


class ProviderUnavailableError(AppError):
    status_code, code = 502, "provider_unavailable"
    user_message = "This service is temporarily unavailable. Please try again shortly."


class MeterInvalidError(AppError):
    status_code, code = 422, "invalid_meter"
    user_message = "We could not verify this meter number. Please check it and try again."


class SmartcardInvalidError(AppError):
    status_code, code = 422, "invalid_smartcard"
    user_message = "We could not verify this smartcard number. Please check it and try again."
