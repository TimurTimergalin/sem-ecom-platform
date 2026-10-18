import asyncio
import json
import secrets
import uuid

import yookassa_setup
from dataclasses import dataclass
from decimal import Decimal

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from yookassa import Deal, Payout
from yookassa import Payment as YooKassaPayment
from yookassa import Refund as YooKassaRefund

from db import run_serializable
from models.deal import Deal as DealRow
from models.item import Item
from models.order import Order
from models.payment import Payment as PaymentRow
from models.refund import Refund as RefundRow
from schemas import (
    CancelOut,
    CompleteOut,
    CompleteRequest,
    ConfirmOut,
    CreateOrderRequest,
    DealOut,
    ItemOut,
    OrderOut,
    Skipped,
    items_total,
)

ORDER_STATUS_CREATED = "CREATED"
ORDER_STATUS_DEAL_CREATED = "DEAL_CREATED"
ORDER_STATUS_PAYMENT_INITIALIZED = "PAYMENT_INITIALIZED"
ORDER_STATUS_PAID = "PAID"
ORDER_STATUS_DELIVERED = "DELIVERED"
ORDER_STATUS_COMPLETED = "COMPLETED"
ORDER_STATUS_CANCELLED = "CANCELLED"
PAYMENT_STATUS_CREATED = "created"
PAYMENT_STATUS_PENDING = "pending"
PAYMENT_STATUS_CANCELLED = "cancelled"
YOOKASSA_SUCCEEDED = "succeeded"
YOOKASSA_CANCELED = {"canceled", "cancelled"}
UNMADE_PAYMENT_STATUSES = {PAYMENT_STATUS_CREATED, *YOOKASSA_CANCELED}
DEAL_STATUS_CLOSED = "closed"
RESUMABLE_ORDER_STATUSES = {
    ORDER_STATUS_CREATED,
    ORDER_STATUS_DEAL_CREATED,
    ORDER_STATUS_PAYMENT_INITIALIZED,
}
DEAL_FEE_MOMENT = "deal_closed"
PAYOUT_CANCELED = "canceled"


class YooKassaFailed(Exception):
    pass


class OrderNotFound(Exception):
    pass


class StateMismatch(Exception):
    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


def _touch(order: Order) -> None:
    order.updated_at = func.now()


@dataclass(frozen=True)
class StoredDeal:
    deal_id: str
    status: str


@dataclass(frozen=True)
class StoredPayment:
    payment_id: str
    idempotency_key: str
    status: str
    confirmation_url: str | None


@dataclass(frozen=True)
class StoredOrder:
    order_id: int
    user_id: int
    address: str
    delivery_type: str
    status: str
    buyer_amount: Decimal
    seller_amount: Decimal
    deal_idempotency_key: str
    items: tuple[ItemOut, ...]
    deal: StoredDeal | None
    payment: StoredPayment | None


async def create_order(
    sessions: async_sessionmaker[AsyncSession],
    request: CreateOrderRequest,
) -> OrderOut:
    stored = await run_serializable(sessions, lambda session: _get_or_create_order(session, request))

    if stored.deal is None:
        remote_deal = await _create_yookassa_deal(stored.order_id, stored.deal_idempotency_key)
        if not remote_deal.id:
            raise YooKassaFailed
        order_id = stored.order_id
        stored = await run_serializable(
            sessions,
            lambda session: _save_deal_and_payment(session, order_id, remote_deal),
        )

    if stored.payment is None or not stored.payment.confirmation_url:
        if stored.payment is None:
            raise RuntimeError("deal was saved without a payment")
        stored = await _issue_payment(sessions, stored)

    return _order_out(stored)


