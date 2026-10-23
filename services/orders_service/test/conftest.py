import json
from types import SimpleNamespace

import pytest
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.ext.compiler import compiles

from models import Base


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
    await engine.dispose()


@pytest.fixture
def yookassa(monkeypatch):
    calls = []
    sequence = {"n": 0}

    def create_payment(params, idempotency_key=None):
        sequence["n"] += 1
        calls.append(("payment", idempotency_key, params))
        return payment_response(payment_id=f"pay-{sequence['n']}")

    def create_refund(params, idempotency_key=None):
        calls.append(("refund", idempotency_key, params))
        return Remote(id="rf-1", status="succeeded")

    def find_payment(payment_id):
        calls.append(("find_payment", payment_id))
        return payment_response(payment_id=payment_id, status="pending")

    def cancel_payment(payment_id, idempotency_key=None):
        calls.append(("cancel", idempotency_key, payment_id))
        return payment_response(payment_id, "canceled")

    def find_deal(deal_id):
        calls.append(("find_deal", deal_id))
        return deal_response(deal_id=deal_id, status="opened")

    monkeypatch.setattr("service.YooKassaPayment.create", create_payment)
    monkeypatch.setattr("service.YooKassaPayment.find_one", find_payment)
    monkeypatch.setattr("service.YooKassaPayment.cancel", cancel_payment)
    monkeypatch.setattr("service.YooKassaRefund.create", create_refund)
    monkeypatch.setattr("reads.Deal.find_one", find_deal)
    monkeypatch.setattr("reads.YooKassaPayment.find_one", find_payment)
    import yookassa_setup

    yookassa_setup.return_url = "https://example.com/return"
    return calls
