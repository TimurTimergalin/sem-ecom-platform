"""Premium subscription checkout via a regular YooKassa payment."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from urllib.parse import urlparse

from fastapi import APIRouter, Header, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from yookassa import Payment

import yookassa_setup

router = APIRouter(prefix="/api/internal/subscriptions", tags=["subscriptions"])
public = APIRouter(tags=["subscriptions"])

_fake_payments: dict[str, dict] = {}


class CheckoutIn(BaseModel):
    sellerId: str = Field(min_length=1, max_length=64)
    tier: str
    amount: int = Field(ge=1)
    currency: str = "RUB"


class RenewIn(BaseModel):
    sellerId: str = Field(min_length=1, max_length=64)
    paymentMethodId: str = Field(min_length=1, max_length=64)
    amount: int = Field(ge=1)
    currency: str = "RUB"


def envelope(data: dict) -> dict:
    return {"data": data, "error": None}


def fail(status: int, message: str) -> JSONResponse:
    return JSONResponse(
        status_code=status,
        content={"data": None, "error": {"code": "UPSTREAM_ERROR", "message": message}},
    )


def subscription_return_url() -> str:
    parsed = urlparse(yookassa_setup.return_url or "http://localhost:3000/account/orders")
    origin = f"{parsed.scheme}://{parsed.netloc}" if parsed.scheme and parsed.netloc else "http://localhost:3000"
    return f"{origin}/seller/pricing?sync=1"


def money(amount: int) -> str:
    return format(Decimal(amount).quantize(Decimal("0.01")), "f")


def metadata_of(payment) -> dict:
    raw = getattr(payment, "metadata", None)
    if raw is None:
        return {}
    if isinstance(raw, dict):
        return raw
    try:
        return dict(raw)
    except (TypeError, ValueError):
        return {}


def status_of(payment, seller_id: str) -> dict:
    meta = metadata_of(payment)
    if str(meta.get("seller_id") or "") != seller_id:
        return {}
    remote = getattr(payment, "status", "") or ""
    if remote == "succeeded":
        status = "confirmed"
    elif remote == "canceled":
        status = "cancelled"
    else:
        status = "pending"
    valid_until = None
    if status == "confirmed":
        valid_until = (datetime.now(UTC) + timedelta(days=30)).isoformat()
    return {
        "sellerId": seller_id,
        "reference": str(payment.id),
        "status": status,
        "tier": "premium",
        "validUntil": valid_until,
        "onlinePayments": status == "confirmed",
        "paymentMethodId": saved_method_id(payment),
    }


def saved_method_id(payment) -> str | None:
    method = getattr(payment, "payment_method", None)
    if isinstance(method, dict):
        method_id, saved = method.get("id"), method.get("saved")
    elif method is not None:
        method_id, saved = getattr(method, "id", None), getattr(method, "saved", False)
    else:
        return None
    if saved and isinstance(method_id, str) and method_id:
        return method_id
    return None


def fake_view(reference: str) -> dict:
    row = _fake_payments.get(reference)
    if row is None:
        raise HTTPException(status_code=404, detail="not found")
    paid = row["status"] == "confirmed"
    return {
        "buyer_amount": money(row["amount"]),
        "status": "PAID" if paid else "PENDING",
        "paid": paid,
    }


@router.post("/checkout", response_model=None)
async def checkout(
    body: CheckoutIn,
    idempotency_key: str = Header(alias="Idempotency-Key"),
) -> dict | JSONResponse:
    if body.tier != "premium" or body.currency != "RUB":
        return fail(400, "Поддерживается только Premium в рублях")
    try:
        payment = await asyncio.to_thread(
            Payment.create,
            {
                "amount": {"value": money(body.amount), "currency": "RUB"},
                "capture": True,
                "save_payment_method": True,
                "confirmation": {"type": "redirect", "return_url": subscription_return_url()},
                "description": "Подписка Premium",
                "metadata": {"seller_id": body.sellerId, "purpose": "premium"},
            },
            idempotency_key,
        )
    except Exception:
        return fail(502, "YooKassa request failed")
    confirmation = getattr(payment, "confirmation", None)
    url = getattr(confirmation, "confirmation_url", None)
    if not getattr(payment, "id", None) or not url:
        return fail(502, "YooKassa request failed")
    return envelope({"reference": str(payment.id), "paymentUrl": url, "status": "pending"})


@router.post("/renew", response_model=None)
async def renew(
    body: RenewIn,
    idempotency_key: str = Header(alias="Idempotency-Key"),
) -> dict | JSONResponse:
    if body.currency != "RUB":
        return fail(400, "Поддерживается только продление в рублях")
    try:
        payment = await asyncio.to_thread(
            Payment.create,
            {
                "amount": {"value": money(body.amount), "currency": "RUB"},
                "capture": True,
                "payment_method_id": body.paymentMethodId,
                "description": "Продление подписки Premium",
                "metadata": {"seller_id": body.sellerId, "purpose": "premium"},
            },
            idempotency_key,
        )
    except Exception:
        return fail(502, "YooKassa request failed")
    if not getattr(payment, "id", None):
        return fail(502, "YooKassa request failed")
    payload = status_of(payment, body.sellerId)
    if not payload:
        return fail(502, "YooKassa request failed")
    return envelope(payload)


@router.get("/{reference}", response_model=None)
async def state(reference: str, sellerId: str) -> dict | JSONResponse:
    try:
        payment = await asyncio.to_thread(Payment.find_one, reference)
    except Exception:
        return fail(502, "YooKassa request failed")
    if payment is None or not getattr(payment, "id", None):
        return fail(404, "Платёж не найден")
    payload = status_of(payment, sellerId)
    if not payload:
        return fail(404, "Платёж не найден")
    return envelope(payload)


@public.get("/v1/subscriptions/{reference}")
async def public_subscription(reference: str) -> dict:
    if not yookassa_setup.fake:
        raise HTTPException(status_code=404, detail="not found")
    return fake_view(reference)


@public.post("/v1/subscriptions/{reference}/fake-pay")
async def public_subscription_pay(reference: str) -> dict:
    if not yookassa_setup.fake:
        raise HTTPException(status_code=404, detail="not found")
    row = _fake_payments.get(reference)
    if row is None:
        raise HTTPException(status_code=404, detail="not found")
    row["status"] = "confirmed"
    return fake_view(reference)