async def repay_order(
    sessions: async_sessionmaker[AsyncSession],
    order_id: int,
) -> OrderOut | Skipped:
    stored = await run_serializable(sessions, lambda session: _load_order(session, order_id))
    if stored is None:
        raise OrderNotFound
    if stored.status not in RESUMABLE_ORDER_STATUSES:
        raise StateMismatch(f"order status is {stored.status}")

    if stored.deal is None:
        remote_deal = await _create_yookassa_deal(stored.order_id, stored.deal_idempotency_key)
        if not remote_deal.id:
            raise YooKassaFailed
        stored = await run_serializable(
            sessions,
            lambda session: _save_deal_and_payment(session, order_id, remote_deal),
        )
        stored = await _issue_payment(sessions, stored)
        return _order_out(stored)

    if stored.payment is None or stored.payment.status == PAYMENT_STATUS_CREATED:
        if stored.payment is None:
            stored = await run_serializable(sessions, lambda session: _insert_created_payment(session, order_id))
        stored = await _issue_payment(sessions, stored)
        return _order_out(stored)

    if stored.payment.status == PAYMENT_STATUS_PENDING:
        remote_payment = await _fetch_yookassa_payment(stored.payment.payment_id)
        idempotency_key = stored.payment.idempotency_key
        stored = await run_serializable(
            sessions,
            lambda session: _save_remote_payment_status(session, order_id, idempotency_key, remote_payment),
        )
        if stored.status == ORDER_STATUS_PAID:
            return _order_out(stored)
        if stored.payment is not None and stored.payment.status in YOOKASSA_CANCELED:
            stored = await run_serializable(sessions, lambda session: _insert_created_payment(session, order_id))
            stored = await _issue_payment(sessions, stored)
        return _order_out(stored)

    if stored.payment.status in YOOKASSA_CANCELED:
        stored = await run_serializable(sessions, lambda session: _insert_created_payment(session, order_id))
        stored = await _issue_payment(sessions, stored)
        return _order_out(stored)

    return _order_out(stored)


async def confirm_order(
    sessions: async_sessionmaker[AsyncSession],
    order_id: int,
) -> ConfirmOut:
    result = await run_serializable(sessions, lambda session: _confirm_paid_order(session, order_id))
    if result is None:
        raise OrderNotFound
    return result


async def _confirm_paid_order(session: AsyncSession, order_id: int) -> ConfirmOut | None:
    order = await session.get(Order, order_id)
    if order is None:
        return None
    if order.status != ORDER_STATUS_PAID:
        raise StateMismatch(f"order status is {order.status}")
    receival_code = f"{secrets.randbelow(1_000_000):06d}"
    order.status = ORDER_STATUS_DELIVERED
    order.receival_code = receival_code
    _touch(order)
    return ConfirmOut(order_id=order.order_id, status=order.status, receival_code=receival_code)


@dataclass(frozen=True)
class _PayoutReady:
    deal_id: str
    seller_amount: Decimal
    payout_idempotency_key: str
    payout_token: str


async def complete_order(
    sessions: async_sessionmaker[AsyncSession],
    order_id: int,
    request: CompleteRequest,
) -> CompleteOut | Skipped:
    prepared = await run_serializable(
        sessions,
        lambda session: _prepare_completion(session, order_id, request.receival_code),
    )
    if prepared is None:
        raise OrderNotFound
    if isinstance(prepared, Skipped):
        return prepared
    payout = await _create_yookassa_payout(order_id, prepared)
    if payout.status == PAYOUT_CANCELED:
        raise YooKassaFailed
    await run_serializable(sessions, lambda session: _mark_completed(session, order_id))
    return CompleteOut(order_id=order_id, status=ORDER_STATUS_COMPLETED)


async def _prepare_completion(
    session: AsyncSession,
    order_id: int,
    receival_code: str,
) -> _PayoutReady | Skipped | None:
    order = await session.get(Order, order_id)
    if order is None:
        return None
    if order.status != ORDER_STATUS_DELIVERED:
        raise StateMismatch(f"order status is {order.status}")
    saved_code = order.receival_code or ""
    if not secrets.compare_digest(saved_code, receival_code):
        return Skipped(reason="receival code does not match")
    deal = await session.scalar(select(DealRow).where(DealRow.order_id == order_id))
    if deal is None:
        return Skipped(reason="order has no deal")
    return _PayoutReady(
        deal_id=deal.deal_id,
        seller_amount=order.seller_amount,
        payout_idempotency_key=order.payout_idempotency_key,
        payout_token=order.payout_token,
    )


