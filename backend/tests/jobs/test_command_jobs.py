"""P3.9: expiry, lost Agents, and why finished commands never change (AGT-1.2/1.4/1.8/1.9/1.10,
AC-19, AC-20, TEST-3.2)."""

from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
import pytest
import time_machine
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.jobs import commands as command_jobs
from app.jobs.commands import LOST_REASON, expire_pending, mark_lost
from app.jobs.runner import LOCK_COMMAND_TIMEOUTS, build_scheduler
from app.models.agents import AgentCommand
from app.models.company import Company, User
from app.models.config import CompanySetting
from app.models.enums import AgentStatus, CommandStatus, RoleName, SettingDataType
from tally_contract.testing import assert_logged
from tests.factories import (
    agent_header,
    auth_header,
    make_command,
    make_company,
    make_registered_agent,
    make_user,
)

BEAT = {
    "agent_version": "1.0.0",
    "tdl_version": "1.0.0",
    "tally_status": "OK",
    "confirmed_tally_guid": "guid-1",
    "queue_status": {"records": 0, "dead_letter_count": 0, "full": False},
}


@pytest.fixture
async def company(session: AsyncSession) -> Company:
    return await make_company(session, tally_guid="guid-1")


@pytest.fixture
async def owner(session: AsyncSession, company: Company) -> User:
    return await make_user(session, company, RoleName.OWNER)


async def _step(
    api: httpx.AsyncClient, credential: str, command: AgentCommand, step: str, **body: Any
) -> httpx.Response:
    return await api.post(
        f"/agent/commands/{command.command_id}/{step}",
        json=body or None,
        headers=agent_header(credential),
    )


def _snapshot(c: AgentCommand) -> tuple[object, ...]:
    return (
        c.status,
        c.agent_id,
        c.claimed_at,
        c.lease_expires_at,
        c.completed_at,
        c.error_code,
        c.error_message,
    )


@pytest.mark.req("AC-19", "RTE-1.6")
async def test_offline_agent_command_waits_labelled_and_is_claimed_on_return(
    api: httpx.AsyncClient, session: AsyncSession, company: Company, owner: User
) -> None:
    agent, credential = await make_registered_agent(session, company, status=AgentStatus.OFFLINE)
    r = await api.post(
        f"/companies/{company.company_id}/sync",
        json={"sync_mode": "FULL"},
        headers=auth_header(owner),
    )
    body = r.json()
    assert body["status"] == "PENDING"
    assert body["waiting_label"].startswith("Waiting — Agent offline since ")
    assert await expire_pending(session, datetime.now(UTC) + timedelta(minutes=9)) == 0
    beat = await api.post("/agent/heartbeat", json=BEAT, headers=agent_header(credential))
    assert beat.json()["status"] == "ACTIVE"
    assert beat.json()["command"]["command_id"] == body["command_id"]
    command = await session.get(AgentCommand, beat.json()["command"]["command_id"])
    assert command is not None
    assert (await _step(api, credential, command, "claim")).json()["status"] == "CLAIMED"
    # ... unless it expires first:
    late = await make_command(session, agent)
    assert await expire_pending(session, datetime.now(UTC) + timedelta(minutes=10, seconds=1)) == 1
    await session.refresh(late)
    assert late.status == "EXPIRED"


@pytest.mark.req("AGT-1.10")
async def test_pending_expires_after_the_company_claim_timeout(
    session: AsyncSession, company: Company, caplog: pytest.LogCaptureFixture
) -> None:
    patient = await make_company(session, name="Patient")
    session.add(
        CompanySetting(
            company_id=patient.company_id,
            setting_key="agent.command_claim_timeout_minutes",
            setting_value=30,
            data_type=SettingDataType.INTEGER,
        )
    )
    agent, _ = await make_registered_agent(session, company)
    slow_agent, _ = await make_registered_agent(session, patient, "slow")
    default = await make_command(session, agent)
    waiting = await make_command(session, slow_agent)
    now = default.created_at + timedelta(minutes=10)
    assert await expire_pending(session, now - timedelta(seconds=1)) == 0
    assert await expire_pending(session, now) == 1
    await session.refresh(default)
    await session.refresh(waiting)
    assert (default.status, default.error_message) == ("EXPIRED", "Not claimed within 10 minutes")
    assert default.completed_at == now
    assert waiting.status == "PENDING"
    assert_logged(caplog, "command_expired", command_id=str(default.command_id))


