"""Agent onboarding and the Agent protocol (SRS 4.2-4.8, D-011, D-035)."""

import uuid
from datetime import UTC, datetime, timedelta

from packaging.version import Version
from sqlalchemy import func, or_, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import audit
from app.core.agent_credentials import (
    AgentContext,
    hash_registration_token,
    new_credential,
    new_registration_token,
)
from app.core.config import get_settings
from app.core.errors import AppError
from app.core.gates import collection_sync_mode
from app.core.permissions import CompanyContext
from app.models.agents import Agent, AgentCommand, AgentRegistrationToken, SyncSchedule
from app.models.company import Company
from app.models.enums import AgentStatus, CollectionType, CommandStatus, SyncMode, TallyStatus
from app.schemas.agents import (
    AgentConfig,
    CommandOut,
    HeartbeatRequest,
    HeartbeatResponse,
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


def _compatible(agent_version: str, tdl_version: str) -> bool:
    settings = get_settings()
    return Version(agent_version) >= Version(settings.min_agent_version) and Version(
        tdl_version
    ) >= Version(settings.min_tdl_version)


async def _next_command(session: AsyncSession, agent: Agent, now: datetime) -> CommandOut | None:
    """The oldest unexpired PENDING command, unless one is already in progress (D-035 #13)."""
    busy = await session.scalar(
        select(AgentCommand.command_id).where(
            AgentCommand.agent_id == agent.agent_id,
            AgentCommand.status.in_([CommandStatus.CLAIMED, CommandStatus.RUNNING]),
        )
    )
    if busy is not None:
        return None
    timeout = await get_setting(session, agent.company_id, "agent.command_claim_timeout_minutes")
    command = await session.scalar(
        select(AgentCommand)
        .where(
            AgentCommand.agent_id == agent.agent_id,
            AgentCommand.company_id == agent.company_id,
            AgentCommand.status == CommandStatus.PENDING,
            AgentCommand.created_at > now - timedelta(minutes=timeout),
        )
        .order_by(AgentCommand.created_at, AgentCommand.command_id)
        .limit(1)
    )
    if command is None:
        return None
    return CommandOut(
        command_id=command.command_id,
        sync_mode=SyncMode(command.sync_mode),
        date_from=command.date_from,
        date_to=command.date_to,
        created_at=command.created_at,
    )


async def heartbeat(
    session: AsyncSession, ctx: AgentContext, body: HeartbeatRequest
) -> HeartbeatResponse:
    """AGT-1.1, VER-1.x, D-025. The row is locked so a heartbeat and the offline job
    serialise instead of overwriting each other."""
    now = datetime.now(UTC)
    agent = (
        await session.execute(
            select(Agent)
            .where(Agent.agent_id == ctx.agent_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
    ).scalar_one()
    agent.agent_version = body.agent_version
    agent.tdl_version = body.tdl_version
    agent.tally_version = body.tally_version
    agent.tally_uptime_seconds = body.tally_uptime_seconds
    agent.queue_status = body.queue_status.model_dump()
    agent.last_heartbeat_at = now
    if agent.last_tally_status != body.tally_status:
        agent.last_tally_status = body.tally_status
        agent.tally_status_since = now

    warnings: list[str] = []
    guid_confirmed = body.confirmed_tally_guid == agent.tally_guid
    mismatch = body.tally_status == TallyStatus.COMPANY_MISMATCH or (
        body.confirmed_tally_guid is not None and not guid_confirmed
    )
    if mismatch:  # AGT-3.4: a warning; never re-bound, status unchanged
        warnings.append(
            "COMPANY_MISMATCH: Tally reports a different company than this Agent is registered "
            "for; the Agent must be re-registered"
        )
    if not _compatible(body.agent_version, body.tdl_version):
        agent.status = AgentStatus.INCOMPATIBLE  # VER-1.2
        warnings.append(
            f"INCOMPATIBLE: Agent {body.agent_version} / TDL {body.tdl_version} is below the "
            f"minimum {get_settings().min_agent_version} / {get_settings().min_tdl_version}"
        )
    elif agent.status == AgentStatus.OFFLINE or (
        agent.status in (AgentStatus.REGISTERING, AgentStatus.INCOMPATIBLE)
        and guid_confirmed
        and not mismatch
    ):
        agent.status = AgentStatus.ACTIVE
    if body.queue_status.full:
        warnings.append("QUEUE_FULL: the Agent's local queue is full")

    command = (
        await _next_command(session, agent, now) if agent.status == AgentStatus.ACTIVE else None
    )
    config = await agent_config(session, agent)
    await session.commit()
    return HeartbeatResponse(
        status=AgentStatus(agent.status), config=config, command=command, warnings=warnings
    )