async def cancel_order(
    sessions: async_sessionmaker[AsyncSession],
    order_id: int,
) -> CancelOut:
    view = await run_serializable(sessions, lambda session: _load_cancel_view(session, order_id))
    if view is None:
        raise OrderNotFound
    if view.status in {ORDER_STATUS_COMPLETED, ORDER_STATUS_CANCELLED}:
        raise StateMismatch(f"order status is {view.status}")
    if view.deal_id is None:
        await run_serializable(sessions, lambda session: _cancel_order_row(session, order_id))
        return CancelOut(order_id=order_id, status=ORDER_STATUS_CANCELLED)

    pending = next((payment for payment in view.payments if payment.status == PAYMENT_STATUS_PENDING), None)
    if pending is not None:
        remote = await _fetch_yookassa_payment(pending.payment_id)
        if remote.status == PAYMENT_STATUS_PENDING:
            remote = await _discard_yookassa_payment(pending.payment_id)
        await run_serializable(
            sessions,
            lambda session: _save_payment_state(session, pending.idempotency_key, remote),
        )
        if remote.status == YOOKASSA_SUCCEEDED:
            await _refund_succeeded_payment(sessions, order_id, pending.idempotency_key, view.buyer_amount)
            return CancelOut(order_id=order_id, status=ORDER_STATUS_CANCELLED)
        if remote.status not in YOOKASSA_CANCELED:
            raise YooKassaFailed
        await run_serializable(sessions, lambda session: _close_unpaid_deal(session, order_id))
        return CancelOut(order_id=order_id, status=ORDER_STATUS_CANCELLED)

    succeeded = next((payment for payment in view.payments if payment.status == YOOKASSA_SUCCEEDED), None)
    if succeeded is not None:
        await _refund_succeeded_payment(sessions, order_id, succeeded.idempotency_key, view.buyer_amount)
        return CancelOut(order_id=order_id, status=ORDER_STATUS_CANCELLED)

    if view.payments and all(payment.status in UNMADE_PAYMENT_STATUSES for payment in view.payments):
        await run_serializable(sessions, lambda session: _close_unpaid_deal(session, order_id))
        return CancelOut(order_id=order_id, status=ORDER_STATUS_CANCELLED)
    if not view.payments:
        await run_serializable(sessions, lambda session: _close_unpaid_deal(session, order_id))
        return CancelOut(order_id=order_id, status=ORDER_STATUS_CANCELLED)
    raise StateMismatch(f"order status is {view.status}")


async def _mark_completed(session: AsyncSession, order_id: int) -> None:
    order = await session.get(Order, order_id)
    if order is None:
        raise RuntimeError("order missing")
    if order.status == ORDER_STATUS_DELIVERED:
        order.status = ORDER_STATUS_COMPLETED
        _touch(order)


async def _create_yookassa_payout(order_id: int, prepared: _PayoutReady):
    try:
        return await asyncio.to_thread(
            Payout.create,
            {
                "amount": {"value": _money(prepared.seller_amount), "currency": "RUB"},
                "payout_token": prepared.payout_token,
                "description": f"Order {order_id}",
                "metadata": {"order_id": str(order_id)},
                "deal": {"id": prepared.deal_id},
            },
            prepared.payout_idempotency_key,
        )
    except Exception as exc:
        raise YooKassaFailed from exc


async def _issue_payment(
    sessions: async_sessionmaker[AsyncSession],
    stored: StoredOrder,
) -> StoredOrder:
    if stored.deal is None or stored.payment is None:
        raise RuntimeError("deal was saved without a payment")
    remote_payment = await _create_yookassa_payment(stored, stored.payment.idempotency_key)
    confirmation = remote_payment.confirmation
    confirmation_url = None if confirmation is None else confirmation.confirmation_url
    if not remote_payment.id or not confirmation_url:
        raise YooKassaFailed
    order_id = stored.order_id
    idempotency_key = stored.payment.idempotency_key
    return await run_serializable(
        sessions,
        lambda session: _finalize_payment(session, order_id, idempotency_key, remote_payment, confirmation_url),
    )


async def _load_order(session: AsyncSession, order_id: int) -> StoredOrder | None:
    order = await session.get(Order, order_id)
    if order is None:
        return None
    return await _snapshot(session, order_id)


async def _insert_created_payment(session: AsyncSession, order_id: int) -> StoredOrder:
    deal = await session.scalar(select(DealRow).where(DealRow.order_id == order_id))
    if deal is None:
        raise RuntimeError("deal missing")
    session.add(
        PaymentRow(
            payment_id=str(uuid.uuid4()),
            idempotency_key=str(uuid.uuid4()),
            status=PAYMENT_STATUS_CREATED,
            confirmation_url=None,
            last_state={},
            deal_id=deal.deal_id,
        )
    )
    order = await session.get(Order, order_id)
    if order is None:
        raise RuntimeError("order missing")
    _touch(order)
    return await _snapshot(session, order_id)