@pytest.mark.req("AC-20", "TEST-3.2", "AGT-1.8")
async def test_a_running_command_past_its_lease_is_lost_and_never_reassigned(
    api: httpx.AsyncClient,
    session: AsyncSession,
    company: Company,
    caplog: pytest.LogCaptureFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    lost_hook: list[AgentCommand] = []

    async def spy(_: AsyncSession, command: AgentCommand) -> None:
        lost_hook.append(command)

    monkeypatch.setattr(command_jobs, "on_command_lost", spy)
    agent, credential = await make_registered_agent(session, company)
    standby, standby_credential = await make_registered_agent(session, company, "standby")
    command = await make_command(session, agent)
    start = datetime.now(UTC)
    with time_machine.travel(start, tick=False):
        await _step(api, credential, command, "claim")
        await _step(api, credential, command, "progress")
    # The Agent crashes: no more progress. Before the deadline nothing happens.
    assert await mark_lost(session, start + timedelta(seconds=299)) == 0
    assert await mark_lost(session, start + timedelta(seconds=300)) == 1
    await session.refresh(command)
    assert (command.status, command.error_message, command.agent_id) == (
        "FAILED_AGENT_LOST",
        LOST_REASON,
        agent.agent_id,
    )
    assert [c.command_id for c in lost_hook] == [command.command_id]
    assert_logged(caplog, "command_agent_lost", level="warning", command_id=str(command.command_id))
    for cred in (standby_credential, credential):  # offered to no one, ever again
        beat = await api.post("/agent/heartbeat", json=BEAT, headers=agent_header(cred))
        assert beat.json()["command"] is None
    assert await session.scalar(select(func.count()).select_from(AgentCommand)) == 1


@pytest.mark.req("AGT-1.9")
@pytest.mark.parametrize("final", ["FAILED_AGENT_LOST", "EXPIRED"])
async def test_late_calls_never_change_a_lost_or_expired_command(
    api: httpx.AsyncClient, session: AsyncSession, company: Company, final: str
) -> None:
    agent, credential = await make_registered_agent(session, company)
    command = await make_command(session, agent)
    start = datetime.now(UTC)
    if final == "FAILED_AGENT_LOST":
        with time_machine.travel(start, tick=False):
            await _step(api, credential, command, "claim")
            await _step(api, credential, command, "progress")
        await mark_lost(session, start + timedelta(minutes=6))
    else:
        await expire_pending(session, start + timedelta(minutes=11))
    await session.refresh(command)
    assert command.status == final
    before = _snapshot(command)
    late = [
        ("claim", {}),
        ("progress", {}),
        ("result", {"status": "COMPLETED"}),
        ("result", {"status": "FAILED", "error_code": "TALLY_EXPORT_TIMEOUT"}),
    ]
    for step, body in late:
        r = await _step(api, credential, command, step, **body)
        assert (r.status_code, r.json()["code"]) == (409, "INVALID_COMMAND_STATE"), step
        await session.refresh(command)
        assert _snapshot(command) == before, f"{step} changed a {final} command"


async def test_a_lapsed_lease_is_final_even_before_the_job_runs(
    api: httpx.AsyncClient, session: AsyncSession, company: Company
) -> None:
    """D-035 #2: after the deadline, progress cannot revive the command."""
    agent, credential = await make_registered_agent(session, company)
    command = await make_command(session, agent)
    start = datetime.now(UTC)
    with time_machine.travel(start, tick=False):
        await _step(api, credential, command, "claim")
    with time_machine.travel(start + timedelta(seconds=301), tick=False):
        progress = await _step(api, credential, command, "progress")
        done = await _step(
            api, credential, command, "result", status="FAILED", error_code="TALLY_EXPORT_TIMEOUT"
        )
    assert progress.status_code == done.status_code == 409
    await session.refresh(command)
    assert command.status == "CLAIMED"  # untouched until the job records the loss
    assert await mark_lost(session, start + timedelta(seconds=301)) == 1


@pytest.mark.req("AGT-1.4")
async def test_a_failed_command_is_not_retried(
    api: httpx.AsyncClient, session: AsyncSession, company: Company
) -> None:
    agent, credential = await make_registered_agent(session, company)
    command = await make_command(session, agent)
    await _step(api, credential, command, "claim")
    await _step(api, credential, command, "result", status="FAILED", error_code="TALLY_UNREACHABLE")
    await expire_pending(session, datetime.now(UTC) + timedelta(days=1))
    await mark_lost(session, datetime.now(UTC) + timedelta(days=1))
    beat = await api.post("/agent/heartbeat", json=BEAT, headers=agent_header(credential))
    assert beat.json()["command"] is None
    assert await session.scalar(select(func.count()).select_from(AgentCommand)) == 1


@pytest.mark.req("AGT-1.2")
async def test_every_command_state_and_path(
    api: httpx.AsyncClient, session: AsyncSession, company: Company
) -> None:
    assert [s.value for s in CommandStatus] == [
        "PENDING",
        "CLAIMED",
        "RUNNING",
        "COMPLETED",
        "FAILED",
        "EXPIRED",
        "FAILED_AGENT_LOST",
    ]
    agents = [await make_registered_agent(session, company, f"a{i}") for i in range(4)]
    done, failed, expired, lost = [await make_command(session, a) for a, _ in agents]
    seen: list[str] = []
    (_, c0), (_, c1), _, (_, c3) = agents
    start = datetime.now(UTC)
    with time_machine.travel(start, tick=False):
        seen.append((await _step(api, c0, done, "claim")).json()["status"])
        seen.append((await _step(api, c0, done, "progress")).json()["status"])
        seen.append((await _step(api, c0, done, "result", status="COMPLETED")).json()["status"])
        await _step(api, c1, failed, "claim")
        seen.append(
            (
                await _step(api, c1, failed, "result", status="FAILED", error_code="PARSE_ERROR")
            ).json()["status"]
        )
        await _step(api, c3, lost, "claim")
    await session.refresh(expired)
    seen.insert(0, expired.status)
    await expire_pending(session, start + timedelta(minutes=11))
    await mark_lost(session, start + timedelta(minutes=11))
    for c in (expired, lost):
        await session.refresh(c)
    seen += [expired.status, lost.status]
    assert seen == [
        "PENDING",
        "CLAIMED",
        "RUNNING",
        "COMPLETED",
        "FAILED",
        "EXPIRED",
        "FAILED_AGENT_LOST",
    ]


def test_timeouts_run_every_minute_under_their_own_lock() -> None:
    job = build_scheduler().get_job("command_timeouts")
    assert job is not None and job.args[0] == LOCK_COMMAND_TIMEOUTS
    assert job.trigger.interval == timedelta(seconds=60)
