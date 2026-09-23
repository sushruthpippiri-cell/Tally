"""Async SQLAlchemy engine (asyncpg), per-request session dependency and transaction helper."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from functools import lru_cache

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.core.config import get_settings


@lru_cache
def get_engine() -> AsyncEngine:
    url = get_settings().database_url
    assert url is not None  # guaranteed by Settings validation
    return create_async_engine(url, pool_pre_ping=True)


@lru_cache
def _sessionmaker() -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(get_engine(), expire_on_commit=False)


async def get_session() -> AsyncIterator[AsyncSession]:
    """FastAPI dependency. The caller owns commit/rollback (use `transaction()` for writes)."""
    async with _sessionmaker()() as session:
        yield session


@asynccontextmanager
async def transaction() -> AsyncIterator[AsyncSession]:
    """One session, one transaction: commits on success, rolls back on any exception."""
    async with _sessionmaker()() as session, session.begin():
        yield session
