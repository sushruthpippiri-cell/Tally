"""P3.5: heartbeat and polling (AGT-1.1, VER-1.x, AGT-3.4, D-025, D-035 #13)."""

from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
import pytest
import time_machine
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.models.agents import Agent
from app.models.company import Company
from app.models.enums import AgentStatus, CommandStatus
from tests.factories import (
    agent_header,
    make_command,
    make_company,
    make_registered_agent,
)

GUID = "guid-sharma-traders"


def _beat(**kw: Any) -> dict[str, Any]:
    return {
        "agent_version": "1.2.0",
        "tdl_version": "1.0.0",
        "tally_version": "TallyPrime 5.1",
        "tally_uptime_seconds": 3600,
        "queue_status": {
            "records": 0,
            "oldest_age_seconds": None,
            "dead_letter_count": 0,
            "full": False,
        },
        "tally_status": "OK",
        "confirmed_tally_guid": GUID,
    } | kw


@pytest.fixture
async def company(session: AsyncSession) -> Company:
    return await make_company(session, tally_guid=GUID)


async def _heartbeat(api: httpx.AsyncClient, credential: str, **kw: Any) -> httpx.Response:
    return await api.post("/agent/heartbeat", json=_beat(**kw), headers=agent_header(credential))


@pytest.mark.req("AGT-1.1", "VER-1.1")
async def test_heartbeat_records_versions_uptime_and_queue(
    api: httpx.AsyncClient, session: AsyncSession, company: Company
) -> None:
    agent, credential = await make_registered_agent(session, company, last_heartbeat_at=None)
    r = await _heartbeat(
        api,
        credential,
        queue_status={
            "records": 12,
            "oldest_age_seconds": 40,
            "dead_letter_count": 1,
            "full": False,
        },
    )
    assert r.status_code == 200, r.text
    await session.refresh(agent)
    assert (agent.agent_version, agent.tdl_version, agent.tally_version) == (
        "1.2.0",
        "1.0.0",
        "TallyPrime 5.1",
    )
    assert agent.tally_uptime_seconds == 3600
    assert agent.queue_status == {
        "records": 12,
        "oldest_age_seconds": 40,
        "dead_letter_count": 1,
        "full": False,
    }
    assert agent.last_heartbeat_at is not None
    assert r.json()["config"]["poll_interval_seconds"] == 30  # AGT-1.1 default


async def test_registering_becomes_active_only_on_the_confirmed_guid(
    api: httpx.AsyncClient, session: AsyncSession, company: Company
) -> None:
    agent, credential = await make_registered_agent(
        session, company, status=AgentStatus.REGISTERING
    )
    r = await _heartbeat(
        api, credential, confirmed_tally_guid=None, tally_status="TALLY_UNREACHABLE"
    )
    assert r.json()["status"] == "REGISTERING"
    r = await _heartbeat(api, credential)
    assert r.json()["status"] == "ACTIVE"


async def test_offline_agent_becomes_active_on_any_heartbeat(
    api: httpx.AsyncClient, session: AsyncSession, company: Company
) -> None:
    _, credential = await make_registered_agent(session, company, status=AgentStatus.OFFLINE)
    r = await _heartbeat(
        api, credential, confirmed_tally_guid=None, tally_status="TALLY_UNREACHABLE"
    )
    assert r.json()["status"] == "ACTIVE"


