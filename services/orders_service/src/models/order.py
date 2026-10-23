from datetime import datetime
from decimal import Decimal

from sqlalchemy import ForeignKey, Index, Numeric, String, desc
from sqlalchemy.orm import Mapped, mapped_column

from models.base import Base, created_at_column, updated_at_column


class Order(Base):
    __tablename__ = "orders"
    __table_args__ = (Index("ix_orders_user_id_updated_at_desc", "user_id", desc("updated_at")),)

    order_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    creation_idempotency_key: Mapped[str] = mapped_column(String(128), unique=True)
    deal_idempotency_key: Mapped[str] = mapped_column(String(64), unique=True)
    payout_idempotency_key: Mapped[str] = mapped_column(String(64), unique=True)
    payout_token: Mapped[str | None] = mapped_column(String(512))
    user_id: Mapped[str] = mapped_column(String(36))
    seller_id: Mapped[str] = mapped_column(String(36), index=True)
    multi_order_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("multi_orders.id"), index=True)
    yookassa_account_id: Mapped[str | None] = mapped_column(String(128))
    delivery_type: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(64))
    receival_code: Mapped[str | None] = mapped_column(String(6))
    address: Mapped[str] = mapped_column(String(1024))
    buyer_amount: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    seller_amount: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    created_at: Mapped[datetime] = created_at_column()
    updated_at: Mapped[datetime] = updated_at_column()
