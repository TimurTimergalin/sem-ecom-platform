import asyncio
import json
import secrets
import uuid

import yookassa_setup
from dataclasses import dataclass
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from yookassa import Payment as YooKassaPayment
from yookassa import Refund as YooKassaRefund

from db import run_serializable
from models.deal import Deal as DealRow
from models.item import Item
from models.multi_order import MultiOrder
from models.order import Order
from models.payment import Payment as PaymentRow
from models.refund import Refund as RefundRow
from schemas import (
    CancelOut,
    CompleteOut,
    CompleteRequest,
    ConfirmOut,
    CreateOrderRequest,
    GroupOrderOut,
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
UNPAID_ORDER_STATUSES = {
    ORDER_STATUS_CREATED,
    ORDER_STATUS_DEAL_CREATED,
    ORDER_STATUS_PAYMENT_INITIALIZED,
}
RESUMABLE_ORDER_STATUSES = UNPAID_ORDER_STATUSES
DEAL_STATUS_CLOSED = "closed"
SETTLED_ORDER_STATUSES = {
    ORDER_STATUS_PAID,
    ORDER_STATUS_DELIVERED,
    ORDER_STATUS_COMPLETED,
    ORDER_STATUS_CANCELLED,
}
DESCRIPTION_LIMIT = 128


class YooKassaFailed(Exception):
    pass


class OrderNotFound(Exception):
    pass


class AccountRequired(Exception):
    pass


class StateMismatch(Exception):
    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


def _touch(order: Order) -> None:
    order.updated_at = func.now()


def _touch_multi(multi: MultiOrder) -> None:
    multi.updated_at = func.now()


@dataclass(frozen=True)
class StoredLine:
    order_id: str
    seller_id: str
    status: str
    buyer_amount: Decimal
    seller_amount: Decimal
    address: str
    delivery_type: str
    yookassa_account_id: str | None
    items: tuple[ItemOut, ...]


@dataclass(frozen=True)
class StoredCheckout:
    multi_order_id: str
    user_id: str
    focus_order_id: str
    payment_id: str | None
    payment_status: str
    confirmation_url: str | None
    payment_idempotency_key: str
    lines: tuple[StoredLine, ...]


def _require_accounts(request: CreateOrderRequest) -> None:
    for group in request.groups:
        if not group.yookassa_account_id.strip():
            raise AccountRequired


async def create_order(
    sessions: async_sessionmaker[AsyncSession],
    request: CreateOrderRequest,
) -> OrderOut:
    _require_accounts(request)
    checkout = await run_serializable(sessions, lambda session: _get_or_create_checkout(session, request))
    checkout = await _ensure_payment(sessions, checkout)
    return _order_out(checkout)


async def repay_order(
    sessions: async_sessionmaker[AsyncSession],
    order_id: str,
) -> OrderOut:
    checkout = await run_serializable(sessions, lambda session: _load_checkout_by_order(session, order_id))
    if checkout is None:
        raise OrderNotFound
    focus = _focus(checkout)
    if focus.status not in RESUMABLE_ORDER_STATUSES:
        raise StateMismatch(f"order status is {focus.status}")
    if (
        checkout.payment_status == PAYMENT_STATUS_PENDING
        and checkout.payment_id
        and not yookassa_setup.fake
    ):
        remote = await _fetch_yookassa_payment(checkout.payment_id)
        multi_id = checkout.multi_order_id
        focus_id = checkout.focus_order_id
        checkout = await run_serializable(
            sessions,
            lambda session: _apply_remote_payment(session, multi_id, focus_id, remote),
        )
        if checkout.payment_status == YOOKASSA_SUCCEEDED:
            return _order_out(checkout)
        if checkout.payment_status not in YOOKASSA_CANCELED and checkout.confirmation_url:
            return _order_out(checkout)
    checkout = await _ensure_payment(sessions, checkout)
    return _order_out(checkout)


async def confirm_order(
    sessions: async_sessionmaker[AsyncSession],
    order_id: str,
) -> ConfirmOut:
    result = await run_serializable(sessions, lambda session: _confirm_paid_order(session, order_id))
    if result is None:
        raise OrderNotFound
    return result


async def _confirm_paid_order(session: AsyncSession, order_id: str) -> ConfirmOut | None:
    order = await session.get(Order, order_id)
    if order is None:
        return None
    if order.multi_order_id:
        await promote_paid_multi(session, order.multi_order_id)
    if order.status != ORDER_STATUS_PAID:
        raise StateMismatch(f"order status is {order.status}")
    receival_code = f"{secrets.randbelow(1_000_000):06d}"
    order.status = ORDER_STATUS_DELIVERED
    order.receival_code = receival_code
    _touch(order)
    return ConfirmOut(order_id=order.order_id, status=order.status, receival_code=receival_code)


async def complete_order(
    sessions: async_sessionmaker[AsyncSession],
    order_id: str,
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
    await run_serializable(sessions, lambda session: _mark_completed(session, order_id))
    return CompleteOut(order_id=order_id, status=ORDER_STATUS_COMPLETED)


async def _prepare_completion(
    session: AsyncSession,
    order_id: str,
    receival_code: str,
) -> bool | Skipped | None:
    order = await session.get(Order, order_id)
    if order is None:
        return None
    if order.status != ORDER_STATUS_DELIVERED:
        raise StateMismatch(f"order status is {order.status}")
    saved_code = order.receival_code or ""
    if not secrets.compare_digest(saved_code, receival_code):
        return Skipped(reason="receival code does not match")
    return True


async def _mark_completed(session: AsyncSession, order_id: str) -> None:
    order = await session.get(Order, order_id)
    if order is None:
        raise RuntimeError("order missing")
    if order.status == ORDER_STATUS_DELIVERED:
        order.status = ORDER_STATUS_COMPLETED
        _touch(order)


async def cancel_order(
    sessions: async_sessionmaker[AsyncSession],
    order_id: str,
) -> CancelOut:
    view = await run_serializable(sessions, lambda session: _load_cancel_view(session, order_id))
    if view is None:
        raise OrderNotFound
    if view.status in {ORDER_STATUS_COMPLETED, ORDER_STATUS_CANCELLED}:
        raise StateMismatch(f"order status is {view.status}")
    if view.multi_order_id is not None:
        return await _cancel_multi(sessions, order_id, view)
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


async def _cancel_multi(
    sessions: async_sessionmaker[AsyncSession],
    order_id: str,
    view: "_CancelView",
) -> CancelOut:
    if view.payment_status == YOOKASSA_SUCCEEDED:
        await _refund_seller_transfer(order_id, view)
        await run_serializable(sessions, lambda session: _cancel_order_row(session, order_id))
        return CancelOut(order_id=order_id, status=ORDER_STATUS_CANCELLED)

    if view.payment_status == PAYMENT_STATUS_PENDING and view.payment_id and not yookassa_setup.fake:
        remote = await _fetch_yookassa_payment(view.payment_id)
        if remote.status == PAYMENT_STATUS_PENDING:
            remote = await _discard_yookassa_payment(view.payment_id)
        if remote.status == YOOKASSA_SUCCEEDED:
            multi_id = view.multi_order_id
            await run_serializable(
                sessions,
                lambda session: save_remote_multi_payment(session, multi_id, remote),
            )
            await _refund_seller_transfer(order_id, view)
            await run_serializable(sessions, lambda session: _cancel_order_row(session, order_id))
            return CancelOut(order_id=order_id, status=ORDER_STATUS_CANCELLED)
        if remote.status not in YOOKASSA_CANCELED:
            raise YooKassaFailed

    if view.payment_status == PAYMENT_STATUS_PENDING or (
        view.payment_id and view.payment_status not in YOOKASSA_CANCELED | {PAYMENT_STATUS_CREATED}
    ):
        multi_id = view.multi_order_id
        await run_serializable(
            sessions,
            lambda session: _cancel_order_and_open_payment(session, order_id, multi_id),
        )
        return CancelOut(order_id=order_id, status=ORDER_STATUS_CANCELLED)

    await run_serializable(sessions, lambda session: _cancel_order_row(session, order_id))
    return CancelOut(order_id=order_id, status=ORDER_STATUS_CANCELLED)


async def _refund_seller_transfer(order_id: str, view: "_CancelView") -> None:
    if yookassa_setup.fake:
        return
    if not view.payment_id or not view.yookassa_account_id:
        raise AccountRequired
    try:
        remote = await asyncio.to_thread(
            YooKassaRefund.create,
            {
                "payment_id": view.payment_id,
                "amount": {"value": _money(view.buyer_amount), "currency": "RUB"},
                "description": f"Order {order_id}",
                "sources": [
                    {
                        "account_id": view.yookassa_account_id,
                        "amount": {"value": _money(view.buyer_amount), "currency": "RUB"},
                    }
                ],
            },
            order_id,
        )
    except Exception as exc:
        raise YooKassaFailed from exc
    if remote.status in YOOKASSA_CANCELED:
        raise YooKassaFailed


async def _cancel_order_and_open_payment(session: AsyncSession, order_id: str, multi_id: str | None) -> None:
    await _cancel_order_row(session, order_id)
    if multi_id is None:
        return
    multi = await session.get(MultiOrder, multi_id)
    if multi is None:
        raise RuntimeError("multi order missing")
    if multi.payment_status == YOOKASSA_SUCCEEDED:
        return
    multi.payment_status = "canceled"
    _touch_multi(multi)


async def promote_paid_multi(session: AsyncSession, multi_id: str) -> None:
    multi = await session.get(MultiOrder, multi_id)
    if multi is None or multi.payment_status != YOOKASSA_SUCCEEDED:
        return
    orders = (await session.scalars(select(Order).where(Order.multi_order_id == multi_id))).all()
    for order in orders:
        if order.status in UNPAID_ORDER_STATUSES:
            order.status = ORDER_STATUS_PAID
            _touch(order)


async def save_remote_multi_payment(session: AsyncSession, multi_id: str, remote_payment) -> None:
    multi = await session.get(MultiOrder, multi_id)
    if multi is None:
        raise RuntimeError("multi order missing")
    remote_id = getattr(remote_payment, "id", None)
    if remote_id:
        multi.payment_id = remote_id
    multi.payment_status = remote_payment.status
    payload = dict(multi.yookassa_payload or {})
    payload["remote"] = json.loads(remote_payment.json())
    multi.yookassa_payload = payload
    _touch_multi(multi)
    if remote_payment.status == YOOKASSA_SUCCEEDED:
        await promote_paid_multi(session, multi_id)


async def _ensure_payment(
    sessions: async_sessionmaker[AsyncSession],
    checkout: StoredCheckout,
) -> StoredCheckout:
    if checkout.payment_status in YOOKASSA_CANCELED:
        multi_id = checkout.multi_order_id
        focus_id = checkout.focus_order_id
        checkout = await run_serializable(
            sessions,
            lambda session: _rotate_payment_attempt(session, multi_id, focus_id),
        )
    if checkout.payment_status == YOOKASSA_SUCCEEDED and checkout.confirmation_url:
        return checkout
    if checkout.payment_status == PAYMENT_STATUS_PENDING and checkout.confirmation_url:
        return checkout
    payable = [line for line in checkout.lines if line.status != ORDER_STATUS_CANCELLED]
    if not payable:
        raise StateMismatch("order status is CANCELLED")
    if not checkout.payment_idempotency_key:
        multi_id = checkout.multi_order_id
        focus_id = checkout.focus_order_id
        checkout = await run_serializable(
            sessions,
            lambda session: _ensure_payment_key(session, multi_id, focus_id),
        )
    remote = await _create_yookassa_payment(checkout)
    confirmation = getattr(remote, "confirmation", None)
    confirmation_url = None if confirmation is None else getattr(confirmation, "confirmation_url", None)
    if not getattr(remote, "id", None) or not confirmation_url:
        raise YooKassaFailed
    multi_id = checkout.multi_order_id
    focus_id = checkout.focus_order_id
    return await run_serializable(
        sessions,
        lambda session: _save_issued_payment(session, multi_id, focus_id, remote, confirmation_url),
    )


async def _apply_remote_payment(session: AsyncSession, multi_id: str, focus_order_id: str, remote_payment) -> StoredCheckout:
    await save_remote_multi_payment(session, multi_id, remote_payment)
    return await _load_checkout(session, multi_id, focus_order_id)


async def _get_or_create_checkout(session: AsyncSession, request: CreateOrderRequest) -> StoredCheckout:
    existing = await session.scalar(select(MultiOrder).where(MultiOrder.idempotency_key == request.idempotency_key))
    if existing is None:
        multi = MultiOrder(
            id=str(uuid.uuid4()),
            user_id=request.user_id,
            payment_id=None,
            payment_status=PAYMENT_STATUS_CREATED,
            confirmation_url=None,
            idempotency_key=request.idempotency_key,
            yookassa_payload={"payment_idempotency_key": str(uuid.uuid4())},
        )
        session.add(multi)
        await session.flush()
        for index, group in enumerate(request.groups):
            amount = items_total(group.items)
            order = Order(
                order_id=str(uuid.uuid4()),
                creation_idempotency_key=f"{multi.id}:{index:04d}",
                deal_idempotency_key=str(uuid.uuid4()),
                payout_idempotency_key=str(uuid.uuid4()),
                payout_token=None,
                user_id=request.user_id,
                seller_id=group.seller_id,
                delivery_type=group.delivery_type,
                status=ORDER_STATUS_CREATED,
                address=group.address,
                buyer_amount=amount,
                seller_amount=amount,
                multi_order_id=multi.id,
                yookassa_account_id=group.yookassa_account_id.strip(),
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
                for item in group.items
            )
        existing = multi
    lines = (
        await session.scalars(
            select(Order).where(Order.multi_order_id == existing.id).order_by(Order.creation_idempotency_key)
        )
    ).all()
    if not lines:
        raise RuntimeError("multi order has no orders")
    return await _load_checkout(session, existing.id, lines[0].order_id)


async def _load_checkout_by_order(session: AsyncSession, order_id: str) -> StoredCheckout | None:
    order = await session.get(Order, order_id)
    if order is None:
        return None
    if order.multi_order_id is None:
        raise StateMismatch("order has no multi order")
    return await _load_checkout(session, order.multi_order_id, order.order_id)


async def _load_checkout(session: AsyncSession, multi_id: str, focus_order_id: str) -> StoredCheckout:
    multi = await session.get(MultiOrder, multi_id)
    if multi is None:
        raise RuntimeError("multi order missing")
    if multi.payment_status == YOOKASSA_SUCCEEDED:
        await promote_paid_multi(session, multi_id)
    order_rows = (
        await session.scalars(
            select(Order).where(Order.multi_order_id == multi_id).order_by(Order.creation_idempotency_key)
        )
    ).all()
    lines: list[StoredLine] = []
    for row in order_rows:
        item_rows = (
            await session.scalars(select(Item).where(Item.order_id == row.order_id).order_by(Item.sku_id))
        ).all()
        lines.append(
            StoredLine(
                order_id=row.order_id,
                seller_id=row.seller_id,
                status=row.status,
                buyer_amount=row.buyer_amount,
                seller_amount=row.seller_amount,
                address=row.address,
                delivery_type=row.delivery_type,
                yookassa_account_id=row.yookassa_account_id,
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
            )
        )
    payload = multi.yookassa_payload or {}
    return StoredCheckout(
        multi_order_id=multi.id,
        user_id=multi.user_id,
        focus_order_id=focus_order_id,
        payment_id=multi.payment_id,
        payment_status=multi.payment_status,
        confirmation_url=multi.confirmation_url,
        payment_idempotency_key=str(payload.get("payment_idempotency_key") or ""),
        lines=tuple(lines),
    )


async def _rotate_payment_attempt(session: AsyncSession, multi_id: str, focus_order_id: str) -> StoredCheckout:
    multi = await session.get(MultiOrder, multi_id)
    if multi is None:
        raise RuntimeError("multi order missing")
    payload = dict(multi.yookassa_payload or {})
    payload["payment_idempotency_key"] = str(uuid.uuid4())
    payload.pop("remote", None)
    multi.yookassa_payload = payload
    multi.payment_id = None
    multi.payment_status = PAYMENT_STATUS_CREATED
    multi.confirmation_url = None
    _touch_multi(multi)
    return await _load_checkout(session, multi_id, focus_order_id)


async def _ensure_payment_key(session: AsyncSession, multi_id: str, focus_order_id: str) -> StoredCheckout:
    multi = await session.get(MultiOrder, multi_id)
    if multi is None:
        raise RuntimeError("multi order missing")
    payload = dict(multi.yookassa_payload or {})
    if not payload.get("payment_idempotency_key"):
        payload["payment_idempotency_key"] = str(uuid.uuid4())
        multi.yookassa_payload = payload
    return await _load_checkout(session, multi_id, focus_order_id)


async def _save_issued_payment(
    session: AsyncSession,
    multi_id: str,
    focus_order_id: str,
    remote_payment,
    confirmation_url: str,
) -> StoredCheckout:
    multi = await session.get(MultiOrder, multi_id)
    if multi is None:
        raise RuntimeError("multi order missing")
    multi.payment_id = remote_payment.id
    multi.payment_status = YOOKASSA_SUCCEEDED if remote_payment.status == YOOKASSA_SUCCEEDED else PAYMENT_STATUS_PENDING
    multi.confirmation_url = confirmation_url
    payload = dict(multi.yookassa_payload or {})
    payload["remote"] = json.loads(remote_payment.json())
    multi.yookassa_payload = payload
    _touch_multi(multi)
    orders = (await session.scalars(select(Order).where(Order.multi_order_id == multi_id))).all()
    for order in orders:
        if order.status in SETTLED_ORDER_STATUSES:
            continue
        order.status = (
            ORDER_STATUS_PAID if multi.payment_status == YOOKASSA_SUCCEEDED else ORDER_STATUS_PAYMENT_INITIALIZED
        )
        _touch(order)
    return await _load_checkout(session, multi_id, focus_order_id)


async def _create_yookassa_payment(checkout: StoredCheckout):
    payable = [line for line in checkout.lines if line.status != ORDER_STATUS_CANCELLED]
    if not payable:
        raise YooKassaFailed
    for line in payable:
        if not (line.yookassa_account_id or "").strip():
            raise AccountRequired
    total = sum((line.buyer_amount for line in payable), Decimal("0"))
    if yookassa_setup.fake:
        return yookassa_setup.fake_payment(payable[0].order_id)
    try:
        return await asyncio.to_thread(
            YooKassaPayment.create,
            {
                "amount": {"value": _money(total), "currency": "RUB"},
                "capture": True,
                "confirmation": {"type": "redirect", "return_url": yookassa_setup.return_url},
                "description": _description(payable),
                "transfers": [
                    {
                        "account_id": line.yookassa_account_id,
                        "amount": {"value": _money(line.buyer_amount), "currency": "RUB"},
                        "metadata": {"order_id": line.order_id},
                    }
                    for line in payable
                ],
            },
            checkout.payment_idempotency_key,
        )
    except AccountRequired:
        raise
    except Exception as exc:
        raise YooKassaFailed from exc


def _description(lines: list[StoredLine]) -> str:
    text = ", ".join(f"{line.seller_id} {_money(line.buyer_amount)}" for line in lines)
    if len(text) <= DESCRIPTION_LIMIT:
        return text
    return text[: DESCRIPTION_LIMIT - 3] + "..."


def _money(amount: Decimal) -> str:
    return format(amount.quantize(Decimal("0.01")), "f")


def _focus(checkout: StoredCheckout) -> StoredLine:
    for line in checkout.lines:
        if line.order_id == checkout.focus_order_id:
            return line
    raise RuntimeError("focus order missing")


def _order_out(checkout: StoredCheckout) -> OrderOut:
    if not checkout.confirmation_url:
        raise RuntimeError("order payment is not initialized")
    focus = _focus(checkout)
    return OrderOut(
        order_id=focus.order_id,
        user_id=checkout.user_id,
        seller_id=focus.seller_id,
        address=focus.address,
        delivery_type=focus.delivery_type,
        status=focus.status,
        buyer_amount=focus.buyer_amount,
        seller_amount=focus.seller_amount,
        items=list(focus.items),
        deal=None,
        confirmation_url=checkout.confirmation_url,
        multi_order_id=checkout.multi_order_id,
        orders=[
            GroupOrderOut(
                order_id=line.order_id,
                seller_id=line.seller_id,
                status=line.status,
                buyer_amount=line.buyer_amount,
            )
            for line in checkout.lines
        ],
    )


async def fake_mark_paid(sessions: async_sessionmaker[AsyncSession], order_id: str) -> None:
    if not yookassa_setup.fake:
        raise OrderNotFound
    updated = await run_serializable(sessions, lambda session: _fake_mark_paid(session, order_id))
    if updated is None:
        raise OrderNotFound


async def _fake_mark_paid(session: AsyncSession, order_id: str) -> str | None:
    order = await session.get(Order, order_id)
    if order is None:
        return None
    if order.multi_order_id:
        return await _fake_mark_multi(session, order)
    if order.status in {ORDER_STATUS_PAID, ORDER_STATUS_DELIVERED, ORDER_STATUS_COMPLETED}:
        return order.order_id
    if order.status != ORDER_STATUS_PAYMENT_INITIALIZED:
        raise StateMismatch("payment is not ready")
    deal = await session.scalar(select(DealRow).where(DealRow.order_id == order_id))
    payment = None
    if deal is not None:
        payment = await session.scalar(
            select(PaymentRow).where(PaymentRow.deal_id == deal.deal_id).order_by(PaymentRow.created_at.desc())
        )
    if payment is None:
        raise StateMismatch("order has no payment")
    payment.status = YOOKASSA_SUCCEEDED
    payment.last_state = {"id": payment.payment_id, "status": YOOKASSA_SUCCEEDED, "fake": True}
    order.status = ORDER_STATUS_PAID
    _touch(order)
    return order.order_id


async def _fake_mark_multi(session: AsyncSession, order: Order) -> str:
    if order.multi_order_id is None:
        raise StateMismatch("payment is not ready")
    multi = await session.get(MultiOrder, order.multi_order_id)
    if multi is None:
        raise StateMismatch("payment is not ready")
    if multi.payment_status == PAYMENT_STATUS_CREATED and not multi.confirmation_url and not multi.payment_id:
        raise StateMismatch("payment is not ready")
    siblings = (await session.scalars(select(Order).where(Order.multi_order_id == multi.id))).all()
    open_orders = [row for row in siblings if row.status != ORDER_STATUS_CANCELLED]
    if not open_orders:
        raise StateMismatch("payment is not ready")
    for row in open_orders:
        if row.status in UNPAID_ORDER_STATUSES:
            row.status = ORDER_STATUS_PAID
            _touch(row)
    multi.payment_status = YOOKASSA_SUCCEEDED
    if not multi.payment_id:
        multi.payment_id = f"pay-{multi.id}"
    payload = dict(multi.yookassa_payload or {})
    payload["remote"] = {"id": multi.payment_id, "status": YOOKASSA_SUCCEEDED, "fake": True}
    multi.yookassa_payload = payload
    _touch_multi(multi)
    return order.order_id


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
    multi_order_id: str | None = None
    payment_id: str | None = None
    payment_status: str | None = None
    yookassa_account_id: str | None = None


async def _load_cancel_view(session: AsyncSession, order_id: str) -> _CancelView | None:
    order = await session.get(Order, order_id)
    if order is None:
        return None
    multi = await session.get(MultiOrder, order.multi_order_id) if order.multi_order_id else None
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
        multi_order_id=order.multi_order_id,
        payment_id=None if multi is None else multi.payment_id,
        payment_status=None if multi is None else multi.payment_status,
        yookassa_account_id=order.yookassa_account_id,
    )


async def _cancel_order_row(session: AsyncSession, order_id: str) -> None:
    order = await session.get(Order, order_id)
    if order is None:
        raise RuntimeError("order missing")
    order.status = ORDER_STATUS_CANCELLED
    _touch(order)


async def _close_unpaid_deal(session: AsyncSession, order_id: str) -> None:
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


async def _fetch_yookassa_payment(payment_id: str):
    if yookassa_setup.fake:
        return yookassa_setup.LocalGatewayObject(id=payment_id, status=PAYMENT_STATUS_PENDING)
    try:
        return await asyncio.to_thread(YooKassaPayment.find_one, payment_id)
    except Exception as exc:
        raise YooKassaFailed from exc


async def _discard_yookassa_payment(payment_id: str):
    if yookassa_setup.fake:
        return yookassa_setup.LocalGatewayObject(id=payment_id, status="canceled")
    try:
        return await asyncio.to_thread(YooKassaPayment.cancel, payment_id, str(uuid.uuid4()))
    except Exception as exc:
        raise YooKassaFailed from exc


async def _refund_succeeded_payment(
    sessions: async_sessionmaker[AsyncSession],
    order_id: str,
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


async def _create_yookassa_refund(order_id: str, payment_id: str, buyer_amount: Decimal, idempotency_key: str):
    if yookassa_setup.fake:
        return yookassa_setup.fake_refund(order_id)
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


async def _save_refund(session: AsyncSession, order_id: str, payment_id: str, remote_refund) -> None:
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
