"""P3.10: firing schedules (D-036 #2-4, RTE-1.3, TZ-1.1)."""

from datetime import UTC, datetime, timedelta

import httpx
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.jobs.runner import LOCK_FIRE_SCHEDULES, build_scheduler
from app.jobs.schedules import fire_schedules
from app.models.agents import Agent, AgentCommand, SyncSchedule
from app.models.company import Company
from app.models.enums import AgentStatus, SyncMode
from app.services.schedules import activate
from tests.factories import agent_header, make_company, make_registered_agent

IST = "Asia/Kolkata"
# 26 Sep 2026 02:00 IST == 25 Sep 20:30 UTC
TWO_AM_IST = datetime(2026, 9, 25, 20, 30, tzinfo=UTC)
BEAT = {
    "agent_version": "1.0.0",
    "tdl_version": "1.0.0",
    "tally_status": "OK",
    "queue_status": {"records": 0, "dead_letter_count": 0, "full": False},
}


@pytest.fixture
async def company(session: AsyncSession) -> Company:
    return await make_company(session, tz=IST, tally_guid="guid-1")


async def _schedule(
    session: AsyncSession, agent: Agent, cron: str, mode: SyncMode, activated_at: datetime
) -> SyncSchedule:
    schedule = SyncSchedule(
        company_id=agent.company_id,
        agent_id=agent.agent_id,
        cron_expression=cron,
        sync_mode=mode,
        is_active=False,
    )
    activate(schedule, IST, activated_at)
    session.add(schedule)
    await session.flush()
    return schedule


async def _commands(session: AsyncSession) -> list[AgentCommand]:
    rows = await session.execute(
        select(AgentCommand).order_by(AgentCommand.created_at, AgentCommand.seq)
    )
    return list(rows.scalars())


@pytest.mark.parametrize("insert_order", ["incremental_first", "reconciliation_first"])
async def test_at_2am_incremental_is_created_before_reconciliation(
    api: httpx.AsyncClient, session: AsyncSession, company: Company, insert_order: str
) -> None:
    """D-036 #3: reconciliation must compare against the latest data, whatever order the
    schedules were created in."""
    agent, credential = await make_registered_agent(session, company)
    before = TWO_AM_IST - timedelta(minutes=30)
    specs = [("0 * * * *", SyncMode.INCREMENTAL), ("0 2 * * *", SyncMode.RECONCILIATION)]
    if insert_order == "reconciliation_first":
        specs.reverse()
    made = [await _schedule(session, agent, cron, mode, before) for cron, mode in specs]
    assert {s.next_fire_at for s in made} == {TWO_AM_IST}

    assert await fire_schedules(session, TWO_AM_IST + timedelta(seconds=30)) == 2
    commands = await _commands(session)
    assert [c.sync_mode for c in commands] == ["INCREMENTAL", "RECONCILIATION"]
    assert commands[0].created_at == commands[1].created_at  # same instant ...
    assert commands[0].seq < commands[1].seq  # ... ordered by seq
    assert all(c.created_by is None for c in commands)
    offered = await api.post(
        "/agent/heartbeat",
        json=BEAT | {"confirmed_tally_guid": "guid-1"},
        headers=agent_header(credential),
    )
    assert offered.json()["command"]["sync_mode"] == "INCREMENTAL"
    by_mode = {s.sync_mode: s.next_fire_at for s in made}
    assert by_mode["INCREMENTAL"] == TWO_AM_IST + timedelta(hours=1)
    assert by_mode["RECONCILIATION"] == TWO_AM_IST + timedelta(days=1)


async def test_missed_runs_coalesce_into_one_command(
    session: AsyncSession, company: Company
) -> None:
    agent, _ = await make_registered_agent(session, company)
    hourly = await _schedule(
        session, agent, "0 * * * *", SyncMode.INCREMENTAL, TWO_AM_IST - timedelta(hours=6)
    )
    now = TWO_AM_IST + timedelta(minutes=10)  # six hourly runs were missed
    assert await fire_schedules(session, now) == 1
    assert hourly.next_fire_at == TWO_AM_IST + timedelta(hours=1)
    assert await fire_schedules(session, now) == 0


async def test_inactive_schedules_never_fire(session: AsyncSession, company: Company) -> None:
    agent, _ = await make_registered_agent(session, company)
    schedule = await _schedule(
        session, agent, "0 * * * *", SyncMode.INCREMENTAL, TWO_AM_IST - timedelta(hours=2)
    )
    schedule.is_active, schedule.next_fire_at = False, None
    await session.flush()
    assert await fire_schedules(session, TWO_AM_IST + timedelta(days=2)) == 0


async def test_offline_agents_get_commands_revoked_ones_are_skipped(
    session: AsyncSession, company: Company
) -> None:
    offline, _ = await make_registered_agent(session, company, "off", status=AgentStatus.OFFLINE)
    revoked, _ = await make_registered_agent(session, company, "gone", status=AgentStatus.REVOKED)
    for agent in (offline, revoked):
        await _schedule(
            session, agent, "0 * * * *", SyncMode.INCREMENTAL, TWO_AM_IST - timedelta(minutes=30)
        )
    assert await fire_schedules(session, TWO_AM_IST) == 1
    assert [c.agent_id for c in await _commands(session)] == [offline.agent_id]
    skipped = (
        await session.execute(select(SyncSchedule).where(SyncSchedule.agent_id == revoked.agent_id))
    ).scalar_one()
    assert skipped.next_fire_at == TWO_AM_IST + timedelta(hours=1)  # advanced, not stuck


def test_schedules_fire_every_minute_under_their_own_lock() -> None:
    job = build_scheduler().get_job("fire_schedules")
    assert job is not None and job.args[0] == LOCK_FIRE_SCHEDULES
