import asyncio
import base64
import binascii
import json
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from yookassa import Deal
from yookassa import Payment as YooKassaPayment

from db import run_serializable
from models.deal import Deal as DealRow
from models.deal_event import DealEvent
from models.item import Item
from models.order import Order
from models.order_event import OrderEvent
from models.payment import Payment as PaymentRow
from models.payment_event import PaymentEvent
from models.refund import Refund as RefundRow
from models.refund_event import RefundEvent
from schemas import (
    DebugDeal,
    DebugDealEvent,
    DebugPayment,
    DebugPaymentEvent,
    DebugRefund,
    DebugRefundEvent,
    DealPublic,
    ItemOut,
    OrderDebug,
    OrderDetail,
    OrderList,
    OrderListItem,
    PaymentPublic,
    DebugOrderEvent,
)
from service import (
    ORDER_STATUS_PAID,
    ORDER_STATUS_PAYMENT_INITIALIZED,
    PAYMENT_STATUS_CANCELLED,
    PAYMENT_STATUS_CREATED,
    YOOKASSA_SUCCEEDED,
    OrderNotFound,
    YooKassaFailed,
    _touch,
)

PAGE_SIZE = 20


class InvalidCursor(Exception):
    pass


async def list_orders(
    sessions: async_sessionmaker[AsyncSession],
    user_id: int,
    cursor: str | None,
    limit: int = PAGE_SIZE,
) -> OrderList:
    moment = None if cursor is None else _decode_cursor(cursor)
    return await run_serializable(sessions, lambda session: _list_orders(session, user_id, moment, limit))


async def get_order(sessions: async_sessionmaker[AsyncSession], order_id: int) -> OrderDetail:
    loaded = await run_serializable(sessions, lambda session: _load_refresh_target(session, order_id))
    if loaded is None:
        raise OrderNotFound
    deal_id, payment = loaded
    if deal_id is not None:
        remote_deal = await _fetch_deal(deal_id)
        await run_serializable(sessions, lambda session: _save_deal_state(session, deal_id, remote_deal))
    if payment is not None:
        remote_payment = await _fetch_payment(payment[0])
        idempotency_key = payment[1]
        await run_serializable(
            sessions,
            lambda session: _save_refreshed_payment(session, order_id, idempotency_key, remote_payment),
        )
    detail = await run_serializable(sessions, lambda session: _order_detail(session, order_id))
    if detail is None:
        raise OrderNotFound
    return detail


async def debug_order(sessions: async_sessionmaker[AsyncSession], order_id: int) -> OrderDebug:
    result = await run_serializable(sessions, lambda session: _order_debug(session, order_id))
    if result is None:
        raise OrderNotFound
    return result


async def _list_orders(session: AsyncSession, user_id: int, moment: datetime | None, limit: int) -> OrderList:
    query = select(Order).where(Order.user_id == user_id)
    if moment is not None:
        query = query.where(Order.updated_at < moment)
    rows = (await session.scalars(query.order_by(Order.updated_at.desc()).limit(limit + 1))).all()
    page = rows[:limit]
    images = await _images_by_order(session, [row.order_id for row in page])
    next_cursor = encode_cursor(page[-1].updated_at) if len(rows) > limit and page else None
    return OrderList(
        orders=[OrderListItem(order_id=row.order_id, images=images.get(row.order_id, []), status=row.status) for row in page],
        next_cursor=next_cursor,
    )


async def _images_by_order(session: AsyncSession, order_ids: list[int]) -> dict[int, list[str]]:
    if not order_ids:
        return {}
    rows = (await session.scalars(select(Item).where(Item.order_id.in_(order_ids)).order_by(Item.sku_id))).all()
    images: dict[int, list[str]] = {}
    for item in rows:
        images.setdefault(item.order_id, []).append(item.image)
    return images


