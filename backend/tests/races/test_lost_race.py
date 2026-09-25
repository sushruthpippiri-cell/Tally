"""The lost-Agent job racing a late progress call, on real connections (AGT-1.8, D-035 #2)."""

import asyncio
from datetime import UTC, datetime, timedelta

import time_machine
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.agent_credentials import AgentContext
from app.core.errors import AppError
from app.jobs.commands import mark_lost
from app.models.agents import AgentCommand
from app.models.enums import AgentStatus
from app.services.commands import claim, progress
from tests.factories import make_command, make_company, make_registered_agent

Factory = async_sessionmaker[AsyncSession]


async def _claimed(committed: Factory, start: datetime) -> tuple[AgentContext, AgentCommand]:
    async with committed() as s:
        company = await make_company(s)
        agent, _ = await make_registered_agent(s, company)
        command = await make_command(s, agent)
        await s.commit()
    ctx = AgentContext(agent.agent_id, company.company_id, AgentStatus.ACTIVE)
    with time_machine.travel(start, tick=False):
        async with committed() as s:
            await claim(s, ctx, command.command_id)
    return ctx, command


async def _progress(committed: Factory, ctx: AgentContext, command: AgentCommand) -> str:
    async with committed() as s:
        try:
            return str((await progress(s, ctx, command.command_id)).status)
        except AppError as exc:
            return str(exc.http_status)


async def _status(committed: Factory) -> str:
    async with committed() as s:
        return str(await s.scalar(select(AgentCommand.status)))


async def test_on_time_progress_blocked_behind_the_lost_job_cannot_revive_it(
    committed: Factory,
) -> None:
    """Progress sent 1 s before the deadline reaches the row while the job (1 s after it) holds
    the lock. It must wait, then re-check the committed row and lose: once LOST, always LOST.
    (A progress call already past the deadline does not even wait: its condition is false.)"""
    start = datetime.now(UTC)
    ctx, command = await _claimed(committed, start)
    deadline = start + timedelta(seconds=300)
    async with committed() as job:
        assert await mark_lost(job, deadline + timedelta(seconds=1)) == 1  # holds the lock
        with time_machine.travel(deadline - timedelta(seconds=1), tick=False):
            racer = asyncio.create_task(_progress(committed, ctx, command))
            await asyncio.sleep(0.3)
            assert not racer.done(), "an on-time progress must wait on the job's row lock"
            await job.commit()
            assert await racer == "409"
    assert await _status(committed) == "FAILED_AGENT_LOST"


async def test_job_and_late_progress_at_once_end_lost_every_time(committed: Factory) -> None:
    start = datetime.now(UTC)
    ctx, command = await _claimed(committed, start)
    late = start + timedelta(minutes=6)

    async def job() -> int:
        async with committed() as s:
            changed = await mark_lost(s, late)
            await s.commit()
            return changed

    with time_machine.travel(late, tick=False):
        changed, *answers = await asyncio.gather(
            job(), *(_progress(committed, ctx, command) for _ in range(5))
        )
    assert changed == 1
    assert answers == ["409"] * 5
    assert await _status(committed) == "FAILED_AGENT_LOST"
