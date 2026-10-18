import json
from types import SimpleNamespace

import pytest
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.ext.compiler import compiles
from sqlalchemy import event

from models import Base
from models.order import Order


@compiles(JSONB, "sqlite")
def _compile_jsonb_for_sqlite(element, compiler, **kwargs):
    return "JSON"


class Remote:
    def __init__(self, **data):
        self._data = data
        for key, value in data.items():
            setattr(self, key, value)

    def json(self):
        payload = {key: value for key, value in self._data.items() if key != "confirmation"}
        return json.dumps(payload, default=str)


def payment_response(payment_id="pay-1", status="pending", url="https://pay.example/1"):
    return Remote(
        id=payment_id,
        status=status,
        confirmation=SimpleNamespace(confirmation_url=url),
    )


def deal_response(deal_id="dl-1", status="opened"):
    return Remote(id=deal_id, status=status)


@pytest.fixture
async def sessions(monkeypatch):
    engine = create_async_engine("sqlite+aiosqlite://")
    next_id = {"value": 0}

    def assign_order_id(mapper, connection, target):
        if target.order_id is None:
            next_id["value"] += 1
            target.order_id = next_id["value"]

    event.listen(Order, "before_insert", assign_order_id)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)

    async def run(bound_factory, work):
        async with bound_factory() as session:
            async with session.begin():
                return await work(session)

    monkeypatch.setattr("service.run_serializable", run)
    monkeypatch.setattr("reads.run_serializable", run)
    monkeypatch.setattr("db.run_serializable", run)
    yield factory
    event.remove(Order, "before_insert", assign_order_id)
    await engine.dispose()


@pytest.fixture
def yookassa(monkeypatch):
    calls = []
    sequence = {"n": 0}

    def create_deal(params, idempotency_key=None):
        sequence["n"] += 1
        calls.append(("deal", idempotency_key, params))
        return deal_response(deal_id=f"dl-{sequence['n']}")

    def create_payment(params, idempotency_key=None):
        sequence["n"] += 1
        calls.append(("payment", idempotency_key, params))
        return payment_response(payment_id=f"pay-{sequence['n']}")

    def create_payout(params, idempotency_key=None):
        calls.append(("payout", idempotency_key, params))
        return Remote(id="po-1", status="succeeded")

    def create_refund(params, idempotency_key=None):
        calls.append(("refund", idempotency_key, params))
        return Remote(id="rf-1", status="succeeded")

    def find_payment(payment_id):
        calls.append(("find_payment", payment_id))
        return payment_response(payment_id=payment_id, status="succeeded")

    def find_deal(deal_id):
        calls.append(("find_deal", deal_id))
        return deal_response(deal_id=deal_id, status="opened")

    monkeypatch.setattr("service.Deal.create", create_deal)
    monkeypatch.setattr("service.YooKassaPayment.create", create_payment)
    monkeypatch.setattr("service.YooKassaPayment.find_one", find_payment)
    monkeypatch.setattr("service.YooKassaPayment.cancel", lambda payment_id, idempotency_key=None: payment_response(payment_id, "canceled"))
    monkeypatch.setattr("service.Payout.create", create_payout)
    monkeypatch.setattr("service.YooKassaRefund.create", create_refund)
    monkeypatch.setattr("reads.Deal.find_one", find_deal)
    monkeypatch.setattr("reads.YooKassaPayment.find_one", find_payment)
    import yookassa_setup

    yookassa_setup.return_url = "https://example.com/return"
    return calls
