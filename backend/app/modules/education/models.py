import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, Index, Integer, String, UniqueConstraint, func, text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base
from app.core.ids import uuid7


class EducationProduct(Base):
    """An exam PIN product (WAEC / NECO result checker...). Mapping and cost are entered by an admin because
    the provider's catalogue format is not fully verified."""

    __tablename__ = "education_products"
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid7)
    provider_code: Mapped[str] = mapped_column(String(20))
    code: Mapped[str] = mapped_column(String(20))                       # WAEC, NECO: also a pricing scope
    name: Mapped[str] = mapped_column(String(80))
    provider_service_id: Mapped[str] = mapped_column(String(40))
    max_quantity: Mapped[int] = mapped_column(Integer, default=5, server_default=text("5"))
    listed: Mapped[bool] = mapped_column(Boolean, default=False, server_default=text("false"))
    active: Mapped[bool] = mapped_column(Boolean, default=True, server_default=text("true"))
    sort_order: Mapped[int] = mapped_column(Integer, default=0, server_default=text("0"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    __table_args__ = (
        UniqueConstraint("provider_code", "provider_service_id", name="uq_education_products_provider_service"),
        Index("ix_education_products_listing", "sort_order", postgresql_where=text("listed AND active")),
    )
