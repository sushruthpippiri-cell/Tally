"""P3.11: Agents view, rotation, revocation, Tally settings, and replacing an Agent
(SEC-2.1/2.3, AC-16, AC-24, AGT-4.2, FR-4.4, D-036 #6)."""

from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.jobs.schedules import fire_schedules
from app.models.agents import SyncSchedule
from app.models.company import Company, User
from app.models.config import AuditLog
from app.models.enums import AgentStatus, RoleName
from app.services.agent_admin import NO_ACTIVE_SCHEDULE
from app.services.schedules import activate
from tests.factories import (
    agent_header,
    auth_header,
    make_company,
    make_registered_agent,
    make_registration_token,
    make_user,
)

GUID = "guid-sharma"
BEAT = {
    "agent_version": "1.0.0",
    "tdl_version": "1.0.0",
    "tally_status": "OK",
    "confirmed_tally_guid": GUID,
    "queue_status": {"records": 0, "dead_letter_count": 0, "full": False},
}


@pytest.fixture
async def company(session: AsyncSession) -> Company:
    return await make_company(session, tz="Asia/Kolkata")


@pytest.fixture
async def owner(session: AsyncSession, company: Company) -> User:
    return await make_user(session, company, RoleName.OWNER)


def _agents(company: Company) -> str:
    return f"/companies/{company.company_id}/agents"


async def _beat(api: httpx.AsyncClient, credential: str) -> httpx.Response:
    return await api.post("/agent/heartbeat", json=BEAT, headers=agent_header(credential))


async def _register(
    api: httpx.AsyncClient, session: AsyncSession, company: Company, name: str
) -> dict[str, Any]:
    token = await make_registration_token(session, company)
    r = await api.post(
        "/agent/register",
        json={
            "token": token,
            "agent_name": name,
            "tally_guid": GUID,
            "tally_company_name": "Sharma Traders",
            "agent_version": "1.0.0",
            "tdl_version": "1.0.0",
        },
    )
    assert r.status_code == 201, r.text
    body: dict[str, Any] = r.json()
    return body


async def _schedules(session: AsyncSession, agent_id: str) -> list[SyncSchedule]:
    rows = await session.execute(
        select(SyncSchedule)
        .where(SyncSchedule.agent_id == agent_id)
        .order_by(SyncSchedule.cron_expression)
    )
    return list(rows.scalars())


@pytest.mark.req("AC-16")
async def test_rotation_invalidates_the_old_credential_and_the_new_one_works(
    api: httpx.AsyncClient, session: AsyncSession, company: Company, owner: User
) -> None:
    agent, old = await make_registered_agent(session, company)
    r = await api.post(
        f"{_agents(company)}/{agent.agent_id}/rotate-credential", headers=auth_header(owner)
    )
    assert r.status_code == 200, r.text
    new = r.json()["credential"]
    assert r.json()["agent_id"] == str(agent.agent_id)
    stale = await _beat(api, old)
    assert (stale.status_code, stale.json()["code"]) == (401, "CREDENTIAL_INVALID")
    assert (await _beat(api, new)).status_code == 200
    rows = (await session.execute(select(AuditLog.action))).scalars().all()
    assert "AGENT_CREDENTIAL_ROTATED" in rows
    assert new not in str(
        [a.after_value for a in (await session.execute(select(AuditLog))).scalars()]
    )


@pytest.mark.req("SEC-2.3")
async def test_rotation_keeps_the_agent_id_and_revocation_is_permanent(
    api: httpx.AsyncClient, session: AsyncSession, company: Company, owner: User
) -> None:
    agent, credential = await make_registered_agent(session, company, tally_guid=GUID)
    rotated = await api.post(
        f"{_agents(company)}/{agent.agent_id}/rotate-credential", headers=auth_header(owner)
    )
    assert rotated.json()["agent_id"] == str(agent.agent_id)
    credential = rotated.json()["credential"]
    assert (
        await api.post(f"{_agents(company)}/{agent.agent_id}/revoke", headers=auth_header(owner))
    ).status_code == 204
    assert (await _beat(api, credential)).json()["code"] == "AGENT_REVOKED"
    again = await api.post(
        f"{_agents(company)}/{agent.agent_id}/rotate-credential", headers=auth_header(owner)
    )
    assert (again.status_code, again.json()["code"]) == (409, "AGENT_REVOKED")
    twice = await api.post(
        f"{_agents(company)}/{agent.agent_id}/revoke", headers=auth_header(owner)
    )
    assert twice.status_code == 409
    # The installation comes back only as a NEW Agent.
    company.tally_guid = GUID
    await session.flush()
    fresh = await _register(api, session, company, "Head Office (new)")
    assert fresh["agent_id"] != str(agent.agent_id)


@pytest.mark.req("AGT-4.2")
@pytest.mark.req_partial("AC-24", "AGT-5.4")  # AC-24 timeout retry, AGT-5.4 reporting: P7
async def test_tally_settings_reject_batches_over_10000_and_reach_the_agent(
    api: httpx.AsyncClient, session: AsyncSession, company: Company, owner: User
) -> None:
    agent, credential = await make_registered_agent(session, company, tally_guid=GUID)
    url = f"{_agents(company)}/{agent.agent_id}/tally-settings"
    for bad in (15_000, 10_001, 0):
        r = await api.put(url, json={"extraction_batch_size": bad}, headers=auth_header(owner))
        assert r.status_code == 422, bad
    r = await api.put(
        url,
        json={"extraction_batch_size": 10_000, "tally_company_name": "Sharma Traders Pvt Ltd"},
        headers=auth_header(owner),
    )
    assert r.status_code == 200, r.text
    config = (await _beat(api, credential)).json()["config"]
    assert (config["extraction_batch_size"], config["tally_company_name"]) == (
        10_000,
        "Sharma Traders Pvt Ltd",
    )
    audit = (
        await session.execute(
            select(AuditLog).where(AuditLog.action == "AGENT_TALLY_SETTINGS_CHANGED")
        )
    ).scalar_one()
    assert audit.before_value == {
        "extraction_batch_size": 5000,
        "tally_company_name": "Test Traders",
    }