async def _save_remote_payment_status(
    session: AsyncSession,
    order_id: int,
    idempotency_key: str,
    remote_payment,
) -> StoredOrder:
    order = await session.get(Order, order_id)
    payment = await session.scalar(select(PaymentRow).where(PaymentRow.idempotency_key == idempotency_key))
    if order is None or payment is None:
        raise RuntimeError("order or payment missing")
    payment.status = remote_payment.status
    payment.last_state = json.loads(remote_payment.json())
    if remote_payment.status == YOOKASSA_SUCCEEDED:
        order.status = ORDER_STATUS_PAID
    _touch(order)
    return await _snapshot(session, order_id)


async def _fetch_yookassa_payment(payment_id: str):
    try:
        return await asyncio.to_thread(YooKassaPayment.find_one, payment_id)
    except Exception as exc:
        raise YooKassaFailed from exc


@dataclass(frozen=True)
class _PaymentView:
    payment_id: str
    idempotency_key: str
    status: str


@dataclass(frozen=True)
class _CancelView:
    status: str
    buyer_amount: Decimal
    deal_id: str | None
    payments: tuple[_PaymentView, ...]


async def _load_cancel_view(session: AsyncSession, order_id: int) -> _CancelView | None:
    order = await session.get(Order, order_id)
    if order is None:
        return None
    deal = await session.scalar(select(DealRow).where(DealRow.order_id == order_id))
    payments: tuple[_PaymentView, ...] = ()
    if deal is not None:
        rows = (
            await session.scalars(
                select(PaymentRow).where(PaymentRow.deal_id == deal.deal_id).order_by(PaymentRow.created_at.desc())
            )
        ).all()
        payments = tuple(
            _PaymentView(payment_id=row.payment_id, idempotency_key=row.idempotency_key, status=row.status)
            for row in rows
        )
    return _CancelView(
        status=order.status,
        buyer_amount=order.buyer_amount,
        deal_id=None if deal is None else deal.deal_id,
        payments=payments,
    )


async def _cancel_order_row(session: AsyncSession, order_id: int) -> None:
    order = await session.get(Order, order_id)
    if order is None:
        raise RuntimeError("order missing")
    order.status = ORDER_STATUS_CANCELLED
    _touch(order)


async def _close_unpaid_deal(session: AsyncSession, order_id: int) -> None:
    order = await session.get(Order, order_id)
    deal = await session.scalar(select(DealRow).where(DealRow.order_id == order_id))
    if order is None or deal is None:
        raise RuntimeError("order or deal missing")
    deal.status = DEAL_STATUS_CLOSED
    payments = (await session.scalars(select(PaymentRow).where(PaymentRow.deal_id == deal.deal_id))).all()
    for payment in payments:
        if payment.status == PAYMENT_STATUS_CREATED:
            payment.status = PAYMENT_STATUS_CANCELLED
    order.status = ORDER_STATUS_CANCELLED
    _touch(order)


async def _save_payment_state(session: AsyncSession, idempotency_key: str, remote_payment) -> None:
    payment = await session.scalar(select(PaymentRow).where(PaymentRow.idempotency_key == idempotency_key))
    if payment is None:
        raise RuntimeError("payment missing")
    payment.status = remote_payment.status
    payment.last_state = json.loads(remote_payment.json())


async def _discard_yookassa_payment(payment_id: str):
    try:
        return await asyncio.to_thread(YooKassaPayment.cancel, payment_id, str(uuid.uuid4()))
    except Exception as exc:
        raise YooKassaFailed from exc


async def _refund_succeeded_payment(
    sessions: async_sessionmaker[AsyncSession],
    order_id: int,
    payment_idempotency_key: str,
    buyer_amount: Decimal,
) -> None:
    prepared = await run_serializable(
        sessions,
        lambda session: _prepare_refund(session, payment_idempotency_key),
    )
    remote = await _create_yookassa_refund(order_id, prepared.payment_id, buyer_amount, prepared.refund_idempotency_key)
    if remote.status in YOOKASSA_CANCELED:
        raise YooKassaFailed
    await run_serializable(
        sessions,
        lambda session: _save_refund(session, order_id, prepared.payment_id, remote),
    )


