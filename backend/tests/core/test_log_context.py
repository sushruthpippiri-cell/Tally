"""P16.3: structured logs carry the request id, company id and Agent id (SRS 15).

Binding happens once, where each value is resolved - `Require.__call__` for the company and
user, `current_agent` for the Agent, `run_exclusive` for a job - and structlog's contextvars
processor puts them on every record of that request. Call sites do not pass them by hand, so a
new log line gets them for free; the middleware unbinds them so they cannot leak into the next
request handled by the same task.
"""

import uuid
from typing import Any

import pytest
from fastapi.security import HTTPAuthorizationCredentials
from sqlalchemy.ext.asyncio import AsyncSession
from structlog.contextvars import clear_contextvars, get_contextvars

from app.core.agent_credentials import current_agent
from app.core.permissions import Permission
from app.jobs.runner import LOCK_MARK_OFFLINE, run_exclusive
from app.main import create_app
from tally_contract.testing import assert_logged
from tests.conftest import client_for
from tests.factories import auth_header, grant, make_company, make_registered_agent


@pytest.mark.req("LOG-1.2")
async def test_a_refused_request_logs_the_request_company_and_user(
    session: AsyncSession, caplog: pytest.LogCaptureFixture
) -> None:
    company = await make_company(session)
    user = await make_user_without_permission(session, company)
    async with client_for(create_app(), session) as client:
        response = await client.get(
            f"/companies/{company.company_id}/sync/errors",  # needs VIEW_LOGS
            headers=auth_header(user) | {"X-Request-ID": "req-abc-123"},
        )
    assert response.status_code == 403
    assert_logged(
        caplog,
        "permission_denied",
        request_id="req-abc-123",
        company_id=str(company.company_id),
        user_id=str(user.user_id),
    )


@pytest.mark.req("LOG-1.2")
async def test_an_agent_credential_binds_the_agent_and_its_company(
    session: AsyncSession,
) -> None:
    """Asserted where the binding happens rather than through a route: the Agent endpoints log
    nothing of their own today, and this is the behaviour that must hold for the ones that do."""
    company = await make_company(session)
    agent, credential = await make_registered_agent(session, company)

    context = await current_agent(
        HTTPAuthorizationCredentials(scheme="Bearer", credentials=credential), session
    )

    assert context.agent_id == agent.agent_id
    bound = get_contextvars()
    assert bound["agent_id"] == str(agent.agent_id)
    assert bound["company_id"] == str(company.company_id)
    clear_contextvars()


async def test_the_ids_do_not_leak_into_the_next_request(session: AsyncSession) -> None:
    """The middleware unbinds them, so a later request on the same task cannot inherit another
    company's id - which would put the wrong tenant on a log line."""
    company = await make_company(session)
    user = await make_user_without_permission(session, company)
    async with client_for(create_app(), session) as client:
        await client.get(f"/companies/{company.company_id}/sync/errors", headers=auth_header(user))
    assert "company_id" not in get_contextvars()
    assert "user_id" not in get_contextvars()
    assert "agent_id" not in get_contextvars()


@pytest.mark.req("LOG-1.2")
async def test_a_job_logs_its_name_instead_of_a_request_id(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """A background job has no request, so `job` is what ties its records together."""
    from app.jobs.agents import mark_offline

    await run_exclusive(LOCK_MARK_OFFLINE, mark_offline)
    fields = assert_logged(caplog, "job_ran", level="info", job="mark_offline")
    assert "request_id" not in fields


async def make_user_without_permission(session: AsyncSession, company: Any) -> Any:
    """An Accountant: SRS 14.1 gives them no VIEW_LOGS, so /sync/errors is a 403."""
    from app.models.enums import RoleName
    from tests.factories import make_user

    user = await make_user(session, email=f"acct-{uuid.uuid4().hex[:8]}@example.com")
    await grant(session, user, company, RoleName.ACCOUNTANT)
    assert Permission.VIEW_LOGS  # the permission the route needs
    return user
