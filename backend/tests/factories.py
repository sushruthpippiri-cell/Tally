"""Builders for tests in every phase. Amounts are passed as strings and stored as Decimal."""

import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import date

import pytest
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.agents import Agent, AgentCommand
from app.models.company import Company
from app.models.enums import AgentStatus, CommandStatus, CommandType, SyncMode


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


async def make_agent(session: AsyncSession, company: Company, name: str = "agent-1") -> Agent:
    agent = Agent(company_id=company.company_id, agent_name=name, status=AgentStatus.ACTIVE)
    session.add(agent)
    await session.flush()
    return agent


async def make_command(
    session: AsyncSession, agent: Agent, sync_mode: SyncMode = SyncMode.FULL
) -> AgentCommand:
    command = AgentCommand(
        company_id=agent.company_id,
        agent_id=agent.agent_id,
        command_type=CommandType.RUN_SYNC,
        sync_mode=sync_mode,
        status=CommandStatus.PENDING,
    )
    session.add(command)
    await session.flush()
    return command