@dataclass(frozen=True)
class _RefundReady:
    payment_id: str
    refund_idempotency_key: str


async def _prepare_refund(session: AsyncSession, payment_idempotency_key: str) -> _RefundReady:
    payment = await session.scalar(select(PaymentRow).where(PaymentRow.idempotency_key == payment_idempotency_key))
    if payment is None:
        raise RuntimeError("payment missing")
    if payment.refund_idempotency_key is None:
        payment.refund_idempotency_key = str(uuid.uuid4())
    refund_key = payment.refund_idempotency_key
    if refund_key is None:
        raise RuntimeError("refund idempotency key missing")
    return _RefundReady(payment_id=payment.payment_id, refund_idempotency_key=refund_key)


async def _create_yookassa_refund(order_id: int, payment_id: str, buyer_amount: Decimal, idempotency_key: str):
    try:
        return await asyncio.to_thread(
            YooKassaRefund.create,
            {
                "payment_id": payment_id,
                "amount": {"value": _money(buyer_amount), "currency": "RUB"},
                "description": f"Order {order_id}",
            },
            idempotency_key,
        )
    except Exception as exc:
        raise YooKassaFailed from exc


async def _save_refund(session: AsyncSession, order_id: int, payment_id: str, remote_refund) -> None:
    existing = await session.scalar(select(RefundRow).where(RefundRow.refund_id == remote_refund.id))
    if existing is None:
        session.add(
            RefundRow(
                refund_id=remote_refund.id,
                status=remote_refund.status,
                last_state=json.loads(remote_refund.json()),
                payment_id=payment_id,
            )
        )
    deal = await session.scalar(select(DealRow).where(DealRow.order_id == order_id))
    order = await session.get(Order, order_id)
    if deal is None or order is None:
        raise RuntimeError("order or deal missing")
    deal.status = DEAL_STATUS_CLOSED
    order.status = ORDER_STATUS_CANCELLED
    _touch(order)


async def _get_or_create_order(session: AsyncSession, request: CreateOrderRequest) -> StoredOrder:
    order = await session.scalar(select(Order).where(Order.creation_idempotency_key == request.idempotency_key))
    if order is None:
        amount = items_total(request.items)
        order = Order(
            creation_idempotency_key=request.idempotency_key,
            deal_idempotency_key=str(uuid.uuid4()),
            payout_idempotency_key=str(uuid.uuid4()),
            payout_token=request.payout_token,
            user_id=request.user_id,
            delivery_type=request.delivery_type,
            status=ORDER_STATUS_CREATED,
            address=request.address,
            buyer_amount=amount,
            seller_amount=amount,
        )
        session.add(order)
        await session.flush()
        session.add_all(
            Item(
                sku_id=item.sku_id,
                order_id=order.order_id,
                name=item.name,
                image=item.image,
                price=item.price,
                quantity=item.quantity,
            )
            for item in request.items
        )
    return await _snapshot(session, order.order_id)


async def _save_deal_and_payment(session: AsyncSession, order_id: int, remote_deal) -> StoredOrder:
    order = await session.get(Order, order_id)
    if order is None:
        raise RuntimeError("order missing")
    deal = await session.scalar(select(DealRow).where(DealRow.order_id == order_id))
    if deal is None:
        deal = DealRow(
            deal_id=remote_deal.id,
            status=remote_deal.status,
            last_state=json.loads(remote_deal.json()),
            order_id=order_id,
        )
        session.add(deal)
        await session.flush()
    if order.status == ORDER_STATUS_CREATED:
        order.status = ORDER_STATUS_DEAL_CREATED
    _touch(order)
    payment = await session.scalar(select(PaymentRow).where(PaymentRow.deal_id == deal.deal_id))
    if payment is None:
        session.add(
            PaymentRow(
                payment_id=str(uuid.uuid4()),
                idempotency_key=str(uuid.uuid4()),
                status=PAYMENT_STATUS_CREATED,
                confirmation_url=None,
                last_state={},
                deal_id=deal.deal_id,
            )
        )
    return await _snapshot(session, order_id)


