"""Builders for tests in every phase. Amounts are passed as strings and stored as Decimal."""

import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import date

import pytest
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.company import Company


@asynccontextmanager
async def db_error(session: AsyncSession, match: str) -> AsyncIterator[None]:
    """Expect the database to reject what the block does (run in a savepoint, then rolled back)."""
    with pytest.raises(DBAPIError, match=match):
        async with session.begin_nested():
            yield


def guid() -> str:
    return str(uuid.uuid4())


async def make_company(
    session: AsyncSession,
    fy_start: date = date(2024, 4, 1),
    tz: str = "Asia/Kolkata",
    name: str = "Test Traders",
    tally_guid: str | None = None,
) -> Company:
    company = Company(
        name=name, financial_year_start=fy_start, company_timezone=tz, tally_guid=tally_guid
    )
    session.add(company)
    await session.flush()
    return company
