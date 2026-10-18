from datetime import datetime

from sqlalchemy import ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from models.base import Base, created_at_column


class DealEvent(Base):
    __tablename__ = "deal_events"

    id: Mapped[int] = mapped_column(primary_key=True)
    deal_id: Mapped[str] = mapped_column(String(128), ForeignKey("deals.deal_id"))
    old_status: Mapped[str] = mapped_column(String(64))
    new_status: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = created_at_column()
