"""P3.7: Sync Now, routing and command status (AGT-1.5, RTE-1.x, D-036 #5)."""

import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.agents import AgentCommand
from app.models.company import Company, User
from app.models.config import AuditLog
from app.models.enums import AgentStatus, RoleName
from tests.factories import auth_header, make_company, make_registered_agent, make_user

APP = Path(__file__).parents[2] / "app"


@pytest.fixture
async def company(session: AsyncSession) -> Company:
    return await make_company(session, tz="Asia/Kolkata")


@pytest.fixture
async def owner(session: AsyncSession, company: Company) -> User:
    return await make_user(session, company, RoleName.OWNER)


async def _sync(
    api: httpx.AsyncClient, company: Company, user: User, **body: Any
) -> httpx.Response:
    return await api.post(
        f"/companies/{company.company_id}/sync",
        json={"sync_mode": "FULL"} | body,
        headers=auth_header(user),
    )


@pytest.mark.req("AGT-1.5")
async def test_sync_now_only_creates_a_pending_command(
    api: httpx.AsyncClient, session: AsyncSession, company: Company, owner: User
) -> None:
    agent, _ = await make_registered_agent(session, company)
    r = await _sync(api, company, owner)
    assert r.status_code == 201, r.text
    body = r.json()
    assert (body["status"], body["agent_id"], body["created_by"]) == (
        "PENDING",
        str(agent.agent_id),
        str(owner.user_id),
    )
    assert body["waiting_label"] is None
    row = (
        await session.execute(select(AuditLog).where(AuditLog.action == "SYNC_REQUESTED"))
    ).scalar_one()
    assert row.entity_id == body["command_id"]
    # "It never attempts to connect to the Agent": the backend has no HTTP client at all.
    clients = re.compile(
        r"^\s*(import|from)\s+(httpx|requests|aiohttp|urllib3|urllib\.request)\b", re.M
    )
    offenders = [p for p in APP.rglob("*.py") if clients.search(p.read_text(encoding="utf-8"))]
    assert offenders == []


@pytest.mark.req("RTE-1.1")
async def test_the_one_active_agent_is_targeted_automatically(
    api: httpx.AsyncClient, session: AsyncSession, company: Company, owner: User
) -> None:
    await make_registered_agent(session, company, "revoked", status=AgentStatus.REVOKED)
    await make_registered_agent(session, company, "old", status=AgentStatus.INCOMPATIBLE)
    active, _ = await make_registered_agent(session, company, "active")
    r = await _sync(api, company, owner)
    assert r.json()["agent_id"] == str(active.agent_id)


@pytest.mark.req("AC-18", "RTE-1.2")
async def test_two_active_agents_need_an_agent_id_and_only_that_one_gets_it(
    api: httpx.AsyncClient, session: AsyncSession, company: Company, owner: User
) -> None:
    a, a_cred = await make_registered_agent(session, company, "a")
    b, b_cred = await make_registered_agent(session, company, "b")
    r = await _sync(api, company, owner)
    assert (r.status_code, r.json()["code"]) == (422, "AGENT_SELECTION_REQUIRED")
    r = await _sync(api, company, owner, agent_id=str(b.agent_id))
    assert r.json()["agent_id"] == str(b.agent_id)
    beat = {
        "agent_version": "1.0.0",
        "tdl_version": "1.0.0",
        "tally_status": "OK",
        "confirmed_tally_guid": a.tally_guid,
        "queue_status": {"records": 0, "dead_letter_count": 0, "full": False},
    }
    offered_a = await api.post(
        "/agent/heartbeat", json=beat, headers={"Authorization": f"Bearer {a_cred}"}
    )
    offered_b = await api.post(
        "/agent/heartbeat", json=beat, headers={"Authorization": f"Bearer {b_cred}"}
    )
    assert offered_a.json()["command"] is None
    assert offered_b.json()["command"]["command_id"] == r.json()["command_id"]
    # The per-Agent path does the same.
    r = await api.post(
        f"/companies/{company.company_id}/agents/{a.agent_id}/sync",
        json={"sync_mode": "INCREMENTAL"},
        headers=auth_header(owner),
    )
    assert (r.status_code, r.json()["agent_id"]) == (201, str(a.agent_id))


@pytest.mark.parametrize(
    ("status", "label"),
    [
        (AgentStatus.OFFLINE, "Waiting — Agent offline since 25 Sep 2026, 17:30"),
        (AgentStatus.REGISTERING, "Waiting — Agent has not connected yet"),
    ],
)
async def test_a_single_eligible_agent_is_targeted_even_when_not_active(
    api: httpx.AsyncClient,
    session: AsyncSession,
    company: Company,
    owner: User,
    status: AgentStatus,
    label: str,
) -> None:
    """D-036 #5: a one-Agent company never has to choose from a list of one."""
    await make_registered_agent(session, company, "gone", status=AgentStatus.REVOKED)
    agent, _ = await make_registered_agent(
        session,
        company,
        "only",
        status=status,
        last_heartbeat_at=datetime(2026, 9, 25, 12, 0, tzinfo=UTC),  # 17:30 IST
    )
    r = await _sync(api, company, owner)
    assert r.status_code == 201, r.text
    assert (r.json()["agent_id"], r.json()["status"]) == (str(agent.agent_id), "PENDING")
    assert r.json()["waiting_label"] == label


