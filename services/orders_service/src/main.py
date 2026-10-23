from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
import html
import secrets

from fastapi import FastAPI, Form, Header, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from models import Base
from schemas import (
    CancelOut,
    CompleteOut,
    CompleteRequest,
    ConfirmOut,
    CreateOrderRequest,
    OrderDebug,
    OrderDetail,
    OrderList,
    OrderOut,
    Skipped,
)
from db import SerializationFailed
from reads import InvalidCursor, debug_order, get_order, list_orders
from service import (
    AccountRequired,
    OrderNotFound,
    StateMismatch,
    YooKassaFailed,
    cancel_order,
    complete_order,
    confirm_order,
    create_order,
    fake_mark_paid,
    repay_order,
)
from settings import Settings
from subscriptions import public as subscriptions_public
from subscriptions import router as subscriptions_router
import yookassa_setup
from yookassa_setup import configure_sdk


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = Settings()
    configure_sdk(settings)
    engine = create_async_engine(settings.database_url, isolation_level="SERIALIZABLE")
    app.state.sessions = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
        await _ensure_split_columns(connection)
    yield
    await engine.dispose()


app = FastAPI(lifespan=lifespan)
app.include_router(subscriptions_router)
app.include_router(subscriptions_public)

_oauth_codes: dict[str, str] = {}
_oauth_tokens: dict[str, str] = {}


def _redirect_allowed(uri: str) -> bool:
    return uri.startswith("http://localhost:8090/api/seller/yookassa/callback") or uri.startswith(
        "http://b2b:8000/api/seller/yookassa/callback"
    )


@app.get("/oauth/v2/authorize", response_class=HTMLResponse)
async def oauth_authorize(state: str, redirect_uri: str) -> HTMLResponse:
    if not yookassa_setup.fake:
        raise HTTPException(status_code=404)
    if not _redirect_allowed(redirect_uri):
        raise HTTPException(status_code=400, detail="redirect_uri")
    safe_state = html.escape(state, quote=True)
    safe_redirect = html.escape(redirect_uri, quote=True)
    page = f"""<!doctype html>
<html lang="ru"><head><meta charset="utf-8"><title>Заглушка ЮKassa</title></head>
<body style="font-family:sans-serif;max-width:28rem;margin:3rem auto">
<h1>Тестовая ЮKassa</h1>
<p>Локальная заглушка. Магазин не создаётся в настоящей ЮKassa, деньги не списываются.</p>
<form method="post">
<input type="hidden" name="state" value="{safe_state}">
<input type="hidden" name="redirect_uri" value="{safe_redirect}">
<label>Номер тестового магазина<br>
<input name="account_id" value="100001" inputmode="numeric" required>
</label>
<p><button type="submit">Выдать доступ</button></p>
</form>
</body></html>"""
    return HTMLResponse(page)


@app.post("/oauth/v2/authorize")
async def oauth_authorize_submit(
    state: str = Form(),
    redirect_uri: str = Form(),
    account_id: str = Form(),
) -> RedirectResponse:
    if not yookassa_setup.fake:
        raise HTTPException(status_code=404)
    if not _redirect_allowed(redirect_uri) or not account_id.isdigit():
        raise HTTPException(status_code=400)
    code = secrets.token_urlsafe(18)
    _oauth_codes[code] = account_id
    return RedirectResponse(f"{redirect_uri}?code={code}&state={state}", status_code=302)


@app.post("/oauth/v2/token")
async def oauth_token(grant_type: str = Form(), code: str = Form()) -> JSONResponse:
    if not yookassa_setup.fake:
        raise HTTPException(status_code=404)
    if grant_type != "authorization_code":
        return JSONResponse(status_code=400, content={"error": "unsupported_grant_type"})
    account_id = _oauth_codes.pop(code, None)
    if account_id is None:
        return JSONResponse(status_code=400, content={"error": "invalid_grant"})
    access_token = secrets.token_urlsafe(18)
    _oauth_tokens[access_token] = account_id
    return JSONResponse(
        {"access_token": access_token, "expires_in": 3600, "token_type": "bearer"}
    )


@app.get("/v3/me")
async def oauth_me(authorization: str = Header(default="")) -> dict:
    if not yookassa_setup.fake:
        raise HTTPException(status_code=404)
    token = authorization.removeprefix("Bearer ").strip()
    account_id = _oauth_tokens.get(token)
    if not account_id:
        raise HTTPException(status_code=401)
    return {"account_id": account_id, "status": "enabled", "test": True}


async def _ensure_split_columns(connection) -> None:
    if connection.dialect.name != "postgresql":
        return
    statements = (
        "ALTER TABLE orders ADD COLUMN IF NOT EXISTS multi_order_id VARCHAR(36)",
        "ALTER TABLE orders ADD COLUMN IF NOT EXISTS yookassa_account_id VARCHAR(128)",
        "ALTER TABLE orders ALTER COLUMN payout_token DROP NOT NULL",
        "CREATE INDEX IF NOT EXISTS ix_orders_multi_order_id ON orders (multi_order_id)",
    )
    for statement in statements:
        await connection.execute(text(statement))


def _rejected(exc: StateMismatch) -> JSONResponse:
    return JSONResponse(status_code=400, content={"reason": exc.reason})


def _rejected_reason(exc: InvalidCursor) -> JSONResponse:
    return JSONResponse(status_code=400, content={"reason": "invalid cursor"})


