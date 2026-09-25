"""P3.10: schedule API (RTE-1.3, TZ-1.1)."""

from datetime import UTC, datetime
from typing import Any

import httpx
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.agents import Agent
from app.models.company import Company, User
from app.models.config import AuditLog
from app.models.enums import AgentStatus, RoleName
from tests.factories import auth_header, make_company, make_registered_agent, make_user


@pytest.fixture
async def company(session: AsyncSession) -> Company:
    return await make_company(session, tz="Asia/Kolkata")


@pytest.fixture
async def admin(session: AsyncSession, company: Company) -> User:
    return await make_user(session, company, RoleName.ADMIN)


@pytest.fixture
async def agent(session: AsyncSession, company: Company) -> Agent:
    return (await make_registered_agent(session, company))[0]


def _url(company: Company) -> str:
    return f"/companies/{company.company_id}/sync-schedules"


async def _create(
    api: httpx.AsyncClient, company: Company, user: User, agent: Agent, **body: Any
) -> httpx.Response:
    return await api.post(
        _url(company),
        json={
            "agent_id": str(agent.agent_id),
            "cron_expression": "0 2 * * *",
            "sync_mode": "RECONCILIATION",
        }
        | body,
        headers=auth_header(user),
    )


@pytest.mark.req("RTE-1.3")
async def test_a_schedule_is_bound_to_its_agent_for_good(
    api: httpx.AsyncClient, session: AsyncSession, company: Company, admin: User, agent: Agent
) -> None:
    r = await _create(api, company, admin, agent)
    assert r.status_code == 201, r.text
    assert r.json()["agent_id"] == str(agent.agent_id)
    other, _ = await make_registered_agent(session, company, "other")
    url = f"{_url(company)}/{r.json()['schedule_id']}"
    moved = await api.put(url, json={"agent_id": str(other.agent_id)}, headers=auth_header(admin))
    assert moved.status_code == 422
    missing = await api.post(
        _url(company),
        json={"cron_expression": "0 * * * *", "sync_mode": "FULL"},
        headers=auth_header(admin),
    )
    assert missing.status_code == 422  # agent_id is required at creation
    listed = await api.get(_url(company), headers=auth_header(admin))
    assert [s["agent_id"] for s in listed.json()] == [str(agent.agent_id)]


@pytest.mark.req_partial("TZ-1.1")  # date-based schedules; other clauses in their phases
async def test_next_fire_is_computed_in_the_company_time_zone(
    api: httpx.AsyncClient, company: Company, admin: User, agent: Agent
) -> None:
    r = await _create(api, company, admin, agent)
    fire = datetime.fromisoformat(r.json()["next_fire_at"])
    assert (fire.astimezone(UTC).hour, fire.astimezone(UTC).minute) == (20, 30)  # 02:00 IST
    assert fire > datetime.now(UTC)


@pytest.mark.parametrize(
    ("body", "status"),
    [
        ({"cron_expression": "61 * * * *"}, 422),
        ({"cron_expression": "* * *"}, 422),
        ({"sync_mode": "DATE_RANGE"}, 422),
    ],
)
async def test_invalid_schedules_are_rejected(
    api: httpx.AsyncClient,
    company: Company,
    admin: User,
    agent: Agent,
    body: dict[str, Any],
    status: int,
) -> None:
    assert (await _create(api, company, admin, agent, **body)).status_code == status


async def test_schedules_cannot_use_other_companies_or_unusable_agents(
    api: httpx.AsyncClient, session: AsyncSession, company: Company, admin: User
) -> None:
    other = await make_company(session, name="Other")
    theirs, _ = await make_registered_agent(session, other, "theirs")
    revoked, _ = await make_registered_agent(session, company, "gone", status=AgentStatus.REVOKED)
    assert (await _create(api, company, admin, theirs)).status_code == 403
    r = await _create(api, company, admin, revoked)
    assert (r.status_code, r.json()["code"]) == (409, "AGENT_REVOKED")


async def test_update_recomputes_or_clears_next_fire_and_is_audited(
    api: httpx.AsyncClient, session: AsyncSession, company: Company, admin: User, agent: Agent
) -> None:
    created = await _create(api, company, admin, agent)
    url = f"{_url(company)}/{created.json()['schedule_id']}"
    off = await api.put(url, json={"is_active": False}, headers=auth_header(admin))
    assert (off.json()["is_active"], off.json()["next_fire_at"]) == (False, None)
    on = await api.put(
        url, json={"is_active": True, "cron_expression": "30 * * * *"}, headers=auth_header(admin)
    )
    assert on.json()["is_active"] is True
    assert datetime.fromisoformat(on.json()["next_fire_at"]).minute in (0, 30)  # :30 IST
    actions = (await session.execute(select(AuditLog.action).order_by(AuditLog.id))).scalars().all()
    assert actions == ["SCHEDULE_CREATED", "SCHEDULE_UPDATED", "SCHEDULE_UPDATED"]


async def test_accountants_cannot_manage_schedules(
    api: httpx.AsyncClient, session: AsyncSession, company: Company, agent: Agent
) -> None:
    accountant = await make_user(session, company, RoleName.ACCOUNTANT)
    assert (await _create(api, company, accountant, agent)).status_code == 403
