"""P3.2-P3.3: registration tokens and Agent registration (SRS 4.2, AC-13, AC-14)."""

import asyncio
import hashlib
from datetime import UTC, datetime, timedelta

import httpx
import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.agent_credentials import parse, verify
from app.core.errors import AppError
from app.models.agents import Agent, AgentRegistrationToken, SyncSchedule
from app.models.company import Company, User
from app.models.config import AuditLog
from app.models.enums import CollectionType, RoleName
from app.schemas.agents import RegisterRequest
from app.services.agents import register_agent
from tests.factories import auth_header, make_company, make_registration_token, make_user


@pytest.fixture
async def company(session: AsyncSession) -> Company:
    return await make_company(session)


@pytest.fixture
async def owner(session: AsyncSession, company: Company) -> User:
    return await make_user(session, company, RoleName.OWNER)


async def _token(api: httpx.AsyncClient, company: Company, user: User) -> httpx.Response:
    return await api.post(
        f"/companies/{company.company_id}/agents/register-token", headers=auth_header(user)
    )


async def test_token_is_shown_once_stored_hashed_valid_24h_and_audited(
    api: httpx.AsyncClient, session: AsyncSession, company: Company, owner: User
) -> None:
    r = await _token(api, company, owner)
    assert r.status_code == 201, r.text
    token = r.json()["token"]
    expires = datetime.fromisoformat(r.json()["expires_at"])
    assert timedelta(hours=23, minutes=59) < expires - datetime.now(UTC) <= timedelta(hours=24)
    row = (await session.execute(select(AgentRegistrationToken))).scalar_one()
    assert row.token_hash == hashlib.sha256(token.encode()).hexdigest()
    assert (row.company_id, row.created_by, row.used_at) == (
        company.company_id,
        owner.user_id,
        None,
    )
    audit = (await session.execute(select(AuditLog))).scalar_one()
    assert audit.action == "REGISTRATION_TOKEN_CREATED"
    assert token not in str(audit.after_value)


async def test_admin_may_create_tokens_but_accountant_may_not(
    api: httpx.AsyncClient, session: AsyncSession, company: Company
) -> None:
    admin = await make_user(session, company, RoleName.ADMIN)
    accountant = await make_user(session, company, RoleName.ACCOUNTANT)
    assert (await _token(api, company, admin)).status_code == 201
    assert (await _token(api, company, accountant)).status_code == 403


# --- P3.3 registration -------------------------------------------------------------------

GUID_1, GUID_2 = "guid-tally-company-1", "guid-tally-company-2"


def _body(token: str, **kw: object) -> dict[str, object]:
    return {
        "token": token,
        "agent_name": "Head Office",
        "tally_guid": GUID_1,
        "tally_company_name": "Sharma Traders",
        "agent_version": "1.0.0",
        "tdl_version": "1.0.0",
    } | kw


@pytest.mark.req("AC-13", "AGT-3.1")
async def test_registration_issues_a_credential_bound_to_one_company(
    api: httpx.AsyncClient, session: AsyncSession, company: Company
) -> None:
    token = await make_registration_token(session, company)
    r = await api.post("/agent/register", json=_body(token))
    assert r.status_code == 201, r.text
    body = r.json()
    parsed = parse(body["credential"])
    assert parsed is not None and str(parsed[0]) == body["agent_id"]
    agent = await session.get(Agent, parsed[0])
    assert agent is not None
    assert (agent.company_id, agent.tally_guid, agent.status) == (
        company.company_id,
        GUID_1,
        "REGISTERING",
    )
    assert agent.credential_salt is not None and agent.credential_hash is not None
    assert verify(parsed[1], agent.credential_salt, agent.credential_hash)
    await session.refresh(company)
    assert (company.tally_guid, company.is_active) == (GUID_1, True)  # SRS 4.2 step 8
    config = body["config"]
    assert config["poll_interval_seconds"] == 30
    assert config["progress_interval_seconds"] == 60
    assert config["command_lease_seconds"] == 300
    assert config["extraction_batch_size"] == 5000
    assert (config["tally_host"], config["tally_port"]) == ("localhost", 9000)
    assert set(config["collection_sync_modes"]) == {c.value for c in CollectionType}
    schedules = (await session.execute(select(SyncSchedule))).scalars().all()
    assert sorted((s.cron_expression, s.sync_mode, s.is_active) for s in schedules) == [
        ("0 * * * *", "INCREMENTAL", False),
        ("0 2 * * *", "RECONCILIATION", False),
    ]
    actions = (await session.execute(select(AuditLog.action))).scalars().all()
    assert "AGENT_REGISTERED" in actions


