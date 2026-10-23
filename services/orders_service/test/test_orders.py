import uuid
from datetime import datetime, timezone
from decimal import Decimal

import pytest
from sqlalchemy import select

from conftest import payment_response
from models import Base
from models.base import AwareDateTime
from models.multi_order import MultiOrder
from models.order import Order
from reads import InvalidCursor, debug_order, encode_cursor, get_order, list_orders
from schemas import CreateOrderRequest, ItemIn, OrderGroupIn
from service import (
    AccountRequired,
    CompleteRequest,
    StateMismatch,
    cancel_order,
    complete_order,
    confirm_order,
    create_order,
    fake_mark_paid,
    repay_order,
)

USER_ID = "11111111-1111-4111-8111-111111111111"
OTHER_USER_ID = "44444444-4444-4444-8444-444444444444"
SELLER_ID = "22222222-2222-4222-8222-222222222222"
SELLER_B = "55555555-5555-4555-8555-555555555555"
SKU_ID = "33333333-3333-4333-8333-333333333333"
SKU_B = "66666666-6666-4666-8666-666666666666"
SHOP_A = "shop-a"
SHOP_B = "shop-b"


def _group(
    seller_id=SELLER_ID,
    shop=SHOP_A,
    sku=SKU_ID,
    price="10.00",
    quantity=2,
    address="Moscow",
):
    return OrderGroupIn(
        seller_id=seller_id,
        yookassa_account_id=shop,
        address=address,
        delivery_type="pickup",
        items=[ItemIn(sku_id=sku, name="Cup", image="https://img.example/cup.png", price=Decimal(price), quantity=quantity)],
    )


def _request(key="key-1", user_id=USER_ID, groups=None):
    return CreateOrderRequest(
        user_id=user_id,
        idempotency_key=key,
        groups=groups or [_group()],
    )


def _two_groups(key="key-two", user_id=USER_ID):
    return _request(
        key,
        user_id,
        [
            _group(),
            _group(seller_id=SELLER_B, shop=SHOP_B, sku=SKU_B, price="5.00", quantity=1, address="Kazan"),
        ],
    )


def test_datetime_columns_require_a_timezone():
    dated = [column for table in Base.metadata.tables.values() for column in table.columns if column.name.endswith("_at")]
    assert dated
    assert all(isinstance(column.type, AwareDateTime) for column in dated)
    with pytest.raises(ValueError):
        AwareDateTime().process_bind_param(datetime(2026, 1, 1), None)


async def test_create_order_splits_one_payment_without_a_deal(sessions, yookassa):
    created = await create_order(sessions, _two_groups())

    async with sessions() as session:
        order = await session.get(Order, created.order_id)
        multi = await session.get(MultiOrder, created.multi_order_id)

    assert order.payout_token is None
    assert order.multi_order_id == created.multi_order_id
    assert order.yookassa_account_id == SHOP_A
    assert multi.idempotency_key == "key-two"
    assert created.deal is None
    assert created.order_id == created.orders[0].order_id
    assert [item.seller_id for item in created.orders] == [SELLER_ID, SELLER_B]
    assert created.confirmation_url == "https://pay.example/1"
    assert "last_state" not in created.model_dump()
    assert not any(call[0] in {"deal", "payout"} for call in yookassa)
    payment_call = next(call for call in yookassa if call[0] == "payment")
    assert payment_call[1] == multi.yookassa_payload["payment_idempotency_key"]
    assert payment_call[1] != "key-two"
    assert "deal" not in payment_call[2]
    assert payment_call[2]["capture"] is True
    assert payment_call[2]["amount"] == {"value": "25.00", "currency": "RUB"}
    assert payment_call[2]["confirmation"] == {"type": "redirect", "return_url": "https://example.com/return"}
    assert payment_call[2]["transfers"] == [
        {
            "account_id": SHOP_A,
            "amount": {"value": "20.00", "currency": "RUB"},
            "metadata": {"order_id": created.orders[0].order_id},
        },
        {
            "account_id": SHOP_B,
            "amount": {"value": "5.00", "currency": "RUB"},
            "metadata": {"order_id": created.orders[1].order_id},
        },
    ]
    assert SELLER_ID in payment_call[2]["description"]
    assert "20.00" in payment_call[2]["description"]
    assert SELLER_B in payment_call[2]["description"]

    listed = await list_orders(sessions, user_id=USER_ID, cursor=None, limit=10)
    assert {item.order_id for item in listed.orders} == {created.orders[0].order_id, created.orders[1].order_id}


