from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator


class NotificationRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    category: str
    title: str
    body: str
    resource_type: str | None
    resource_reference: str | None
    payload: dict
    read_at: datetime | None
    created_at: datetime


class NotificationPage(BaseModel):
    items: list[NotificationRead]
    next_cursor: str | None
    unread_count: int


class PreferencesRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    in_app_enabled: bool
    email_enabled: bool
    sms_enabled: bool
    push_enabled: bool
    email_address: str | None


class PreferencesUpdate(BaseModel):
    in_app_enabled: bool | None = None
    email_enabled: bool | None = None
    sms_enabled: bool | None = None
    push_enabled: bool | None = None
    email_address: str | None = Field(default=None, max_length=254)

    @field_validator("email_address")
    @classmethod
    def validate_email_address(cls, value: str | None) -> str | None:
        if value is None or value == "":
            return value
        import re
        if not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", value):
            raise ValueError("Enter a valid email address.")
        return value


class MarkRead(BaseModel):
    ids: list[UUID] = Field(min_length=1, max_length=100)
