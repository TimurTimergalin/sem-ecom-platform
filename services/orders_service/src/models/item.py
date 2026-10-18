from decimal import Decimal

from sqlalchemy import BigInteger, ForeignKey, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column

from models.base import Base


class Item(Base):
    __tablename__ = "items"

    sku_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    order_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("orders.order_id"), primary_key=True)
    name: Mapped[str] = mapped_column(String(255))
    image: Mapped[str] = mapped_column(String(2048))
    price: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    quantity: Mapped[int]

