from datetime import datetime, timezone
from decimal import Decimal

import pytest
from sqlalchemy import select

from conftest import deal_response
from models import Base
from models.base import AwareDateTime
from models.order import Order
from reads import InvalidCursor, debug_order, encode_cursor, get_order, list_orders
from schemas import CreateOrderRequest, ItemIn
from service import (
    CompleteRequest,
    StateMismatch,
    cancel_order,
    complete_order,
    confirm_order,
    create_order,
)


def _request(key="key-1", user_id=5):
    return CreateOrderRequest(
        items=[ItemIn(sku_id=1, name="Cup", image="https://img.example/cup.png", price=Decimal("10.00"), quantity=2)],
        user_id=user_id,
        address="Moscow",
        delivery_type="pickup",
        idempotency_key=key,
        payout_token="seller-card-token",
    )


def test_datetime_columns_require_a_timezone():
    dated = [column for table in Base.metadata.tables.values() for column in table.columns if column.name.endswith("_at")]
    assert dated
    assert all(isinstance(column.type, AwareDateTime) for column in dated)
    with pytest.raises(ValueError):
        AwareDateTime().process_bind_param(datetime(2026, 1, 1), None)


async def test_create_order_uses_a_separate_payout_key(sessions, yookassa):
    created = await create_order(sessions, _request())

    async with sessions() as session:
        order = await session.get(Order, created.order_id)

    assert order.payout_idempotency_key != order.deal_idempotency_key
    assert order.created_at.tzinfo is not None
    assert order.updated_at.tzinfo is not None
    deal_call = next(call for call in yookassa if call[0] == "deal")
    payment_call = next(call for call in yookassa if call[0] == "payment")
    assert deal_call[1] == order.deal_idempotency_key
    assert payment_call[1] != order.payout_idempotency_key
    assert payment_call[1] != order.deal_idempotency_key
    assert created.confirmation_url == "https://pay.example/1"
    assert "last_state" not in created.model_dump()


async def test_repeated_create_does_not_open_another_deal(sessions, yookassa):
    first = await create_order(sessions, _request())
    second = await create_order(sessions, _request())

    assert second.order_id == first.order_id
    assert [call for call in yookassa if call[0] == "deal"] == [yookassa[0]]


async def test_confirm_rejects_an_order_that_is_not_paid(sessions, yookassa):
    created = await create_order(sessions, _request())

    with pytest.raises(StateMismatch, match="PAYMENT_INITIALIZED"):
        await confirm_order(sessions, created.order_id)


async def test_confirm_stores_a_receival_code(sessions, yookassa):
    created = await create_order(sessions, _request())
    async with sessions() as session:
        async with session.begin():
            order = await session.get(Order, created.order_id)
            order.status = "PAID"

    confirmed = await confirm_order(sessions, created.order_id)

    assert confirmed.status == "DELIVERED"
    assert len(confirmed.receival_code) == 6
    assert confirmed.receival_code.isdigit()


async def test_complete_sends_the_order_payout_key(sessions, yookassa):
    created = await create_order(sessions, _request())
    async with sessions() as session:
        async with session.begin():
            order = await session.get(Order, created.order_id)
            order.status = "DELIVERED"
            order.receival_code = "048213"
            payout_key = order.payout_idempotency_key
            deal_key = order.deal_idempotency_key
            payout_token = order.payout_token

    completed = await complete_order(sessions, created.order_id, CompleteRequest(receival_code="048213"))

    payout_call = next(call for call in yookassa if call[0] == "payout")
    assert payout_call[1] == payout_key
    assert payout_call[1] != deal_key
    assert payout_call[2]["payout_token"] == payout_token
    assert completed.status == "COMPLETED"


async def test_cancel_created_order_does_not_call_yookassa(sessions, yookassa):
    async with sessions() as session:
        async with session.begin():
            session.add(
                Order(
                    creation_idempotency_key="lonely",
                    deal_idempotency_key="deal-key",
                    payout_idempotency_key="payout-key",
                    payout_token="seller-card-token",
                    user_id=5,
                    delivery_type="pickup",
                    status="CREATED",
                    address="Moscow",
                    buyer_amount=Decimal("10.00"),
                    seller_amount=Decimal("10.00"),
                )
            )
            await session.flush()
            order_id = (await session.scalar(select(Order))).order_id

    cancelled = await cancel_order(sessions, order_id)

    assert cancelled.status == "CANCELLED"
    assert yookassa == []


async def test_list_orders_uses_the_update_cursor(sessions, yookassa):
    await create_order(sessions, _request("older", user_id=9))
    await create_order(sessions, _request("newer", user_id=9))
    async with sessions() as session:
        async with session.begin():
            rows = (await session.scalars(select(Order).where(Order.user_id == 9).order_by(Order.order_id))).all()
            rows[0].updated_at = datetime(2026, 1, 1, tzinfo=timezone.utc)
            rows[1].updated_at = datetime(2026, 2, 1, tzinfo=timezone.utc)

    older_id, newer_id = rows[0].order_id, rows[1].order_id

    first_page = await list_orders(sessions, user_id=9, cursor=None, limit=1)
    second_page = await list_orders(sessions, user_id=9, cursor=first_page.next_cursor, limit=1)

    assert [item.order_id for item in first_page.orders] == [newer_id]
    assert first_page.orders[0].images == ["https://img.example/cup.png"]
    assert [item.order_id for item in second_page.orders] == [older_id]
    assert second_page.next_cursor is None
    with pytest.raises(InvalidCursor):
        await list_orders(sessions, user_id=9, cursor="not-a-cursor")


async def test_get_order_refreshes_the_deal_without_returning_yookassa_state(sessions, yookassa, monkeypatch):
    created = await create_order(sessions, _request())
    monkeypatch.setattr("reads.Deal.find_one", lambda deal_id: deal_response(deal_id, "closed"))

    detail = await get_order(sessions, created.order_id)
    dumped = detail.model_dump()

    assert detail.deal.status == "closed"
    assert detail.items[0].name == "Cup"
    assert "last_state" not in dumped["deal"]
    assert "idempotency_key" not in dumped["payment"]


async def test_debug_returns_payments_and_events(sessions, yookassa):
    created = await create_order(sessions, _request())

    debug = await debug_order(sessions, created.order_id)

    assert debug.payout_idempotency_key != debug.deal_idempotency_key
    assert debug.deal.last_state["status"] == "opened"
    assert len(debug.payments) == 1
    assert debug.payments[0].last_state["status"] == "pending"
    assert debug.order_events == []
    assert debug.payment_events == []
    assert encode_cursor(debug.updated_at)
