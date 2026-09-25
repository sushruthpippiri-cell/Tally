"""P3.8: claim, progress, result (AGT-1.2/1.3/1.6/1.7, AC-15, AC-17, D-035)."""

from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
import pytest
import time_machine
from sqlalchemy.ext.asyncio import AsyncSession

from app.jobs.agents import mark_offline
from app.models.agents import Agent
from app.models.company import Company, User
from app.models.enums import AgentStatus, RoleName
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
    "queue_status": {"records": 0, "dead_letter_count": 0, "full": False},
}


@pytest.fixture
async def company(session: AsyncSession) -> Company:
    return await make_company(session, tally_guid="guid-1")


@pytest.fixture
async def owner(session: AsyncSession, company: Company) -> User:
    return await make_user(session, company, RoleName.OWNER)


@pytest.fixture
async def agent(session: AsyncSession, company: Company) -> tuple[Agent, str]:
    return await make_registered_agent(session, company)


async def _call(
    api: httpx.AsyncClient, credential: str, command_id: object, step: str, **body: Any
) -> httpx.Response:
    return await api.post(
        f"/agent/commands/{command_id}/{step}", json=body or None, headers=agent_header(credential)
    )


@pytest.mark.req("AC-17", "AGT-1.6")
async def test_sync_now_is_claimed_run_and_completed_each_state_visible(
    api: httpx.AsyncClient, company: Company, owner: User, agent: tuple[Agent, str]
) -> None:
    _, credential = agent
    created = await api.post(
        f"/companies/{company.company_id}/sync",
        json={"sync_mode": "FULL"},
        headers=auth_header(owner),
    )
    command_id = created.json()["command_id"]
    status_url = f"/companies/{company.company_id}/commands/{command_id}"

    async def shown() -> str:
        return str((await api.get(status_url, headers=auth_header(owner))).json()["status"])

    assert await shown() == "PENDING"
    offered = await api.post(
        "/agent/heartbeat",
        json=BEAT | {"confirmed_tally_guid": "guid-1"},
        headers=agent_header(credential),
    )
    assert offered.json()["command"]["command_id"] == command_id
    r = await _call(api, credential, command_id, "claim")
    assert (r.status_code, r.json()["status"]) == (200, "CLAIMED"), r.text
    assert await shown() == "CLAIMED"
    r = await _call(api, credential, command_id, "progress")
    assert r.json()["status"] == "RUNNING"
    assert await shown() == "RUNNING"
    r = await _call(api, credential, command_id, "result", status="COMPLETED")
    assert r.json()["status"] == "COMPLETED"
    body = (await api.get(status_url, headers=auth_header(owner))).json()
    assert body["status"] == "COMPLETED" and body["completed_at"] is not None


@pytest.mark.req("AGT-1.3")
async def test_a_command_can_be_claimed_once(
    api: httpx.AsyncClient, session: AsyncSession, agent: tuple[Agent, str]
) -> None:
    row, credential = agent
    command = await make_command(session, row)
    assert (await _call(api, credential, command.command_id, "claim")).status_code == 200
    again = await _call(api, credential, command.command_id, "claim")
    assert (again.status_code, again.json()["code"]) == (409, "INVALID_COMMAND_STATE")


async def test_claim_sets_the_lease_and_progress_renews_it(
    api: httpx.AsyncClient, session: AsyncSession, agent: tuple[Agent, str]
) -> None:
    row, credential = agent
    command = await make_command(session, row)
    start = datetime.now(UTC)
    with time_machine.travel(start, tick=False):
        r = await _call(api, credential, command.command_id, "claim")
    assert datetime.fromisoformat(r.json()["lease_expires_at"]) == start + timedelta(seconds=300)
    with time_machine.travel(start + timedelta(seconds=240), tick=False):
        r = await _call(api, credential, command.command_id, "progress")
    assert datetime.fromisoformat(r.json()["lease_expires_at"]) == start + timedelta(seconds=540)


@pytest.mark.req("AGT-1.7")
async def test_progress_keeps_a_long_sync_alive_past_the_first_lease(
    api: httpx.AsyncClient, session: AsyncSession, agent: tuple[Agent, str]
) -> None:
    """A 25-minute sync (two 10-minute Tally exports and more) survives on 60 s progress."""
    row, credential = agent
    command = await make_command(session, row)
    start = datetime.now(UTC)
    with time_machine.travel(start, tick=False):
        await _call(api, credential, command.command_id, "claim")
    for minute in range(1, 26):
        with time_machine.travel(start + timedelta(minutes=minute), tick=False):
            r = await _call(api, credential, command.command_id, "progress")
            assert r.status_code == 200, f"lost at minute {minute}"
    with time_machine.travel(start + timedelta(minutes=25, seconds=30), tick=False):
        r = await _call(api, credential, command.command_id, "result", status="COMPLETED")
    assert r.json()["status"] == "COMPLETED"


async def test_progress_counts_as_a_heartbeat_so_a_busy_agent_never_goes_offline(
    api: httpx.AsyncClient, session: AsyncSession, agent: tuple[Agent, str]
) -> None:
    """D-035 #12: only progress calls for 12 minutes (threshold 5) and the Agent stays ACTIVE."""
    row, credential = agent
    command = await make_command(session, row)
    start = datetime.now(UTC)
    with time_machine.travel(start, tick=False):
        await _call(api, credential, command.command_id, "claim")
    for minute in range(1, 13):
        now = start + timedelta(minutes=minute)
        with time_machine.travel(now, tick=False):
            await _call(api, credential, command.command_id, "progress")
        await mark_offline(session, now + timedelta(seconds=30))
        await session.refresh(row)
        assert row.status == "ACTIVE", f"marked offline at minute {minute}"


