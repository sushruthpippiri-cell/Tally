"""Claim races on real, committing connections (AGT-1.3, D-035 #13).

The rollback fixture cannot prove a compare-and-set: everything there runs on one connection.
Here each claim has its own connection and really commits.
"""

import asyncio
import uuid
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.agent_credentials import AgentContext
from app.core.errors import AppError
from app.models.agents import Agent, AgentCommand
from app.models.enums import AgentStatus
from app.services.commands import claim, claim_uncommitted
from tests.factories import make_command, make_company, make_registered_agent

Factory = async_sessionmaker[AsyncSession]


async def _setup(committed: Factory, commands: int = 1) -> tuple[AgentContext, list[uuid.UUID]]:
    async with committed() as s:
        company = await make_company(s)
        agent, _ = await make_registered_agent(s, company)
        made = [await make_command(s, agent) for _ in range(commands)]
        await s.commit()
    ctx = AgentContext(agent.agent_id, company.company_id, AgentStatus.ACTIVE)
    return ctx, [c.command_id for c in made]


async def _claim(committed: Factory, ctx: AgentContext, command_id: uuid.UUID) -> str:
    async with committed() as s:
        try:
            await claim(s, ctx, command_id)
        except AppError as exc:
            return f"{exc.http_status} {exc.message}"
        return "CLAIMED"


async def _statuses(committed: Factory) -> list[str]:
    async with committed() as s:
        return list(
            (await s.execute(select(AgentCommand.status).order_by(AgentCommand.seq))).scalars()
        )


async def test_ten_simultaneous_claims_of_one_command_succeed_once(committed: Factory) -> None:
    ctx, [command_id] = await _setup(committed)
    results = await asyncio.gather(*(_claim(committed, ctx, command_id) for _ in range(10)))
    assert results.count("CLAIMED") == 1
    assert len([r for r in results if r.startswith("409")]) == 9
    assert await _statuses(committed) == ["CLAIMED"]


async def test_claims_blocked_behind_an_uncommitted_claim_all_lose(committed: Factory) -> None:
    """The case a read-then-write gets wrong: everyone reads PENDING while T1 is uncommitted."""
    ctx, [command_id] = await _setup(committed)
    async with committed() as first:
        await claim_uncommitted(first, ctx, command_id, datetime.now(UTC))
        losers = [asyncio.create_task(_claim(committed, ctx, command_id)) for _ in range(9)]
        await asyncio.sleep(0.3)
        assert not any(t.done() for t in losers), "the others must wait on T1's row lock"
        await first.commit()
    results = await asyncio.gather(*losers)
    assert all(r.startswith("409") for r in results), results
    assert await _statuses(committed) == ["CLAIMED"]


async def test_one_agent_claiming_two_commands_at_once_gets_exactly_one(committed: Factory) -> None:
    """D-035 #13: different rows, so only the partial unique index can stop the second."""
    ctx, command_ids = await _setup(committed, commands=2)
    results = await asyncio.gather(*(_claim(committed, ctx, c) for c in command_ids))
    assert sorted(results) == ["409 Agent already has a command in progress", "CLAIMED"]
    assert sorted(await _statuses(committed)) == ["CLAIMED", "PENDING"]


async def test_second_command_blocked_behind_an_uncommitted_claim_is_refused(
    committed: Factory,
) -> None:
    ctx, [first_id, second_id] = await _setup(committed, commands=2)
    async with committed() as first:
        await claim_uncommitted(first, ctx, first_id, datetime.now(UTC))
        second = asyncio.create_task(_claim(committed, ctx, second_id))
        await asyncio.sleep(0.3)
        assert not second.done(), "the index check must wait for T1"
        await first.commit()
    assert await second == "409 Agent already has a command in progress"
    async with committed() as s:
        assert await s.scalar(select(Agent.status)) == "ACTIVE"
