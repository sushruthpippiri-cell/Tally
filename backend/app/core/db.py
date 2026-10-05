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
def session_factory() -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(get_engine(), expire_on_commit=False)


async def get_session() -> AsyncIterator[AsyncSession]:
    """FastAPI dependency. The caller owns commit/rollback (use `transaction()` for writes)."""
    async with session_factory()() as session:
        yield session


@asynccontextmanager
async def transaction() -> AsyncIterator[AsyncSession]:
    """One session, one transaction: commits on success, rolls back on any exception."""
    async with session_factory()() as session, session.begin():
        yield session


@asynccontextmanager
async def snapshot() -> AsyncIterator[AsyncSession]:
    """One REPEATABLE READ, READ ONLY transaction: every statement sees the same snapshot.

    An export asks several questions - the summary, then a page of rows, then the next page -
    and promises that the rows add up to the summary (AC-39). Under PostgreSQL's default READ
    COMMITTED each statement sees whatever has committed since, so a sync landing mid-export
    would break that promise. Read only as well, because an export never writes: the database
    refuses one by mistake.

    Nothing is committed; the caller only reads. The context manager owns the session and
    closes it, so a streaming response does not depend on when its framework tears down
    request dependencies.
    """
    async with session_factory()() as session:
        await session.connection(
            execution_options={
                "isolation_level": "REPEATABLE READ",
                "postgresql_readonly": True,
            }
        )
        try:
            yield session
        finally:
            await session.rollback()