async def test_repeated_create_does_not_open_another_payment(sessions, yookassa):
    first = await create_order(sessions, _request())
    second = await create_order(sessions, _request())

    assert second.order_id == first.order_id
    assert second.multi_order_id == first.multi_order_id
    assert [call for call in yookassa if call[0] == "payment"] == [yookassa[0]]
    assert not any(call[0] == "deal" for call in yookassa)


async def test_missing_shop_is_rejected(sessions, yookassa):
    with pytest.raises(AccountRequired):
        await create_order(sessions, _request(groups=[_group(shop=" ")]))

    assert yookassa == []


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


async def test_complete_does_not_create_a_payout(sessions, yookassa):
    created = await create_order(sessions, _request())
    async with sessions() as session:
        async with session.begin():
            order = await session.get(Order, created.order_id)
            order.status = "DELIVERED"
            order.receival_code = "048213"

    skipped = await complete_order(sessions, created.order_id, CompleteRequest(receival_code="000000"))
    completed = await complete_order(sessions, created.order_id, CompleteRequest(receival_code="048213"))

    assert skipped.reason == "receival code does not match"
    assert completed.status == "COMPLETED"
    assert [call for call in yookassa if call[0] in {"payout", "deal"}] == []


async def test_cancel_created_order_does_not_call_yookassa(sessions, yookassa):
    async with sessions() as session:
        async with session.begin():
            session.add(
                Order(
                    order_id=str(uuid.uuid4()),
                    creation_idempotency_key="lonely",
                    deal_idempotency_key="deal-key",
                    payout_idempotency_key="payout-key",
                    payout_token="seller-card-token",
                    user_id=USER_ID,
                    seller_id=SELLER_ID,
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


async def test_cancel_before_payment_omits_seller_from_next_payment(sessions, yookassa):
    created = await create_order(sessions, _two_groups())

    cancelled = await cancel_order(sessions, created.orders[0].order_id)
    repaid = await repay_order(sessions, created.orders[1].order_id)

    payment_calls = [call for call in yookassa if call[0] == "payment"]
    assert cancelled.status == "CANCELLED"
    assert len(payment_calls) == 2
    assert payment_calls[1][2]["amount"] == {"value": "5.00", "currency": "RUB"}
    assert payment_calls[1][2]["transfers"] == [
        {
            "account_id": SHOP_B,
            "amount": {"value": "5.00", "currency": "RUB"},
            "metadata": {"order_id": created.orders[1].order_id},
        }
    ]
    assert repaid.order_id == created.orders[1].order_id
    assert {item.order_id: item.status for item in repaid.orders} == {
        created.orders[0].order_id: "CANCELLED",
        created.orders[1].order_id: "PAYMENT_INITIALIZED",
    }
    assert any(call[0] == "cancel" for call in yookassa)
    assert not any(call[0] == "refund" for call in yookassa)


async def test_repay_pending_payment_does_not_create_another(sessions, yookassa):
    created = await create_order(sessions, _request())

    again = await repay_order(sessions, created.order_id)

    assert again.confirmation_url == created.confirmation_url
    assert again.multi_order_id == created.multi_order_id
    assert len([call for call in yookassa if call[0] == "payment"]) == 1
    assert any(call[0] == "find_payment" for call in yookassa)


async def test_repay_promotes_every_open_order_when_payment_succeeded(sessions, yookassa, monkeypatch):
    created = await create_order(sessions, _two_groups())

    def find_payment(payment_id):
        return payment_response(payment_id=payment_id, status="succeeded")

    monkeypatch.setattr("service.YooKassaPayment.find_one", find_payment)
    repaid = await repay_order(sessions, created.orders[1].order_id)

    assert repaid.order_id == created.orders[1].order_id
    assert repaid.status == "PAID"
    assert {item.status for item in repaid.orders} == {"PAID"}
    assert len([call for call in yookassa if call[0] == "payment"]) == 1


async def test_cancel_after_payment_refunds_only_that_transfer(sessions, yookassa):
    created = await create_order(sessions, _two_groups())
    async with sessions() as session:
        async with session.begin():
            multi = await session.get(MultiOrder, created.multi_order_id)
            multi.payment_status = "succeeded"
            rows = (await session.scalars(select(Order).where(Order.multi_order_id == created.multi_order_id))).all()
            for row in rows:
                row.status = "PAID"

    cancelled = await cancel_order(sessions, created.orders[0].order_id)

    refund_call = next(call for call in yookassa if call[0] == "refund")
    assert cancelled.status == "CANCELLED"
    assert refund_call[1] == created.orders[0].order_id
    assert refund_call[2]["payment_id"] == "pay-1"
    assert refund_call[2]["amount"] == {"value": "20.00", "currency": "RUB"}
    assert refund_call[2]["sources"] == [
        {"account_id": SHOP_A, "amount": {"value": "20.00", "currency": "RUB"}}
    ]
    async with sessions() as session:
        other = await session.get(Order, created.orders[1].order_id)
    assert other.status == "PAID"
    assert not any(call[0] in {"payout", "deal"} for call in yookassa)


async def test_fake_pay_marks_every_open_order(sessions, yookassa, monkeypatch):
    monkeypatch.setattr("yookassa_setup.fake", True)
    created = await create_order(sessions, _two_groups("fake-key"))
    await cancel_order(sessions, created.orders[0].order_id)

    await fake_mark_paid(sessions, created.orders[1].order_id)

    async with sessions() as session:
        first = await session.get(Order, created.orders[0].order_id)
        second = await session.get(Order, created.orders[1].order_id)
        multi = await session.get(MultiOrder, created.multi_order_id)
    assert first.status == "CANCELLED"
    assert second.status == "PAID"
    assert multi.payment_status == "succeeded"
    assert "/pay/test?order=" in created.confirmation_url
    assert yookassa == []


async def test_fake_cancel_after_pay_does_not_call_yookassa(sessions, yookassa, monkeypatch):
    monkeypatch.setattr("yookassa_setup.fake", True)
    created = await create_order(sessions, _two_groups("fake-paid"))
    await fake_mark_paid(sessions, created.order_id)

    cancelled = await cancel_order(sessions, created.orders[0].order_id)

    async with sessions() as session:
        other = await session.get(Order, created.orders[1].order_id)
    assert cancelled.status == "CANCELLED"
    assert other.status == "PAID"
    assert yookassa == []


async def test_list_orders_uses_the_update_cursor(sessions, yookassa):
    await create_order(sessions, _request("older", user_id=OTHER_USER_ID))
    await create_order(sessions, _request("newer", user_id=OTHER_USER_ID))
    async with sessions() as session:
        async with session.begin():
            rows = (await session.scalars(select(Order).where(Order.user_id == OTHER_USER_ID).order_by(Order.order_id))).all()
            rows[0].updated_at = datetime(2026, 1, 1, tzinfo=timezone.utc)
            rows[1].updated_at = datetime(2026, 2, 1, tzinfo=timezone.utc)

    older_id, newer_id = rows[0].order_id, rows[1].order_id

    first_page = await list_orders(sessions, user_id=OTHER_USER_ID, cursor=None, limit=1)
    second_page = await list_orders(sessions, user_id=OTHER_USER_ID, cursor=first_page.next_cursor, limit=1)
    by_seller = await list_orders(sessions, user_id=None, cursor=None, limit=10, seller_id=SELLER_ID)

    assert [item.order_id for item in first_page.orders] == [newer_id]
    assert first_page.orders[0].seller_id == SELLER_ID
    assert first_page.orders[0].images == ["https://img.example/cup.png"]
    assert [item.order_id for item in second_page.orders] == [older_id]
    assert second_page.next_cursor is None
    assert {item.order_id for item in by_seller.orders} == {older_id, newer_id}
    with pytest.raises(InvalidCursor):
        await list_orders(sessions, user_id=OTHER_USER_ID, cursor="not-a-cursor")


async def test_get_order_refreshes_payment_without_returning_yookassa_state(sessions, yookassa, monkeypatch):
    created = await create_order(sessions, _two_groups())
    monkeypatch.setattr(
        "reads.YooKassaPayment.find_one",
        lambda payment_id: payment_response(payment_id, "succeeded"),
    )

    detail = await get_order(sessions, created.orders[1].order_id)
    dumped = detail.model_dump()
    async with sessions() as session:
        sibling = await session.get(Order, created.orders[0].order_id)

    assert detail.deal is None
    assert detail.status == "PAID"
    assert detail.payment.status == "succeeded"
    assert detail.items[0].name == "Cup"
    assert "last_state" not in dumped["payment"]
    assert "idempotency_key" not in dumped["payment"]
    assert sibling.status == "PAID"


async def test_debug_returns_events_without_a_deal(sessions, yookassa):
    created = await create_order(sessions, _request())

    debug = await debug_order(sessions, created.order_id)

    assert debug.deal is None
    assert debug.payout_token is None
    assert debug.multi_order_id == created.multi_order_id
    assert debug.payments == []
    assert debug.order_events == []
    assert debug.payment_events == []
    assert encode_cursor(debug.updated_at)