async def test_several_eligible_agents_none_active_need_a_choice(
    api: httpx.AsyncClient, session: AsyncSession, company: Company, owner: User
) -> None:
    await make_registered_agent(session, company, "a", status=AgentStatus.OFFLINE)
    await make_registered_agent(session, company, "b", status=AgentStatus.REGISTERING)
    r = await _sync(api, company, owner)
    assert (r.status_code, r.json()["code"]) == (422, "AGENT_SELECTION_REQUIRED")


async def test_no_eligible_agent_is_422(
    api: httpx.AsyncClient, session: AsyncSession, company: Company, owner: User
) -> None:
    await make_registered_agent(session, company, "gone", status=AgentStatus.REVOKED)
    r = await _sync(api, company, owner)
    assert (r.status_code, r.json()["message"]) == (422, "No Agent can take commands; register one")


@pytest.mark.req("RTE-1.5")
async def test_an_agent_of_another_company_is_refused(
    api: httpx.AsyncClient, session: AsyncSession, company: Company, owner: User
) -> None:
    other = await make_company(session, name="Other")
    theirs, _ = await make_registered_agent(session, other, "theirs")
    for r in (
        await _sync(api, company, owner, agent_id=str(theirs.agent_id)),
        await api.post(
            f"/companies/{company.company_id}/agents/{theirs.agent_id}/sync",
            json={"sync_mode": "FULL"},
            headers=auth_header(owner),
        ),
    ):
        assert (r.status_code, r.json()["code"]) == (403, "FORBIDDEN")
    assert (await session.execute(select(AgentCommand))).scalars().all() == []


@pytest.mark.parametrize(
    ("status", "code"),
    [(AgentStatus.REVOKED, "AGENT_REVOKED"), (AgentStatus.INCOMPATIBLE, "AGENT_INCOMPATIBLE")],
)
async def test_revoked_or_incompatible_agents_cannot_be_given_commands(
    api: httpx.AsyncClient,
    session: AsyncSession,
    company: Company,
    owner: User,
    status: AgentStatus,
    code: str,
) -> None:
    agent, _ = await make_registered_agent(session, company, status=status)
    r = await _sync(api, company, owner, agent_id=str(agent.agent_id))
    assert (r.status_code, r.json()["code"]) == (409, code)


@pytest.mark.parametrize(
    "body",
    [
        {"sync_mode": "DATE_RANGE"},
        {"sync_mode": "DATE_RANGE", "date_from": "2024-05-01", "date_to": "2024-04-01"},
        {"sync_mode": "FULL", "date_from": "2024-04-01"},
        {"sync_mode": "EVERYTHING"},
    ],
)
async def test_invalid_sync_requests_are_422(
    api: httpx.AsyncClient,
    session: AsyncSession,
    company: Company,
    owner: User,
    body: dict[str, Any],
) -> None:
    await make_registered_agent(session, company)
    r = await api.post(
        f"/companies/{company.company_id}/sync", json=body, headers=auth_header(owner)
    )
    assert r.status_code == 422


async def test_date_range_is_stored_and_audited_with_its_range(
    api: httpx.AsyncClient, session: AsyncSession, company: Company, owner: User
) -> None:
    await make_registered_agent(session, company)
    r = await _sync(
        api, company, owner, sync_mode="DATE_RANGE", date_from="2024-04-01", date_to="2024-06-30"
    )
    assert (r.json()["date_from"], r.json()["date_to"]) == ("2024-04-01", "2024-06-30")
    row = (
        await session.execute(select(AuditLog).where(AuditLog.action == "SYNC_REQUESTED"))
    ).scalar_one()
    assert row.data_range == {"from": "2024-04-01", "to": "2024-06-30"}


async def test_accountants_may_sync_and_see_status_but_not_other_companies_commands(
    api: httpx.AsyncClient, session: AsyncSession, company: Company, owner: User
) -> None:
    accountant = await make_user(session, company, RoleName.ACCOUNTANT)
    await make_registered_agent(session, company)
    r = await _sync(api, company, accountant)
    assert r.status_code == 201
    url = f"/companies/{company.company_id}/commands/{r.json()['command_id']}"
    assert (await api.get(url, headers=auth_header(accountant))).json()["status"] == "PENDING"
    other = await make_company(session, name="Other")
    stranger = await make_user(session, other, RoleName.OWNER)
    wrong = f"/companies/{other.company_id}/commands/{r.json()['command_id']}"
    assert (await api.get(wrong, headers=auth_header(stranger))).status_code == 404
