"""P3.6: offline detection and the advisory-locked job runner (SRS 4.5, D-017)."""

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.jobs.agents import mark_offline
from app.jobs.runner import LOCK_MARK_OFFLINE, build_scheduler, run_exclusive
from app.models.agents import Agent
from app.models.config import CompanySetting
from app.models.enums import AgentStatus, SettingDataType
from tally_contract.testing import assert_logged
from tests.factories import make_company, make_registered_agent

NOW = datetime(2026, 9, 25, 12, 0, tzinfo=UTC)


def _ago(minutes: float) -> datetime:
    return NOW - timedelta(minutes=minutes)


async def test_silent_active_agents_go_offline_after_the_company_threshold(
    session: AsyncSession, caplog: pytest.LogCaptureFixture
) -> None:
    default_co = await make_company(session, name="Default 5 min")
    patient_co = await make_company(session, name="Threshold 10 min")
    session.add(
        CompanySetting(
            company_id=patient_co.company_id,
            setting_key="agent.offline_threshold_minutes",
            setting_value=10,
            data_type=SettingDataType.INTEGER,
        )
    )
    silent, _ = await make_registered_agent(
        session, default_co, "silent", last_heartbeat_at=_ago(6)
    )
    recent, _ = await make_registered_agent(
        session, default_co, "recent", last_heartbeat_at=_ago(4)
    )
    patient, _ = await make_registered_agent(
        session, patient_co, "patient", last_heartbeat_at=_ago(6)
    )
    late, _ = await make_registered_agent(session, patient_co, "late", last_heartbeat_at=_ago(11))
    others = [
        (
            await make_registered_agent(
                session, default_co, name, status=status, last_heartbeat_at=_ago(60)
            )
        )[0]
        for name, status in [
            ("reg", AgentStatus.REGISTERING),
            ("old", AgentStatus.INCOMPATIBLE),
            ("gone", AgentStatus.REVOKED),
        ]
    ]
    assert await mark_offline(session, NOW) == 2
    for agent in (silent, recent, patient, late, *others):
        await session.refresh(agent)
    assert (silent.status, late.status) == ("OFFLINE", "OFFLINE")
    assert (recent.status, patient.status) == ("ACTIVE", "ACTIVE")
    assert [a.status for a in others] == ["REGISTERING", "INCOMPATIBLE", "REVOKED"]
    assert_logged(caplog, "agent_offline", agent_id=str(silent.agent_id))
    assert await mark_offline(session, NOW) == 0  # idempotent


async def test_only_one_run_at_a_time_across_replicas(
    committed: async_sessionmaker[AsyncSession], caplog: pytest.LogCaptureFixture
) -> None:
    """D-017 on real connections: while one replica holds the job's advisory lock, another
    replica's run is skipped rather than doing the work twice."""
    async with committed() as s:
        company = await make_company(s)
        await make_registered_agent(
            s, company, last_heartbeat_at=datetime.now(UTC) - timedelta(hours=1)
        )
        await s.commit()

    async with committed() as other_replica, other_replica.begin():
        assert await other_replica.scalar(select(func.pg_try_advisory_xact_lock(LOCK_MARK_OFFLINE)))
        assert await run_exclusive(LOCK_MARK_OFFLINE, mark_offline, committed) is None
        assert_logged(caplog, "job_skipped_locked", lock_key=LOCK_MARK_OFFLINE)
        async with committed() as check:
            assert await check.scalar(select(Agent.status)) == "ACTIVE"
    # The lock ends with that transaction; the next run does the work, once.
    assert await run_exclusive(LOCK_MARK_OFFLINE, mark_offline, committed) == 1
    assert await run_exclusive(LOCK_MARK_OFFLINE, mark_offline, committed) == 0


def test_the_scheduler_runs_offline_detection_every_minute() -> None:
    scheduler = build_scheduler()
    job = scheduler.get_job("mark_offline")
    assert job is not None
    assert job.trigger.interval == timedelta(seconds=60)
    assert job.args == (LOCK_MARK_OFFLINE, mark_offline)