@pytest.mark.req("FR-4.4")
@pytest.mark.req_partial("AC-25", "AGT-6.4")  # API flag; shown in the UI P13, emphasis P10
async def test_agents_view_lists_status_versions_heartbeat_uptime_and_queue(
    api: httpx.AsyncClient, session: AsyncSession, company: Company
) -> None:
    accountant = await make_user(session, company, RoleName.ACCOUNTANT)
    await make_registered_agent(
        session,
        company,
        "fresh",
        tally_uptime_seconds=3600,
        queue_status={"records": 3, "full": False},
    )
    await make_registered_agent(
        session,
        company,
        "long",
        tally_uptime_seconds=8 * 86_400,
        queue_status={"records": 50_000, "full": True},
        last_tally_status="COMPANY_MISMATCH",
    )
    last = datetime(2026, 9, 25, 12, 0, tzinfo=UTC)
    await make_registered_agent(
        session, company, "off", status=AgentStatus.OFFLINE, last_heartbeat_at=last
    )
    r = await api.get(_agents(company), headers=auth_header(accountant))
    assert r.status_code == 200
    rows = {a["agent_name"]: a for a in r.json()["agents"]}
    assert set(rows) == {"fresh", "long", "off"}
    fresh, long, off = rows["fresh"], rows["long"], rows["off"]
    for key in (
        "status",
        "agent_version",
        "tdl_version",
        "last_heartbeat_at",
        "tally_uptime_seconds",
        "queue_status",
    ):
        assert key in fresh
    assert (fresh["uptime_advisory"], long["uptime_advisory"]) == (False, True)
    assert any(w.startswith("QUEUE_FULL") for w in long["warnings"])
    assert any(w.startswith("COMPANY_MISMATCH") for w in long["warnings"])
    assert datetime.fromisoformat(off["offline_since"]) == last
    assert "credential_hash" not in fresh and "credential_salt" not in fresh


async def test_replacing_an_agent_keeps_scheduled_syncs_working(
    api: httpx.AsyncClient, session: AsyncSession, company: Company, owner: User
) -> None:
    """D-036 #6, the whole path: revoke A, register B, B's schedules fire."""
    # 1. Agent A registers; its default schedules are activated (as P5 will do).
    a = await _register(api, session, company, "Head Office")
    a_schedules = await _schedules(session, a["agent_id"])
    assert [(s.cron_expression, s.is_active) for s in a_schedules] == [
        ("0 * * * *", False),
        ("0 2 * * *", False),
    ]
    now = datetime.now(UTC)
    for s in a_schedules:
        activate(s, company.company_timezone, now)
    await session.flush()
    assert (await _beat(api, a["credential"])).json()["status"] == "ACTIVE"
    assert (await api.get(_agents(company), headers=auth_header(owner))).json()["warnings"] == []

    # 2. Revoke A: its schedules stop in the same transaction, audited.
    assert (
        await api.post(f"{_agents(company)}/{a['agent_id']}/revoke", headers=auth_header(owner))
    ).status_code == 204
    for s in a_schedules:
        await session.refresh(s)
    assert [(s.is_active, s.next_fire_at) for s in a_schedules] == [(False, None)] * 2
    deactivated = (
        (await session.execute(select(AuditLog).where(AuditLog.action == "SCHEDULE_DEACTIVATED")))
        .scalars()
        .all()
    )
    assert len(deactivated) == 2
    assert all(
        d.after_value == {"is_active": False, "reason": "agent revoked"} for d in deactivated
    )

    # 3. The replacement B registers and gets working default schedules.
    b = await _register(api, session, company, "Head Office (replacement)")
    b_schedules = await _schedules(session, b["agent_id"])
    assert [(s.cron_expression, s.sync_mode) for s in b_schedules] == [
        ("0 * * * *", "INCREMENTAL"),
        ("0 2 * * *", "RECONCILIATION"),
    ]
    assert (await _beat(api, b["credential"])).json()["status"] == "ACTIVE"
    view = (await api.get(_agents(company), headers=auth_header(owner))).json()
    assert view["warnings"] == [NO_ACTIVE_SCHEDULE]  # B is active, nothing scheduled yet

    # 4. Activated (P5 after B's first FULL sync; here via PUT, as an Owner can).
    for s in b_schedules:
        r = await api.put(
            f"/companies/{company.company_id}/sync-schedules/{s.schedule_id}",
            json={"is_active": True},
            headers=auth_header(owner),
        )
        assert r.status_code == 200, r.text
    assert (await api.get(_agents(company), headers=auth_header(owner))).json()["warnings"] == []

    # 5. At the next hour the schedule fires for B, and B is offered the command.
    for s in b_schedules:
        await session.refresh(s)
    next_hour = min(s.next_fire_at for s in b_schedules if s.next_fire_at)
    assert await fire_schedules(session, next_hour + timedelta(seconds=5)) >= 1
    offered = (await _beat(api, b["credential"])).json()["command"]
    assert offered is not None and offered["sync_mode"] == "INCREMENTAL"

    # 6. A standby beside the working, scheduled B gets no schedules of its own.
    standby = await _register(api, session, company, "Standby")
    assert await _schedules(session, standby["agent_id"]) == []
