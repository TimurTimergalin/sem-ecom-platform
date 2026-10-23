from datetime import datetime

from sqlalchemy import ForeignKey, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from models.base import Base, created_at_column


class Deal(Base):
    __tablename__ = "deals"

    deal_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    status: Mapped[str] = mapped_column(String(64))
    last_state: Mapped[dict] = mapped_column(JSONB)
    order_id: Mapped[str] = mapped_column(String(36), ForeignKey("orders.order_id"), unique=True)
    created_at: Mapped[datetime] = created_at_column()