async def test_a_second_agent_with_the_same_guid_joins_without_new_schedules(
    api: httpx.AsyncClient, session: AsyncSession, company: Company
) -> None:
    first = await make_registration_token(session, company)
    second = await make_registration_token(session, company)
    assert (await api.post("/agent/register", json=_body(first))).status_code == 201
    r = await api.post("/agent/register", json=_body(second, agent_name="Standby"))
    assert r.status_code == 201, r.text
    assert len((await session.execute(select(SyncSchedule))).scalars().all()) == 2


@pytest.mark.req("AC-14")
async def test_a_different_guid_is_rejected_and_the_token_stays_usable(
    api: httpx.AsyncClient, session: AsyncSession
) -> None:
    company = await make_company(session, tally_guid=GUID_1)
    token = await make_registration_token(session, company)
    r = await api.post("/agent/register", json=_body(token, tally_guid=GUID_2))
    assert r.status_code == 409
    assert r.json()["code"] == "COMPANY_MISMATCH"
    assert (await session.execute(select(Agent))).scalars().all() == []
    row = (await session.execute(select(AgentRegistrationToken))).scalar_one()
    assert row.used_at is None
    rejected = (
        await session.execute(
            select(AuditLog).where(AuditLog.action == "AGENT_REGISTRATION_REJECTED")
        )
    ).scalar_one()
    assert (rejected.company_id, rejected.result) == (company.company_id, "FAILURE")
    # The same token still works for the right Tally company.
    assert (await api.post("/agent/register", json=_body(token))).status_code == 201


async def test_a_guid_bound_to_another_company_is_rejected(
    api: httpx.AsyncClient, session: AsyncSession, company: Company
) -> None:
    await make_company(session, name="Other", tally_guid=GUID_1)
    token = await make_registration_token(session, company)
    r = await api.post("/agent/register", json=_body(token))
    assert (r.status_code, r.json()["code"]) == (409, "COMPANY_MISMATCH")
    await session.refresh(company)
    assert (company.tally_guid, company.is_active) == (None, True)


async def test_duplicate_agent_name_is_a_conflict(
    api: httpx.AsyncClient, session: AsyncSession, company: Company
) -> None:
    first = await make_registration_token(session, company)
    second = await make_registration_token(session, company)
    assert (await api.post("/agent/register", json=_body(first))).status_code == 201
    r = await api.post("/agent/register", json=_body(second))
    assert (r.status_code, r.json()["code"]) == (409, "CONFLICT")


@pytest.mark.parametrize("case", ["used", "expired", "unknown"])
async def test_used_expired_or_unknown_tokens_are_401(
    api: httpx.AsyncClient, session: AsyncSession, company: Company, case: str
) -> None:
    expires = datetime.now(UTC) - timedelta(seconds=1) if case == "expired" else None
    token = await make_registration_token(session, company, expires_at=expires)
    if case == "used":
        assert (await api.post("/agent/register", json=_body(token))).status_code == 201
    if case == "unknown":
        token = "reg_" + "x" * 43
    r = await api.post("/agent/register", json=_body(token, agent_name="Another"))
    assert (r.status_code, r.json()["code"]) == (401, "CREDENTIAL_INVALID")


# --- committed races: real connections, real commits -------------------------------------


async def _register(committed: async_sessionmaker[AsyncSession], body: dict[str, object]) -> str:
    async with committed() as s:
        try:
            await register_agent(s, RegisterRequest.model_validate(body))
        except AppError as exc:
            return exc.code.value
        return "OK"


async def test_one_token_used_concurrently_registers_exactly_one_agent(
    committed: async_sessionmaker[AsyncSession],
) -> None:
    async with committed() as s:
        company = await make_company(s)
        token = await make_registration_token(s, company)
        await s.commit()
    results = await asyncio.gather(
        *(_register(committed, _body(token, agent_name=f"agent-{i}")) for i in range(8))
    )
    assert sorted(results) == ["CREDENTIAL_INVALID"] * 7 + ["OK"]
    async with committed() as s:
        assert await s.scalar(select(func.count()).select_from(Agent)) == 1


async def test_two_first_agents_with_different_guids_bind_exactly_one(
    committed: async_sessionmaker[AsyncSession],
) -> None:
    async with committed() as s:
        company = await make_company(s)
        tokens = [await make_registration_token(s, company) for _ in range(2)]
        await s.commit()
    results = await asyncio.gather(
        _register(committed, _body(tokens[0], agent_name="a", tally_guid=GUID_1)),
        _register(committed, _body(tokens[1], agent_name="b", tally_guid=GUID_2)),
    )
    assert sorted(results) == ["COMPANY_MISMATCH", "OK"]
    async with committed() as s:
        bound = await s.scalar(
            select(Company.tally_guid).where(Company.company_id == company.company_id)
        )
        agent_guids = (await s.execute(select(Agent.tally_guid))).scalars().all()
    assert agent_guids == [bound]