@pytest.mark.req("AC-22", "VER-1.2")
async def test_below_minimum_version_is_incompatible_and_gets_no_command(
    api: httpx.AsyncClient,
    session: AsyncSession,
    company: Company,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(get_settings(), "min_agent_version", "1.5.0")
    monkeypatch.setattr(get_settings(), "min_tdl_version", "1.0.0")
    agent, credential = await make_registered_agent(session, company)
    await make_command(session, agent)
    for beat in (_beat(agent_version="1.4.9"), _beat(agent_version="2.0.0", tdl_version="0.9")):
        r = await api.post("/agent/heartbeat", json=beat, headers=agent_header(credential))
        assert r.json()["status"] == "INCOMPATIBLE"
        assert r.json()["command"] is None
        assert any(w.startswith("INCOMPATIBLE") for w in r.json()["warnings"])
    r = await _heartbeat(api, credential, agent_version="1.5.0")  # upgraded
    assert r.json()["status"] == "ACTIVE"
    assert r.json()["command"] is not None


async def test_unparseable_versions_are_422(
    api: httpx.AsyncClient, session: AsyncSession, company: Company
) -> None:
    _, credential = await make_registered_agent(session, company)
    assert (await _heartbeat(api, credential, agent_version="latest")).status_code == 422


@pytest.mark.req_partial("AC-15")  # "no commands" also needs claim to reject it: P3.8
async def test_revoked_agent_gets_agent_revoked_and_no_command(
    api: httpx.AsyncClient, session: AsyncSession, company: Company
) -> None:
    agent, credential = await make_registered_agent(session, company, status=AgentStatus.REVOKED)
    await make_command(session, agent)
    r = await _heartbeat(api, credential)
    assert (r.status_code, r.json()["code"]) == (401, "AGENT_REVOKED")
    assert "command" not in r.json()


async def test_tally_status_since_changes_only_when_the_status_changes(
    api: httpx.AsyncClient, session: AsyncSession, company: Company
) -> None:
    agent, credential = await make_registered_agent(session, company)
    start = datetime.now(UTC)
    with time_machine.travel(start, tick=False):
        await _heartbeat(api, credential, tally_status="TALLY_UNREACHABLE")
    with time_machine.travel(start + timedelta(minutes=1), tick=False):
        await _heartbeat(api, credential, tally_status="TALLY_UNREACHABLE")
    await session.refresh(agent)
    assert (agent.last_tally_status, agent.tally_status_since) == ("TALLY_UNREACHABLE", start)
    with time_machine.travel(start + timedelta(minutes=2), tick=False):
        await _heartbeat(api, credential, tally_status="OK")
    await session.refresh(agent)
    assert (agent.last_tally_status, agent.tally_status_since) == (
        "OK",
        start + timedelta(minutes=2),
    )


@pytest.mark.req("AGT-3.4")
async def test_company_mismatch_warns_and_never_rebinds(
    api: httpx.AsyncClient, session: AsyncSession, company: Company
) -> None:
    agent, credential = await make_registered_agent(session, company)
    r = await _heartbeat(
        api, credential, tally_status="COMPANY_MISMATCH", confirmed_tally_guid="guid-other"
    )
    assert r.json()["status"] == "ACTIVE"
    assert any(w.startswith("COMPANY_MISMATCH") for w in r.json()["warnings"])
    await session.refresh(agent)
    await session.refresh(company)
    assert agent.tally_guid == company.tally_guid == GUID
    # A REGISTERING Agent reporting the wrong company is not confirmed.
    _, pending = await make_registered_agent(
        session, company, name="new", status=AgentStatus.REGISTERING
    )
    r = await _heartbeat(api, pending, confirmed_tally_guid="guid-other")
    assert r.json()["status"] == "REGISTERING"


async def test_the_oldest_pending_command_is_offered(
    api: httpx.AsyncClient, session: AsyncSession, company: Company
) -> None:
    agent, credential = await make_registered_agent(session, company)
    first = await make_command(session, agent)
    await make_command(session, agent)
    other_agent, _ = await make_registered_agent(session, company, name="other")
    await make_command(session, other_agent)
    r = await _heartbeat(api, credential)
    assert r.json()["command"]["command_id"] == str(first.command_id)
    assert r.json()["command"]["sync_mode"] == "FULL"


async def test_commands_created_at_the_same_instant_are_offered_in_creation_order(
    api: httpx.AsyncClient, session: AsyncSession, company: Company
) -> None:
    """D-036 #1: equal created_at is broken by seq, never by a random id."""
    agent, credential = await make_registered_agent(session, company)
    same = datetime.now(UTC)
    commands = [await make_command(session, agent) for _ in range(5)]
    for command in commands:
        command.created_at = same
    await session.flush()
    for command in commands:
        await session.refresh(command)
    assert [c.seq for c in commands] == sorted(c.seq for c in commands)
    r = await _heartbeat(api, credential)
    assert r.json()["command"]["command_id"] == str(commands[0].command_id)


async def test_no_new_command_while_one_is_in_progress(
    api: httpx.AsyncClient, session: AsyncSession, company: Company
) -> None:
    agent, credential = await make_registered_agent(session, company)
    running = await make_command(session, agent)
    running.status = CommandStatus.RUNNING
    waiting = await make_command(session, agent)
    await session.flush()
    assert (await _heartbeat(api, credential)).json()["command"] is None
    running.status = CommandStatus.COMPLETED
    await session.flush()
    r = await _heartbeat(api, credential)
    assert r.json()["command"]["command_id"] == str(waiting.command_id)


async def test_an_expired_pending_command_is_not_offered(
    api: httpx.AsyncClient, session: AsyncSession, company: Company
) -> None:
    agent, credential = await make_registered_agent(session, company)
    await make_command(session, agent)
    with time_machine.travel(datetime.now(UTC) + timedelta(minutes=11)):
        r = await _heartbeat(api, credential)
    assert r.json()["command"] is None


async def test_queue_full_is_reported_as_a_warning(
    api: httpx.AsyncClient, session: AsyncSession, company: Company
) -> None:
    _, credential = await make_registered_agent(session, company)
    r = await _heartbeat(
        api,
        credential,
        queue_status={
            "records": 50000,
            "oldest_age_seconds": 10,
            "dead_letter_count": 0,
            "full": True,
        },
    )
    assert any(w.startswith("QUEUE_FULL") for w in r.json()["warnings"])


async def test_an_agent_is_scoped_to_its_own_row(
    api: httpx.AsyncClient, session: AsyncSession, company: Company
) -> None:
    other_company = await make_company(session, name="Other", tally_guid="guid-other-co")
    theirs, _ = await make_registered_agent(session, other_company, name="theirs")
    _, credential = await make_registered_agent(session, company)
    await _heartbeat(api, credential)
    await session.refresh(theirs)
    assert theirs.agent_version == "1.0.0"  # untouched
    assert isinstance(theirs, Agent)
