from datetime import datetime

from sqlalchemy import ForeignKey, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from models.base import Base, created_at_column


class Payment(Base):
    __tablename__ = "payments"

    payment_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    idempotency_key: Mapped[str] = mapped_column(String(64), unique=True)
    refund_idempotency_key: Mapped[str | None] = mapped_column(String(64), unique=True)
    status: Mapped[str] = mapped_column(String(64))
    confirmation_url: Mapped[str | None] = mapped_column(String(2048))
    last_state: Mapped[dict] = mapped_column(JSONB)
    deal_id: Mapped[str] = mapped_column(String(128), ForeignKey("deals.deal_id"), index=True)
    created_at: Mapped[datetime] = created_at_column()