async def _finalize_payment(
    session: AsyncSession,
    order_id: int,
    idempotency_key: str,
    remote_payment,
    confirmation_url: str,
) -> StoredOrder:
    order = await session.get(Order, order_id)
    payment = await session.scalar(select(PaymentRow).where(PaymentRow.idempotency_key == idempotency_key))
    if order is None or payment is None:
        raise RuntimeError("order or payment missing")
    if payment.confirmation_url is None:
        session.expunge(payment)
        await session.execute(
            update(PaymentRow)
            .where(PaymentRow.idempotency_key == idempotency_key)
            .values(
                payment_id=remote_payment.id,
                status=PAYMENT_STATUS_PENDING,
                confirmation_url=confirmation_url,
                last_state=json.loads(remote_payment.json()),
            )
        )
    order = await session.get(Order, order_id)
    if order is None:
        raise RuntimeError("order missing")
    order.status = ORDER_STATUS_PAYMENT_INITIALIZED
    _touch(order)
    return await _snapshot(session, order_id)


async def _snapshot(session: AsyncSession, order_id: int) -> StoredOrder:
    order = await session.get(Order, order_id)
    if order is None:
        raise RuntimeError("order missing")
    item_rows = (await session.scalars(select(Item).where(Item.order_id == order_id))).all()
    deal_row = await session.scalar(select(DealRow).where(DealRow.order_id == order_id))
    payment_row = None
    if deal_row is not None:
        payment_row = await session.scalar(
            select(PaymentRow)
            .where(PaymentRow.deal_id == deal_row.deal_id)
            .order_by(PaymentRow.created_at.desc())
        )
    return StoredOrder(
        order_id=order.order_id,
        user_id=order.user_id,
        address=order.address,
        delivery_type=order.delivery_type,
        status=order.status,
        buyer_amount=order.buyer_amount,
        seller_amount=order.seller_amount,
        deal_idempotency_key=order.deal_idempotency_key,
        items=tuple(
            ItemOut(
                sku_id=item.sku_id,
                name=item.name,
                image=item.image,
                price=item.price,
                quantity=item.quantity,
            )
            for item in item_rows
        ),
        deal=None if deal_row is None else StoredDeal(deal_id=deal_row.deal_id, status=deal_row.status),
        payment=None
        if payment_row is None
        else StoredPayment(
            payment_id=payment_row.payment_id,
            idempotency_key=payment_row.idempotency_key,
            status=payment_row.status,
            confirmation_url=payment_row.confirmation_url,
        ),
    )


async def _create_yookassa_deal(order_id: int, idempotency_key: str):
    try:
        return await asyncio.to_thread(
            Deal.create,
            {
                "type": "safe_deal",
                "fee_moment": DEAL_FEE_MOMENT,
                "description": f"Order {order_id}",
                "metadata": {"order_id": str(order_id)},
            },
            idempotency_key,
        )
    except Exception as exc:
        raise YooKassaFailed from exc


async def _create_yookassa_payment(stored: StoredOrder, idempotency_key: str):
    if stored.deal is None:
        raise YooKassaFailed
    try:
        return await asyncio.to_thread(
            YooKassaPayment.create,
            {
                "amount": {"value": _money(stored.buyer_amount), "currency": "RUB"},
                "capture": True,
                "confirmation": {"type": "redirect", "return_url": yookassa_setup.return_url},
                "description": f"Order {stored.order_id}",
                "metadata": {"order_id": str(stored.order_id)},
                "deal": {
                    "id": stored.deal.deal_id,
                    "settlements": [
                        {
                            "type": "payout",
                            "amount": {"value": _money(stored.seller_amount), "currency": "RUB"},
                        }
                    ],
                },
            },
            idempotency_key,
        )
    except Exception as exc:
        raise YooKassaFailed from exc


def _money(amount: Decimal) -> str:
    return format(amount.quantize(Decimal("0.01")), "f")


def _order_out(stored: StoredOrder) -> OrderOut:
    if stored.deal is None or stored.payment is None or not stored.payment.confirmation_url:
        raise RuntimeError("order payment is not initialized")
    return OrderOut(
        order_id=stored.order_id,
        user_id=stored.user_id,
        address=stored.address,
        delivery_type=stored.delivery_type,
        status=stored.status,
        buyer_amount=stored.buyer_amount,
        seller_amount=stored.seller_amount,
        items=list(stored.items),
        deal=DealOut(deal_id=stored.deal.deal_id, status=stored.deal.status),
        confirmation_url=stored.payment.confirmation_url,
    )
