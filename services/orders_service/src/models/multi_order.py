from datetime import datetime

from sqlalchemy import String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from models.base import Base, created_at_column, updated_at_column


class MultiOrder(Base):
    __tablename__ = "multi_orders"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    user_id: Mapped[str] = mapped_column(String(36), index=True)
    payment_id: Mapped[str | None] = mapped_column(String(128))
    payment_status: Mapped[str] = mapped_column(String(64))
    confirmation_url: Mapped[str | None] = mapped_column(String(2048))
    idempotency_key: Mapped[str] = mapped_column(String(128), unique=True)
    yookassa_payload: Mapped[dict] = mapped_column(JSONB)
    created_at: Mapped[datetime] = created_at_column()
    updated_at: Mapped[datetime] = updated_at_column()
