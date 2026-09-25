"""P3.4: the AgentContext dependency (SEC-2.2)."""

from collections.abc import AsyncIterator

import httpx
import pytest
from fastapi import Depends, FastAPI
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.agent_credentials import AgentContext, current_agent
from app.core.errors import install_error_handlers
from app.models.enums import AgentStatus
from tally_contract.testing import assert_logged
from tests.conftest import client_for
from tests.factories import (
    agent_header,
    auth_header,
    make_company,
    make_registered_agent,
    make_user,
)


@pytest.fixture
async def probe(session: AsyncSession) -> AsyncIterator[httpx.AsyncClient]:
    app = FastAPI()
    install_error_handlers(app)

    @app.get("/probe")
    async def _probe(agent: AgentContext = Depends(current_agent)) -> dict[str, str]:
        return {"agent_id": str(agent.agent_id), "company_id": str(agent.company_id)}

    async with client_for(app, session) as client:
        yield client


async def test_a_valid_credential_identifies_agent_and_company(
    probe: httpx.AsyncClient, session: AsyncSession
) -> None:
    company = await make_company(session)
    agent, credential = await make_registered_agent(session, company)
    r = await probe.get("/probe", headers=agent_header(credential))
    assert r.status_code == 200
    assert r.json() == {"agent_id": str(agent.agent_id), "company_id": str(company.company_id)}


@pytest.mark.req("SEC-2.2")
async def test_invalid_and_revoked_credentials_get_distinguishable_errors(
    probe: httpx.AsyncClient, session: AsyncSession, caplog: pytest.LogCaptureFixture
) -> None:
    company = await make_company(session)
    agent, credential = await make_registered_agent(session, company)
    revoked, revoked_credential = await make_registered_agent(
        session, company, name="old", status=AgentStatus.REVOKED
    )
    invalid = [
        {},
        agent_header(credential + "x"),  # wrong secret
        agent_header("agt_" + credential[4:].replace(str(agent.agent_id)[:8], "00000000")),
        agent_header("not-a-credential"),
        auth_header(await make_user(session, company)),  # a user JWT
        agent_header(revoked_credential + "x"),  # revoked, but wrong secret: no hint
    ]
    for headers in invalid:
        r = await probe.get("/probe", headers=headers)
        assert (r.status_code, r.json()["code"]) == (401, "CREDENTIAL_INVALID"), headers
    r = await probe.get("/probe", headers=agent_header(revoked_credential))
    assert (r.status_code, r.json()["code"]) == (401, "AGENT_REVOKED")
    assert_logged(caplog, "agent_revoked_rejected", agent_id=str(revoked.agent_id))
