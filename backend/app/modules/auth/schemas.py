from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

from app.core.phone import Phone

Password = Annotated[str, StringConstraints(min_length=8, max_length=128)]
Pin = Annotated[str, StringConstraints(pattern=r"^\d{4}$")]
OtpCode = Annotated[str, StringConstraints(pattern=r"^\d{6}$")]


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class RegisterIn(_Strict):
    phone: Phone
    password: Password
    full_name: str = Field(min_length=2, max_length=120)
    email: Annotated[str, StringConstraints(min_length=5, max_length=254, pattern=r"^[^\s@]+@[^\s@]+\.[^\s@]+$")]
    referral_code: str | None = Field(default=None, min_length=3, max_length=16, pattern=r"^[A-Za-z0-9_-]+$")


class VerifyPhoneIn(_Strict):
    phone: Phone
    code: OtpCode


class LoginIn(_Strict):
    phone: Phone
    password: Annotated[str, StringConstraints(min_length=1, max_length=128)]


class RefreshIn(_Strict):
    refresh_token: str = Field(min_length=20, max_length=200)


class ResetRequestIn(_Strict):
    phone: Phone


class ResetConfirmIn(_Strict):
    phone: Phone
    code: OtpCode
    new_password: Password


class SetPinIn(_Strict):
    password: Annotated[str, StringConstraints(min_length=1, max_length=128)]
    pin: Pin


class ChangePinIn(_Strict):
    current_pin: Pin
    new_pin: Pin


class VerifyPinIn(_Strict):
    pin: Pin


class TokenPair(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int
