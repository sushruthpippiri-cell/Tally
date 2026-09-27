"""The sync lease on real, committing connections (SYNC-4.1/4.2, AC-09, TEST-3.1)."""

import asyncio
from datetime import UTC, datetime

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.agent_credentials import AgentContext
from app.core.errors import AppError
from app.models.enums import CollectionType
from app.models.sync import SyncWatermark
from app.sync import leases
from tests.factories import agent_context, make_company, make_registered_agent, make_running_command

Factory = async_sessionmaker[AsyncSession]


async def _agents(committed: Factory, n: int) -> list[AgentContext]:
    async with committed() as s:
        company = await make_company(s)
        # The row already exists, as after a first sync: then only the compare-and-set itself
        # can stop two Agents (a missing row would be serialised by its INSERT instead).
        s.add(SyncWatermark(company_id=company.company_id, collection_type="VOUCHER"))
        contexts = []
        for i in range(n):
            agent, _ = await make_registered_agent(s, company, f"agent-{i}")
            await make_running_command(s, agent)
            contexts.append(agent_context(agent))
        await s.commit()
    return contexts


async def _acquire(committed: Factory, agent: AgentContext) -> str:
    async with committed() as s:
        try:
            await leases.acquire(s, agent, CollectionType.VOUCHER, datetime.now(UTC))
            await s.commit()
        except AppError as exc:
            return exc.code.value
        return "LEASED"


async def _holder(committed: Factory) -> object:
    async with committed() as s:
        return await s.scalar(select(SyncWatermark.locked_by_agent_id))


@pytest.mark.req("AC-09", "TEST-3.1", "SYNC-4.1", "SYNC-4.2")
async def test_two_agents_at_once_exactly_one_gets_the_lease(committed: Factory) -> None:
    a, b = await _agents(committed, 2)
    results = await asyncio.gather(_acquire(committed, a), _acquire(committed, b))
    assert sorted(results) == ["LEASED", "SYNC_LOCKED"]
    winner = a if results[0] == "LEASED" else b
    assert await _holder(committed) == winner.agent_id


async def test_ten_agents_at_once_exactly_one_gets_the_lease(committed: Factory) -> None:
    agents = await _agents(committed, 10)
    results = await asyncio.gather(*(_acquire(committed, a) for a in agents))
    assert results.count("LEASED") == 1 and results.count("SYNC_LOCKED") == 9


async def test_an_acquire_blocked_behind_an_uncommitted_one_is_refused(committed: Factory) -> None:
    """The case a read-then-write gets wrong: B reads 'free' while A is uncommitted."""
    a, b = await _agents(committed, 2)
    async with committed() as first:
        await leases.acquire(first, a, CollectionType.VOUCHER, datetime.now(UTC))
        second = asyncio.create_task(_acquire(committed, b))
        await asyncio.sleep(0.3)
        assert not second.done(), "B must wait on A's row lock"
        await first.commit()
    assert await second == "SYNC_LOCKED"
    assert await _holder(committed) == a.agent_id
