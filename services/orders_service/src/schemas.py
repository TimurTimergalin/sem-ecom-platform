from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, Field, model_validator

MAX_AMOUNT = Decimal("9999999999.99")


class ItemIn(BaseModel):
    sku_id: str = Field(min_length=1, max_length=36)
    name: str = Field(min_length=1, max_length=255)
    image: str = Field(min_length=1, max_length=2048)
    price: Decimal = Field(ge=0, max_digits=12, decimal_places=2)
    quantity: int = Field(gt=0)


class OrderGroupIn(BaseModel):
    seller_id: str = Field(min_length=1, max_length=36)
    yookassa_account_id: str = Field(default="", max_length=128)
    address: str = Field(min_length=1, max_length=1024)
    delivery_type: str = Field(min_length=1, max_length=64)
    items: list[ItemIn] = Field(min_length=1)

    @model_validator(mode="after")
    def unique_skus_and_amount(self) -> "OrderGroupIn":
        sku_ids = [item.sku_id for item in self.items]
        if len(sku_ids) != len(set(sku_ids)):
            raise ValueError("items contain a duplicate sku_id")
        total = items_total(self.items)
        if total <= 0:
            raise ValueError("order amount must be greater than zero")
        if total > MAX_AMOUNT:
            raise ValueError("order amount exceeds NUMERIC(12, 2)")
        return self


class CreateOrderRequest(BaseModel):
    user_id: str = Field(min_length=1, max_length=36)
    idempotency_key: str = Field(min_length=1, max_length=128)
    groups: list[OrderGroupIn] = Field(min_length=1)


class ItemOut(BaseModel):
    sku_id: str
    name: str
    image: str
    price: Decimal
    quantity: int


class DealOut(BaseModel):
    deal_id: str
    status: str


class Skipped(BaseModel):
    reason: str


class ConfirmOut(BaseModel):
    order_id: str
    status: str
    receival_code: str


class CompleteRequest(BaseModel):
    receival_code: str = Field(pattern=r"^\d{6}$")


class CompleteOut(BaseModel):
    order_id: str
    status: str


class CancelOut(BaseModel):
    order_id: str
    status: str


class OrderListItem(BaseModel):
    order_id: str
    seller_id: str
    images: list[str]
    status: str


class OrderList(BaseModel):
    orders: list[OrderListItem]
    next_cursor: str | None


class DealPublic(BaseModel):
    deal_id: str
    status: str


class PaymentPublic(BaseModel):
    payment_id: str
    status: str
    confirmation_url: str | None


class OrderDetail(BaseModel):
    order_id: str
    user_id: str
    seller_id: str
    status: str
    delivery_type: str
    address: str
    buyer_amount: Decimal
    seller_amount: Decimal
    receival_code: str | None
    created_at: datetime
    updated_at: datetime
    items: list[ItemOut]
    deal: DealPublic | None
    payment: PaymentPublic | None
    multi_order_id: str | None = None


class DebugEvent(BaseModel):
    id: int
    old_status: str
    new_status: str
    created_at: datetime


class DebugOrderEvent(DebugEvent):
    order_id: str


class DebugDealEvent(DebugEvent):
    deal_id: str


class DebugPaymentEvent(DebugEvent):
    payment_id: str


class DebugRefundEvent(DebugEvent):
    refund_id: str


class DebugDeal(BaseModel):
    deal_id: str
    status: str
    last_state: dict
    order_id: str
    created_at: datetime


class DebugPayment(BaseModel):
    payment_id: str
    idempotency_key: str
    refund_idempotency_key: str | None
    status: str
    confirmation_url: str | None
    last_state: dict
    deal_id: str
    created_at: datetime


class DebugRefund(BaseModel):
    refund_id: str
    status: str
    last_state: dict
    payment_id: str


class OrderDebug(BaseModel):
    order_id: str
    creation_idempotency_key: str
    deal_idempotency_key: str
    payout_idempotency_key: str
    payout_token: str | None = None
    multi_order_id: str | None = None
    user_id: str
    seller_id: str
    delivery_type: str
    status: str
    receival_code: str | None
    address: str
    buyer_amount: Decimal
    seller_amount: Decimal
    created_at: datetime
    updated_at: datetime
    items: list[ItemOut]
    deal: DebugDeal | None
    payments: list[DebugPayment]
    refunds: list[DebugRefund]
    order_events: list[DebugOrderEvent]
    deal_events: list[DebugDealEvent]
    payment_events: list[DebugPaymentEvent]
    refund_events: list[DebugRefundEvent]


class GroupOrderOut(BaseModel):
    order_id: str
    seller_id: str
    status: str
    buyer_amount: Decimal


class OrderOut(BaseModel):
    order_id: str
    user_id: str
    seller_id: str
    address: str
    delivery_type: str
    status: str
    buyer_amount: Decimal
    seller_amount: Decimal
    items: list[ItemOut]
    deal: DealOut | None = None
    confirmation_url: str
    multi_order_id: str
    orders: list[GroupOrderOut]


def items_total(items: list[ItemIn]) -> Decimal:
    total = sum((item.price * item.quantity for item in items), Decimal("0"))
    return total.quantize(Decimal("0.01"))
