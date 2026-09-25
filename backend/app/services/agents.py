"""Agent onboarding and the Agent protocol (SRS 4.2-4.8, D-011, D-035)."""

import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, or_, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import audit
from app.core.agent_credentials import (
    hash_registration_token,
    new_credential,
    new_registration_token,
)
from app.core.config import get_settings
from app.core.errors import AppError
from app.core.gates import collection_sync_mode
from app.core.permissions import CompanyContext
from app.models.agents import Agent, AgentRegistrationToken, SyncSchedule
from app.models.company import Company
from app.models.enums import AgentStatus, CollectionType, SyncMode
from app.schemas.agents import (
    AgentConfig,
    RegisterRequest,
    RegisterResponse,
    RegistrationTokenOut,
)
from app.services.settings import get_setting
from tally_contract.errors import ErrorCode
from tally_contract.log import get_logger

log = get_logger(__name__)

REGISTRATION_TOKEN_TTL = timedelta(hours=24)
PROGRESS_INTERVAL_SECONDS = 60  # D-035 #11: the Agent sends progress on its own timer
DEFAULT_EXTRACTION_BATCH_SIZE = 5000  # AGT-4.1
# D-023 / D-035 #7: created inactive with a company's first Agent; P5 activates them.
DEFAULT_SCHEDULES = (("0 * * * *", SyncMode.INCREMENTAL), ("0 2 * * *", SyncMode.RECONCILIATION))


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


async def agent_config(session: AsyncSession, agent: Agent) -> AgentConfig:
    assert agent.tally_host and agent.tally_port and agent.tally_company_name
    return AgentConfig(
        poll_interval_seconds=await get_setting(
            session, agent.company_id, "agent.poll_interval_seconds"
        ),
        progress_interval_seconds=PROGRESS_INTERVAL_SECONDS,
        command_lease_seconds=await get_setting(
            session, agent.company_id, "agent.command_lease_seconds"
        ),
        extraction_batch_size=agent.extraction_batch_size or DEFAULT_EXTRACTION_BATCH_SIZE,
        tally_host=agent.tally_host,
        tally_port=agent.tally_port,
        tally_company_name=agent.tally_company_name,
        expected_tdl_version=get_settings().min_tdl_version,
        collection_sync_modes={c.value: collection_sync_mode(c.value) for c in CollectionType},
    )


class _Rejected(Exception):
    def __init__(self, error: AppError, company_id: uuid.UUID) -> None:
        self.error, self.company_id = error, company_id


def _mismatch() -> AppError:
    return AppError(
        ErrorCode.COMPANY_MISMATCH,
        "This Tally company does not match the company the token was issued for",
        409,
    )


async def register_agent(session: AsyncSession, body: RegisterRequest) -> RegisterResponse:
    """SRS 4.2 steps 6-8 in one transaction; every contended step is a compare-and-set.
    A rejection rolls everything back, so the token stays usable (AC-14)."""
    now = datetime.now(UTC)
    try:
        async with session.begin_nested():
            agent, credential = await _register(session, body, now)
    except _Rejected as rejected:
        await audit.record(
            session,
            company_id=rejected.company_id,
            user_id=None,
            action="AGENT_REGISTRATION_REJECTED",
            entity_type="agent",
            after={
                "agent_name": body.agent_name,
                "tally_guid": body.tally_guid,
                "code": rejected.error.code.value,
            },
            result="FAILURE",
        )
        await session.commit()
        log.warning(
            "agent_registration_rejected",
            company_id=str(rejected.company_id),
            code=rejected.error.code.value,
        )
        raise rejected.error from None
    config = await agent_config(session, agent)
    await session.commit()
    return RegisterResponse(agent_id=agent.agent_id, credential=credential, config=config)


async def _register(
    session: AsyncSession, body: RegisterRequest, now: datetime
) -> tuple[Agent, str]:
    token_hash = hash_registration_token(body.token)
    company_id = (
        await session.execute(
            update(AgentRegistrationToken)
            .where(
                AgentRegistrationToken.token_hash == token_hash,
                AgentRegistrationToken.used_at.is_(None),
                AgentRegistrationToken.expires_at > now,
            )
            .values(used_at=now)
            .returning(AgentRegistrationToken.company_id)
        )
    ).scalar_one_or_none()
    if company_id is None:
        raise AppError(
            ErrorCode.CREDENTIAL_INVALID, "Registration token invalid, used or expired", 401
        )
    # The first Agent's GUID becomes the company's; every later one must match (SRS 4.2).
    try:
        async with session.begin_nested():
            bound = (
                await session.execute(
                    update(Company)
                    .where(
                        Company.company_id == company_id,
                        or_(Company.tally_guid.is_(None), Company.tally_guid == body.tally_guid),
                    )
                    .values(tally_guid=body.tally_guid, is_active=True)
                    .returning(Company.company_id)
                )
            ).scalar_one_or_none()
    except IntegrityError:  # the GUID already belongs to another company (D-035 #5)
        bound = None
    if bound is None:
        raise _Rejected(_mismatch(), company_id)

    existing = await session.scalar(
        select(func.count()).select_from(Agent).where(Agent.company_id == company_id)
    )
    agent_id = uuid.uuid4()
    credential, salt, credential_hash = new_credential(agent_id)
    agent = Agent(
        agent_id=agent_id,
        company_id=company_id,
        agent_name=body.agent_name,
        credential_hash=credential_hash,
        credential_salt=salt,
        status=AgentStatus.REGISTERING,
        tally_guid=body.tally_guid,
        tally_company_name=body.tally_company_name,
        tally_host=body.tally_host,
        tally_port=body.tally_port,
        extraction_batch_size=DEFAULT_EXTRACTION_BATCH_SIZE,
        agent_version=body.agent_version,
        tdl_version=body.tdl_version,
        tally_version=body.tally_version,
        registered_at=now,
    )
    try:
        async with session.begin_nested():
            session.add(agent)
            await session.flush()
    except IntegrityError:
        raise _Rejected(
            AppError(ErrorCode.CONFLICT, "An Agent with this name already exists", 409),
            company_id,
        ) from None
    if existing == 0:
        for cron, mode in DEFAULT_SCHEDULES:
            session.add(
                SyncSchedule(
                    company_id=company_id,
                    agent_id=agent_id,
                    cron_expression=cron,
                    sync_mode=mode,
                    is_active=False,
                )
            )
    await audit.record(
        session,
        company_id=company_id,
        user_id=None,
        action="AGENT_REGISTERED",
        entity_type="agent",
        entity_id=str(agent_id),
        after={
            "agent_name": body.agent_name,
            "tally_guid": body.tally_guid,
            "tally_company_name": body.tally_company_name,
        },
    )
    return agent, credential
