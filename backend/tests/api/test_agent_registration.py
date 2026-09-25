"""P3.2-P3.3: registration tokens and Agent registration (SRS 4.2, AC-13, AC-14)."""

import hashlib
from datetime import UTC, datetime, timedelta

import httpx
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.agents import AgentRegistrationToken
from app.models.company import Company, User
from app.models.config import AuditLog
from app.models.enums import RoleName
from tests.factories import auth_header, make_company, make_user


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
