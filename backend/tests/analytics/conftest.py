import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from tests.analytics.books import Books, make_books


@pytest.fixture
async def books(session: AsyncSession) -> Books:
    return await make_books(session)
