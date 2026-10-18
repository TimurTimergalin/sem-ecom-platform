from sqlalchemy import ForeignKey, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from models.base import Base


class Refund(Base):
    __tablename__ = "refunds"

    refund_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    status: Mapped[str] = mapped_column(String(64))
    last_state: Mapped[dict] = mapped_column(JSONB)
    payment_id: Mapped[str] = mapped_column(String(128), ForeignKey("payments.payment_id"))