async def _load_refresh_target(session: AsyncSession, order_id: int) -> tuple[str | None, tuple[str, str] | None] | None:
    order = await session.get(Order, order_id)
    if order is None:
        return None
    deal = await session.scalar(select(DealRow).where(DealRow.order_id == order_id))
    payment = None
    if deal is not None:
        row = await session.scalar(
            select(PaymentRow).where(PaymentRow.deal_id == deal.deal_id).order_by(PaymentRow.created_at.desc())
        )
        if row is not None and row.status not in {PAYMENT_STATUS_CREATED, PAYMENT_STATUS_CANCELLED}:
            payment = (row.payment_id, row.idempotency_key)
    return (None if deal is None else deal.deal_id, payment)


async def _save_deal_state(session: AsyncSession, deal_id: str, remote_deal) -> None:
    deal = await session.get(DealRow, deal_id)
    if deal is None:
        raise RuntimeError("deal missing")
    deal.status = remote_deal.status
    deal.last_state = json.loads(remote_deal.json())


async def _save_refreshed_payment(session: AsyncSession, order_id: int, idempotency_key: str, remote_payment) -> None:
    payment = await session.scalar(select(PaymentRow).where(PaymentRow.idempotency_key == idempotency_key))
    order = await session.get(Order, order_id)
    if payment is None or order is None:
        raise RuntimeError("order or payment missing")
    payment.status = remote_payment.status
    payment.last_state = json.loads(remote_payment.json())
    if remote_payment.status == YOOKASSA_SUCCEEDED and order.status == ORDER_STATUS_PAYMENT_INITIALIZED:
        order.status = ORDER_STATUS_PAID
        _touch(order)


async def _order_detail(session: AsyncSession, order_id: int) -> OrderDetail | None:
    order = await session.get(Order, order_id)
    if order is None:
        return None
    items = (await session.scalars(select(Item).where(Item.order_id == order_id).order_by(Item.sku_id))).all()
    deal = await session.scalar(select(DealRow).where(DealRow.order_id == order_id))
    payment = None
    if deal is not None:
        payment = await session.scalar(
            select(PaymentRow).where(PaymentRow.deal_id == deal.deal_id).order_by(PaymentRow.created_at.desc())
        )
    return OrderDetail(
        order_id=order.order_id,
        user_id=order.user_id,
        status=order.status,
        delivery_type=order.delivery_type,
        address=order.address,
        buyer_amount=order.buyer_amount,
        seller_amount=order.seller_amount,
        receival_code=order.receival_code,
        created_at=order.created_at,
        updated_at=order.updated_at,
        items=[_item_out(item) for item in items],
        deal=None if deal is None else DealPublic(deal_id=deal.deal_id, status=deal.status),
        payment=None
        if payment is None
        else PaymentPublic(
            payment_id=payment.payment_id,
            status=payment.status,
            confirmation_url=payment.confirmation_url,
        ),
    )


