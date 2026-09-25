"""Agent onboarding and the Agent protocol (SRS 4.2-4.8, D-011, D-035)."""

from datetime import UTC, datetime, timedelta

from sqlalchemy.ext.asyncio import AsyncSession

from app.core import audit
from app.core.agent_credentials import new_registration_token
from app.core.permissions import CompanyContext
from app.models.agents import AgentRegistrationToken
from app.schemas.agents import RegistrationTokenOut

REGISTRATION_TOKEN_TTL = timedelta(hours=24)


async def create_registration_token(
    session: AsyncSession, ctx: CompanyContext
) -> RegistrationTokenOut:
    token, token_hash = new_registration_token()
    expires_at = datetime.now(UTC) + REGISTRATION_TOKEN_TTL
    row = AgentRegistrationToken(
        company_id=ctx.company_id,
        token_hash=token_hash,
        expires_at=expires_at,
        created_by=ctx.user_id,
    )
    session.add(row)
    await session.flush()
    await audit.record(
        session,
        company_id=ctx.company_id,
        user_id=ctx.user_id,
        action="REGISTRATION_TOKEN_CREATED",
        entity_type="agent_registration_token",
        entity_id=str(row.token_id),
        after={"expires_at": expires_at.isoformat()},
    )
    await session.commit()
    return RegistrationTokenOut(token=token, expires_at=expires_at)