async def test_progress_brings_an_offline_agent_back(
    api: httpx.AsyncClient, session: AsyncSession, agent: tuple[Agent, str]
) -> None:
    row, credential = agent
    command = await make_command(session, row)
    await _call(api, credential, command.command_id, "claim")
    row.status = AgentStatus.OFFLINE
    await session.flush()
    await _call(api, credential, command.command_id, "progress")
    await session.refresh(row)
    assert row.status == "ACTIVE"


async def test_completed_needs_running_failed_may_come_straight_after_claim(
    api: httpx.AsyncClient, session: AsyncSession, agent: tuple[Agent, str]
) -> None:
    row, credential = agent
    command = await make_command(session, row)
    await _call(api, credential, command.command_id, "claim")
    early = await _call(api, credential, command.command_id, "result", status="COMPLETED")
    assert (early.status_code, early.json()["code"]) == (409, "INVALID_COMMAND_STATE")
    r = await _call(
        api,
        credential,
        command.command_id,
        "result",
        status="FAILED",
        error_code="COMPANY_MISMATCH",
        error_message="Tally has another company open",
    )
    assert r.json()["status"] == "FAILED"
    await session.refresh(command)
    assert (command.error_code, command.error_message) == (
        "COMPANY_MISMATCH",
        "Tally has another company open",
    )
    assert command.completed_at is not None


@pytest.mark.parametrize(
    "body",
    [
        {"status": "FAILED"},
        {"status": "COMPLETED", "error_code": "PARSE_ERROR"},
        {"status": "RUNNING"},
        {"status": "FAILED", "error_code": "NOT_A_CODE"},
    ],
)
async def test_invalid_results_are_422(
    api: httpx.AsyncClient,
    session: AsyncSession,
    agent: tuple[Agent, str],
    body: dict[str, Any],
) -> None:
    row, credential = agent
    command = await make_command(session, row)
    await _call(api, credential, command.command_id, "claim")
    r = await api.post(
        f"/agent/commands/{command.command_id}/result", json=body, headers=agent_header(credential)
    )
    assert r.status_code == 422


async def test_one_command_at_a_time(
    api: httpx.AsyncClient, session: AsyncSession, agent: tuple[Agent, str]
) -> None:
    row, credential = agent
    first, second = await make_command(session, row), await make_command(session, row)
    await _call(api, credential, first.command_id, "claim")
    r = await _call(api, credential, second.command_id, "claim")
    assert (r.status_code, r.json()["message"]) == (409, "Agent already has a command in progress")
    await session.refresh(second)
    assert second.status == "PENDING"


async def test_a_pending_command_past_its_claim_window_cannot_be_claimed(
    api: httpx.AsyncClient, session: AsyncSession, agent: tuple[Agent, str]
) -> None:
    row, credential = agent
    command = await make_command(session, row)
    with time_machine.travel(datetime.now(UTC) + timedelta(minutes=10, seconds=1)):
        r = await _call(api, credential, command.command_id, "claim")
    assert r.status_code == 409


@pytest.mark.parametrize(
    ("status", "code"),
    [
        (AgentStatus.INCOMPATIBLE, "AGENT_INCOMPATIBLE"),
        (AgentStatus.REGISTERING, "INVALID_COMMAND_STATE"),
    ],
)
async def test_only_active_agents_may_claim(
    api: httpx.AsyncClient,
    session: AsyncSession,
    company: Company,
    status: AgentStatus,
    code: str,
) -> None:
    row, credential = await make_registered_agent(session, company, "x", status=status)
    command = await make_command(session, row)
    r = await _call(api, credential, command.command_id, "claim")
    assert (r.status_code, r.json()["code"]) == (409, code)


@pytest.mark.req("AC-15")
async def test_revoked_agent_gets_agent_revoked_and_no_command_by_any_route(
    api: httpx.AsyncClient, session: AsyncSession, company: Company
) -> None:
    row, credential = await make_registered_agent(
        session, company, "gone", status=AgentStatus.REVOKED
    )
    command = await make_command(session, row)
    beat = await api.post("/agent/heartbeat", json=BEAT, headers=agent_header(credential))
    claim = await _call(api, credential, command.command_id, "claim")
    for r in (beat, claim):
        assert (r.status_code, r.json()["code"]) == (401, "AGENT_REVOKED")
    await session.refresh(command)
    assert command.status == "PENDING"


async def test_agents_cannot_touch_other_agents_or_companies_commands(
    api: httpx.AsyncClient, session: AsyncSession, company: Company, agent: tuple[Agent, str]
) -> None:
    _, credential = agent
    sibling, _ = await make_registered_agent(session, company, "sibling")
    other_company = await make_company(session, name="Other")
    stranger, _ = await make_registered_agent(session, other_company, "stranger")
    for target in (sibling, stranger):
        command = await make_command(session, target)
        for step in ("claim", "progress"):
            r = await _call(api, credential, command.command_id, step)
            assert (r.status_code, r.json()["code"]) == (404, "NOT_FOUND")
        await session.refresh(command)
        assert command.status == "PENDING"