async def _order_debug(session: AsyncSession, order_id: int) -> OrderDebug | None:
    order = await session.get(Order, order_id)
    if order is None:
        return None
    items = (await session.scalars(select(Item).where(Item.order_id == order_id).order_by(Item.sku_id))).all()
    deal = await session.scalar(select(DealRow).where(DealRow.order_id == order_id))
    payments = []
    refunds = []
    payment_events = []
    refund_events = []
    if deal is not None:
        payments = (
            await session.scalars(select(PaymentRow).where(PaymentRow.deal_id == deal.deal_id).order_by(PaymentRow.created_at))
        ).all()
        payment_ids = [row.payment_id for row in payments]
        if payment_ids:
            payment_events = (
                await session.scalars(select(PaymentEvent).where(PaymentEvent.payment_id.in_(payment_ids)).order_by(PaymentEvent.id))
            ).all()
            refunds = (
                await session.scalars(select(RefundRow).where(RefundRow.payment_id.in_(payment_ids)))
            ).all()
            refund_ids = [row.refund_id for row in refunds]
            if refund_ids:
                refund_events = (
                    await session.scalars(
                        select(RefundEvent).where(RefundEvent.refund_id.in_(refund_ids)).order_by(RefundEvent.id)
                    )
                ).all()
    order_events = (
        await session.scalars(select(OrderEvent).where(OrderEvent.order_id == order_id).order_by(OrderEvent.id))
    ).all()
    deal_events = []
    if deal is not None:
        deal_events = (
            await session.scalars(select(DealEvent).where(DealEvent.deal_id == deal.deal_id).order_by(DealEvent.id))
        ).all()
    return OrderDebug(
        order_id=order.order_id,
        creation_idempotency_key=order.creation_idempotency_key,
        deal_idempotency_key=order.deal_idempotency_key,
        payout_idempotency_key=order.payout_idempotency_key,
        payout_token=order.payout_token,
        user_id=order.user_id,
        delivery_type=order.delivery_type,
        status=order.status,
        receival_code=order.receival_code,
        address=order.address,
        buyer_amount=order.buyer_amount,
        seller_amount=order.seller_amount,
        created_at=order.created_at,
        updated_at=order.updated_at,
        items=[_item_out(item) for item in items],
        deal=None
        if deal is None
        else DebugDeal(
            deal_id=deal.deal_id,
            status=deal.status,
            last_state=deal.last_state,
            order_id=deal.order_id,
            created_at=deal.created_at,
        ),
        payments=[
            DebugPayment(
                payment_id=row.payment_id,
                idempotency_key=row.idempotency_key,
                refund_idempotency_key=row.refund_idempotency_key,
                status=row.status,
                confirmation_url=row.confirmation_url,
                last_state=row.last_state,
                deal_id=row.deal_id,
                created_at=row.created_at,
            )
            for row in payments
        ],
        refunds=[
            DebugRefund(refund_id=row.refund_id, status=row.status, last_state=row.last_state, payment_id=row.payment_id)
            for row in refunds
        ],
        order_events=[
            DebugOrderEvent(
                id=row.id,
                order_id=row.order_id,
                old_status=row.old_status,
                new_status=row.new_status,
                created_at=row.created_at,
            )
            for row in order_events
        ],
        deal_events=[
            DebugDealEvent(
                id=row.id,
                deal_id=row.deal_id,
                old_status=row.old_status,
                new_status=row.new_status,
                created_at=row.created_at,
            )
            for row in deal_events
        ],
        payment_events=[
            DebugPaymentEvent(
                id=row.id,
                payment_id=row.payment_id,
                old_status=row.old_status,
                new_status=row.new_status,
                created_at=row.created_at,
            )
            for row in payment_events
        ],
        refund_events=[
            DebugRefundEvent(
                id=row.id,
                refund_id=row.refund_id,
                old_status=row.old_status,
                new_status=row.new_status,
                created_at=row.created_at,
            )
            for row in refund_events
        ],
    )


def _item_out(item: Item) -> ItemOut:
    return ItemOut(sku_id=item.sku_id, name=item.name, image=item.image, price=item.price, quantity=item.quantity)


def encode_cursor(updated_at: datetime) -> str:
    payload = json.dumps({"last-updated-at": updated_at.isoformat()})
    return base64.b64encode(payload.encode()).decode()


def _decode_cursor(cursor: str) -> datetime:
    try:
        payload = json.loads(base64.b64decode(cursor, validate=True))
        moment = datetime.fromisoformat(payload["last-updated-at"])
    except (ValueError, KeyError, json.JSONDecodeError, UnicodeDecodeError, binascii.Error):
        raise InvalidCursor from None
    if moment.tzinfo is None:
        raise InvalidCursor
    return moment


async def _fetch_deal(deal_id: str):
    try:
        return await asyncio.to_thread(Deal.find_one, deal_id)
    except Exception as exc:
        raise YooKassaFailed from exc


async def _fetch_payment(payment_id: str):
    try:
        return await asyncio.to_thread(YooKassaPayment.find_one, payment_id)
    except Exception as exc:
        raise YooKassaFailed from exc
