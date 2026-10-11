from app.core.errors import AppError


class InvalidCredentialsError(AppError):
    status_code, code = 401, "invalid_credentials"
    user_message = "Phone number or password is incorrect."


class AccountLockedError(AppError):
    status_code, code = 429, "account_locked"
    user_message = "Too many failed attempts. Please try again later."


class InvalidOtpError(AppError):
    status_code, code = 400, "invalid_otp"
    user_message = "That code is incorrect or has expired."


class PhoneNotVerifiedError(AppError):
    status_code, code = 403, "phone_not_verified"
    user_message = "Please verify your phone number first."


class InvalidPinError(AppError):
    status_code, code = 400, "invalid_pin"
    user_message = "Incorrect PIN."


class PinLockedError(AppError):
    status_code, code = 429, "pin_locked"
    user_message = "Too many incorrect PIN attempts. Please try again later."


class PinNotSetError(AppError):
    status_code, code = 409, "pin_not_set"
    user_message = "Set a transaction PIN first."


class WeakPinError(AppError):
    status_code, code = 422, "weak_pin"
    user_message = "Choose a PIN that is not repeated or sequential."
