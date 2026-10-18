from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import JSONResponse
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
    OrderNotFound,
    StateMismatch,
    YooKassaFailed,
    cancel_order,
    complete_order,
    confirm_order,
    create_order,
    repay_order,
)
from settings import Settings
from yookassa_setup import configure_sdk


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = Settings()
    configure_sdk(settings)
    engine = create_async_engine(settings.database_url, isolation_level="SERIALIZABLE")
    app.state.sessions = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    yield
    await engine.dispose()


app = FastAPI(lifespan=lifespan)


def _rejected(exc: StateMismatch) -> JSONResponse:
    return JSONResponse(status_code=400, content={"reason": exc.reason})


def _rejected_reason(exc: InvalidCursor) -> JSONResponse:
    return JSONResponse(status_code=400, content={"reason": "invalid cursor"})


@app.get("/v1/orders", response_model=OrderList)
async def get_orders(
    request: Request,
    user_id: int = Query(),
    cursor: str | None = None,
    limit: int = Query(default=20, ge=1, le=100),
) -> OrderList | JSONResponse:
    try:
        return await list_orders(request.app.state.sessions, user_id, cursor, limit)
    except InvalidCursor as exc:
        return _rejected_reason(exc)
    except SerializationFailed as exc:
        raise HTTPException(status_code=502, detail="database transaction failed") from exc


@app.get("/v1/orders/{order_id}", response_model=OrderDetail)
async def get_order_by_id(order_id: int, request: Request) -> OrderDetail:
    try:
        return await get_order(request.app.state.sessions, order_id)
    except OrderNotFound as exc:
        raise HTTPException(status_code=404, detail="order not found") from exc
    except YooKassaFailed as exc:
        raise HTTPException(status_code=502, detail="YooKassa request failed") from exc
    except SerializationFailed as exc:
        raise HTTPException(status_code=502, detail="database transaction failed") from exc


@app.get("/v1/orders/{order_id}/debug", response_model=OrderDebug)
async def get_order_debug(order_id: int, request: Request) -> OrderDebug:
    try:
        return await debug_order(request.app.state.sessions, order_id)
    except OrderNotFound as exc:
        raise HTTPException(status_code=404, detail="order not found") from exc
    except SerializationFailed as exc:
        raise HTTPException(status_code=502, detail="database transaction failed") from exc


@app.post("/v1/orders", response_model=OrderOut)
async def post_order(body: CreateOrderRequest, request: Request) -> OrderOut:
    try:
        return await create_order(request.app.state.sessions, body)
    except YooKassaFailed as exc:
        raise HTTPException(status_code=502, detail="YooKassa request failed") from exc
    except SerializationFailed as exc:
        raise HTTPException(status_code=502, detail="database transaction failed") from exc


@app.post("/v1/orders/{order_id}/repay", response_model=OrderOut)
async def post_repay(order_id: int, request: Request) -> OrderOut | JSONResponse:
    try:
        return await repay_order(request.app.state.sessions, order_id)
    except OrderNotFound as exc:
        raise HTTPException(status_code=404, detail="order not found") from exc
    except StateMismatch as exc:
        return _rejected(exc)
    except YooKassaFailed as exc:
        raise HTTPException(status_code=502, detail="YooKassa request failed") from exc
    except SerializationFailed as exc:
        raise HTTPException(status_code=502, detail="database transaction failed") from exc


@app.post("/v1/orders/{order_id}/confirm", response_model=ConfirmOut)
async def post_confirm(order_id: int, request: Request) -> ConfirmOut | JSONResponse:
    try:
        return await confirm_order(request.app.state.sessions, order_id)
    except OrderNotFound as exc:
        raise HTTPException(status_code=404, detail="order not found") from exc
    except StateMismatch as exc:
        return _rejected(exc)
    except SerializationFailed as exc:
        raise HTTPException(status_code=502, detail="database transaction failed") from exc


@app.post("/v1/orders/{order_id}/complete", response_model=CompleteOut | Skipped)
async def post_complete(order_id: int, body: CompleteRequest, request: Request) -> CompleteOut | Skipped | JSONResponse:
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
async def post_cancel(order_id: int, request: Request) -> CancelOut | JSONResponse:
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
