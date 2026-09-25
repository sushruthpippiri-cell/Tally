"""Backend test setup: tests use the real `tally_test` database (docker compose), never dev."""

import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

# Must be set before app.core.config is first imported.
os.environ.setdefault("ENV", "test")
os.environ["DATABASE_URL"] = os.environ.get(
    "TEST_DATABASE_URL", "postgresql+asyncpg://tally_app:tally_app_dev@localhost:5432/tally_test"
)
os.environ["DATABASE_MIGRATION_URL"] = os.environ.get(
    "TEST_DATABASE_MIGRATION_URL",
    "postgresql+psycopg://tally_owner:tally_owner_dev@localhost:5432/tally_test",
)

from app.core.db import get_session  # noqa: E402  (after the environment is set)
from app.main import create_app  # noqa: E402


@pytest.fixture
async def session() -> AsyncIterator[AsyncSession]:
    """App-role session inside one outer transaction that is rolled back after the test.

    Fast and leak-free, but it can NOT test commit behaviour: nothing here ever really
    commits (`session.commit()` only releases a savepoint). Later phases that test
    transaction boundaries (SYNC-6.1, SYNC-6.2, TEST-3.3) need a fixture that really
    commits and cleans up afterwards.
    """
    from app.core.config import get_settings

    engine = create_async_engine(get_settings().database_url or "")
    async with engine.connect() as conn:
        outer = await conn.begin()
        # expire_on_commit=False like the app's sessions (app.core.db)
        s = AsyncSession(
            bind=conn, join_transaction_mode="create_savepoint", expire_on_commit=False
        )
        try:
            yield s
        finally:
            await s.close()
            await outer.rollback()
    await engine.dispose()


@pytest.fixture
async def api(session: AsyncSession) -> AsyncIterator[httpx.AsyncClient]:
    """The real app over ASGI, sharing the rollback `session` (one event loop, no commits)."""
    async with client_for(create_app(), session) as client:
        yield client


@asynccontextmanager
async def client_for(
    app: FastAPI, session: AsyncSession, **transport: Any
) -> AsyncIterator[httpx.AsyncClient]:
    async def _session() -> AsyncIterator[AsyncSession]:
        # "Commit" the test's setup (releases a savepoint; the outer transaction is still
        # rolled back after the test), so a failed request rolls back only its own writes.
        await session.commit()
        try:
            yield session
        except Exception:
            await session.rollback()  # like a real request: nothing uncommitted survives
            raise

    app.dependency_overrides[get_session] = _session
    base = transport.pop("base_url", "http://test")
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app, **transport), base_url=base
    ) as client:
        yield client
