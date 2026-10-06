"""Backend test setup: tests use the real `tally_test` database (docker compose), never dev."""

import os
from collections.abc import AsyncIterator, Callable
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


@pytest.fixture(autouse=True)
async def _no_engine_outlives_its_loop() -> AsyncIterator[None]:
    """`app.core.db` caches one engine for the process, but asyncpg connections belong to the
    event loop that opened them and every test gets a fresh loop.

    Until P16.11 nothing reached that cached engine in tests - `get_session` is always
    overridden - but the rate limiter counts on its own session, outside the request's. A test
    that builds its app with `TestClient(create_app())` rather than `client_for` therefore hands
    the next test an engine holding connections from a loop that has closed.
    """
    yield
    from app.core.db import get_engine, session_factory

    if get_engine.cache_info().currsize:
        await get_engine().dispose()
    get_engine.cache_clear()
    session_factory.cache_clear()


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
    # The rate limiter counts in Postgres (P16.11), on its own session rather than the request's,
    # so - like get_session above - it needs a loop-local engine: app.core.db caches one engine
    # for the process and asyncpg connections belong to the loop that opened them. Counts really
    # commit, outliving this test's rolled-back transaction, so they are deleted afterwards.
    async with counter_store() as store:
        limiter = getattr(app.state, "rate_limiter", None)  # a bare app has no middleware
        if limiter is not None:
            limiter._factory = store
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app, **transport), base_url=base
        ) as client:
            yield client


@asynccontextmanager
async def counter_store() -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    """A really-committing, loop-local factory for `rate_limit_counters`, emptied afterwards."""
    from app.core.config import get_settings

    engine = create_async_engine(get_settings().database_url or "")
    maker = async_sessionmaker(engine, expire_on_commit=False)
    try:
        yield maker
    finally:
        async with maker() as s, s.begin():
            await s.execute(text("DELETE FROM rate_limit_counters"))
        await engine.dispose()


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


@pytest.fixture
def set_gates(monkeypatch: pytest.MonkeyPatch) -> Callable[..., None]:
    """set_gates(G28="PASSED"): the given gate statuses, every other gate NOT_TESTED."""
    from app.core import gates

    def apply(**statuses: str) -> None:
        now = {g: "NOT_TESTED" for g in gates.load_gate_status()} | statuses
        monkeypatch.setattr(gates, "_default_statuses", lambda: now)

    return apply


@pytest.fixture
def g26_passed(set_gates: Callable[..., None]) -> None:
    """Return links are trusted only once gate G26 passes (ACC-5.5)."""
    set_gates(G26="PASSED")
