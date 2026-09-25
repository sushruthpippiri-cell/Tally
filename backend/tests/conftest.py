"""Backend test setup: tests use the real `tally_test` database (docker compose), never dev."""

import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from tally_tools.phase_report import assert_test_database

# Must be set before app.core.config is first imported.
os.environ.setdefault("ENV", "test")
os.environ["SCHEDULER_ENABLED"] = "false"  # tests call job functions directly
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
        # rolled back after the test), then run the request in its own SAVEPOINT: a failed
        # request rolls back only its own writes, like a real one, and - unlike
        # session.rollback() - does not expire the test's objects.
        await session.commit()
        request = await session.begin_nested()
        try:
            yield session
        except Exception:
            if request.is_active:
                await request.rollback()
            raise
        if request.is_active:
            await request.commit()

    app.dependency_overrides[get_session] = _session
    base = transport.pop("base_url", "http://test")
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app, **transport), base_url=base
    ) as client:
        yield client


@pytest.fixture
async def committed() -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    """Sessions that REALLY commit, each on its own connection - for testing locks,
    compare-and-set updates and races, which the rollback `session` fixture cannot prove.

    Race two operations by giving each its own session. Afterwards every company- and
    user-scoped row is removed with TRUNCATE ... CASCADE (as the owner role; `roles` survives),
    and only ever on a database whose name ends in `_test` (D-035 #14).
    """
    from app.core.config import get_settings

    app_url, owner_url = committed_database_urls(get_settings())
    engine = create_async_engine(app_url, pool_size=12)
    try:
        yield async_sessionmaker(engine, expire_on_commit=False)
    finally:
        await engine.dispose()
        owner = create_async_engine(owner_url.replace("+psycopg", "+asyncpg"))
        async with owner.begin() as conn:
            await conn.execute(text("TRUNCATE companies, users CASCADE"))
        await owner.dispose()


def committed_database_urls(settings: Any) -> tuple[str, str]:
    """(app url, owner url); raises unless both name a `_test` database (D-035 #14)."""
    app_url, owner_url = settings.database_url or "", settings.database_migration_url or ""
    assert_test_database(app_url)
    assert_test_database(owner_url)
    return app_url, owner_url
