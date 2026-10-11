import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, Index, Integer, String, UniqueConstraint, func, text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base
from app.core.ids import uuid7


class ElectricityDisco(Base):
    """A distribution company we sell. The provider mapping (disco code and service ids) is admin-editable
    because it is the part of the provider API we cannot assume."""

    __tablename__ = "electricity_discos"
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid7)
    provider_code: Mapped[str] = mapped_column(String(20))
    code: Mapped[str] = mapped_column(String(20))                       # our key, also a pricing scope (e.g. IKEJA)
    name: Mapped[str] = mapped_column(String(80))
    provider_disco_code: Mapped[str] = mapped_column(String(40))        # what the provider calls it in verify requests
    prepaid_service_id: Mapped[str | None] = mapped_column(String(40))
    postpaid_service_id: Mapped[str | None] = mapped_column(String(40))
    listed: Mapped[bool] = mapped_column(Boolean, default=False, server_default=text("false"))
    active: Mapped[bool] = mapped_column(Boolean, default=True, server_default=text("true"))
    sort_order: Mapped[int] = mapped_column(Integer, default=0, server_default=text("0"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    __table_args__ = (
        UniqueConstraint("provider_code", "code", name="uq_electricity_discos_provider_code"),
        Index("ix_electricity_discos_listing", "sort_order", postgresql_where=text("listed AND active")),
    )

    def service_id(self, meter_type: str) -> str | None:
        return self.prepaid_service_id if meter_type == "PREPAID" else self.postpaid_service_id
