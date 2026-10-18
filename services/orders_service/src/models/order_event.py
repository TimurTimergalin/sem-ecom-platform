from datetime import datetime

from sqlalchemy import BigInteger, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from models.base import Base, created_at_column


class OrderEvent(Base):
    __tablename__ = "order_events"

    id: Mapped[int] = mapped_column(primary_key=True)
    order_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("orders.order_id"))
    old_status: Mapped[str] = mapped_column(String(64))
    new_status: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = created_at_column()