@app.get("/v1/orders", response_model=OrderList)
async def get_orders(
    request: Request,
    user_id: str | None = None,
    seller_id: str | None = None,
    cursor: str | None = None,
    limit: int = Query(default=20, ge=1, le=100),
) -> OrderList | JSONResponse:
    user_id = user_id or None
    seller_id = seller_id or None
    if user_id is None and seller_id is None:
        return JSONResponse(status_code=400, content={"reason": "user_id or seller_id is required"})
    try:
        return await list_orders(request.app.state.sessions, user_id, cursor, limit, seller_id)
    except InvalidCursor as exc:
        return _rejected_reason(exc)
    except SerializationFailed as exc:
        raise HTTPException(status_code=502, detail="database transaction failed") from exc


@app.get("/v1/orders/{order_id}", response_model=OrderDetail)
async def get_order_by_id(order_id: str, request: Request) -> OrderDetail:
    try:
        return await get_order(request.app.state.sessions, order_id)
    except OrderNotFound as exc:
        raise HTTPException(status_code=404, detail="order not found") from exc
    except YooKassaFailed as exc:
        raise HTTPException(status_code=502, detail="YooKassa request failed") from exc
    except SerializationFailed as exc:
        raise HTTPException(status_code=502, detail="database transaction failed") from exc


@app.get("/v1/orders/{order_id}/debug", response_model=OrderDebug)
async def get_order_debug(order_id: str, request: Request) -> OrderDebug:
    try:
        return await debug_order(request.app.state.sessions, order_id)
    except OrderNotFound as exc:
        raise HTTPException(status_code=404, detail="order not found") from exc
    except SerializationFailed as exc:
        raise HTTPException(status_code=502, detail="database transaction failed") from exc


@app.post("/v1/orders/{order_id}/fake-pay", response_model=None)
async def post_fake_pay(order_id: str, request: Request) -> OrderDetail | JSONResponse:
    if not yookassa_setup.fake:
        raise HTTPException(status_code=404, detail="not found")
    try:
        await fake_mark_paid(request.app.state.sessions, order_id)
        return await get_order(request.app.state.sessions, order_id)
    except OrderNotFound as exc:
        raise HTTPException(status_code=404, detail="order not found") from exc
    except StateMismatch as exc:
        return _rejected(exc)
    except SerializationFailed as exc:
        raise HTTPException(status_code=502, detail="database transaction failed") from exc


@app.post("/v1/orders", response_model=OrderOut)
async def post_order(body: CreateOrderRequest, request: Request) -> OrderOut | JSONResponse:
    try:
        return await create_order(request.app.state.sessions, body)
    except AccountRequired:
        return JSONResponse(status_code=400, content={"reason": "yookassa_account_id is required"})
    except YooKassaFailed as exc:
        raise HTTPException(status_code=502, detail="YooKassa request failed") from exc
    except SerializationFailed as exc:
        raise HTTPException(status_code=502, detail="database transaction failed") from exc


@app.post("/v1/orders/{order_id}/repay", response_model=OrderOut)
async def post_repay(order_id: str, request: Request) -> OrderOut | JSONResponse:
    try:
        return await repay_order(request.app.state.sessions, order_id)
    except AccountRequired:
        return JSONResponse(status_code=400, content={"reason": "yookassa_account_id is required"})
    except OrderNotFound as exc:
        raise HTTPException(status_code=404, detail="order not found") from exc
    except StateMismatch as exc:
        return _rejected(exc)
    except YooKassaFailed as exc:
        raise HTTPException(status_code=502, detail="YooKassa request failed") from exc
    except SerializationFailed as exc:
        raise HTTPException(status_code=502, detail="database transaction failed") from exc


@app.post("/v1/orders/{order_id}/confirm", response_model=ConfirmOut)
async def post_confirm(order_id: str, request: Request) -> ConfirmOut | JSONResponse:
    try:
        return await confirm_order(request.app.state.sessions, order_id)
    except OrderNotFound as exc:
        raise HTTPException(status_code=404, detail="order not found") from exc
    except StateMismatch as exc:
        return _rejected(exc)
    except SerializationFailed as exc:
        raise HTTPException(status_code=502, detail="database transaction failed") from exc


@app.post("/v1/orders/{order_id}/complete", response_model=CompleteOut | Skipped)
async def post_complete(order_id: str, body: CompleteRequest, request: Request) -> CompleteOut | Skipped | JSONResponse:
    try:
        return await complete_order(request.app.state.sessions, order_id, body)
    except OrderNotFound as exc:
        raise HTTPException(status_code=404, detail="order not found") from exc
    except StateMismatch as exc:
        return _rejected(exc)
    except YooKassaFailed as exc:
        raise HTTPException(status_code=502, detail="YooKassa request failed") from exc
    except SerializationFailed as exc:
        raise HTTPException(status_code=502, detail="database transaction failed") from exc


@app.post("/v1/orders/{order_id}/cancel", response_model=CancelOut)
async def post_cancel(order_id: str, request: Request) -> CancelOut | JSONResponse:
    try:
        return await cancel_order(request.app.state.sessions, order_id)
    except OrderNotFound as exc:
        raise HTTPException(status_code=404, detail="order not found") from exc
    except StateMismatch as exc:
        return _rejected(exc)
    except YooKassaFailed as exc:
        raise HTTPException(status_code=502, detail="YooKassa request failed") from exc
    except SerializationFailed as exc:
        raise HTTPException(status_code=502, detail="database transaction failed") from exc
