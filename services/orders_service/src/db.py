import asyncio
from collections.abc import Awaitable, Callable
from typing import TypeVar

from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

T = TypeVar("T")

SERIALIZATION_FAILURE = "40001"
UNIQUE_VIOLATION = "23505"
ATTEMPTS = 4
BACKOFF_SECONDS = 0.05


class SerializationFailed(Exception):
    pass


async def run_serializable(
    sessions: async_sessionmaker[AsyncSession],
    work: Callable[[AsyncSession], Awaitable[T]],
) -> T:
    last_serialization_error: DBAPIError | None = None
    for attempt in range(ATTEMPTS):
        try:
            async with sessions() as session:
                # Isolation is set on the engine. SET TRANSACTION inside begin()
                # runs after asyncpg has already started a transaction and closes
                # the connection.
                async with session.begin():
                    return await work(session)
        except DBAPIError as exc:
            sqlstate = getattr(exc.orig, "sqlstate", None)
            if sqlstate == UNIQUE_VIOLATION and attempt + 1 < ATTEMPTS:
                continue
            if sqlstate != SERIALIZATION_FAILURE:
                raise
            last_serialization_error = exc
            if attempt + 1 >= ATTEMPTS:
                break
            await asyncio.sleep(BACKOFF_SECONDS * (2**attempt))
    assert last_serialization_error is not None
    raise SerializationFailed from last_serialization_error
