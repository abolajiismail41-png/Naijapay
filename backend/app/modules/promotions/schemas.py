from datetime import datetime
from uuid import UUID
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class PromoCreate(BaseModel):
    code: str = Field(min_length=3, max_length=32, pattern=r"^[A-Za-z0-9_-]+$")
    name: str = Field(min_length=2, max_length=100)
    description: str = Field(default="", max_length=300)
    reward_kobo: int = Field(gt=0, le=100_000_000)
    minimum_qualifying_purchase_kobo: int = Field(default=0, ge=0, le=200_000_000)
    max_redemptions: int | None = Field(default=None, ge=1, le=1_000_000)
    starts_at: datetime | None = None
    ends_at: datetime | None = None
    active: bool = True

    @field_validator("starts_at", "ends_at")
    @classmethod
    def timezone_required(cls, value: datetime | None) -> datetime | None:
        if value is not None and value.tzinfo is None:
            raise ValueError("Campaign datetimes must include a timezone, for example +01:00 or Z.")
        return value

    @model_validator(mode="after")
    def date_range(self):
        if self.starts_at and self.ends_at and self.ends_at <= self.starts_at:
            raise ValueError("ends_at must be after starts_at")
        return self


class PromoUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=2, max_length=100)
    description: str | None = Field(default=None, max_length=300)
    active: bool | None = None
    ends_at: datetime | None = None

    @field_validator("ends_at")
    @classmethod
    def timezone_required(cls, value: datetime | None) -> datetime | None:
        if value is not None and value.tzinfo is None:
            raise ValueError("Campaign datetimes must include a timezone, for example +01:00 or Z.")
        return value


class PromoRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    code: str
    name: str
    description: str
    reward_kobo: int
    minimum_qualifying_purchase_kobo: int
    max_redemptions: int | None
    starts_at: datetime | None
    ends_at: datetime | None
    active: bool
    created_at: datetime


class PromoRedeemIn(BaseModel):
    code: str = Field(min_length=3, max_length=32, pattern=r"^[A-Za-z0-9_-]+$")


class PromoRedemptionRead(BaseModel):
    code: str
    reward_kobo: int
    journal_reference: str
    redeemed_at: datetime
