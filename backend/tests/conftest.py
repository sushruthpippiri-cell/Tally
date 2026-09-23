"""Backend test setup: tests use the real `tally_test` database (docker compose), never dev."""

import os
from collections.abc import AsyncIterator

import pytest
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
        s = AsyncSession(bind=conn, join_transaction_mode="create_savepoint")
        try:
            yield s
        finally:
            await s.close()
            await outer.rollback()
    await engine.dispose()
