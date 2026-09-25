"""Sync commands: creation and routing (AGT-1.5, RTE-1.x, D-036), and the Agent-side state
machine (AGT-1.2/1.3/1.7-1.9, D-035). Every transition is one conditional UPDATE; the
conditions are the whole rule, so a late or duplicate call can never change a finished command.

    PENDING --claim--> CLAIMED --progress--> RUNNING --result--> COMPLETED | FAILED
    CLAIMED --result FAILED--> FAILED
    PENDING --timeout job--> EXPIRED;  CLAIMED/RUNNING --lease job--> FAILED_AGENT_LOST
"""

import uuid
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import ColumnElement, and_, case, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import audit
from app.core.agent_credentials import AgentContext
from app.core.errors import AppError
from app.core.permissions import CompanyContext, scoped
from app.models.agents import Agent, AgentCommand
from app.models.company import Company
from app.models.enums import AgentStatus, CommandStatus, CommandType
from app.schemas.commands import AgentCommandOut, CommandStatusOut, ResultRequest, SyncRequest
from app.services.settings import get_setting
from tally_contract.errors import ErrorCode

CANNOT_RECEIVE = (AgentStatus.REVOKED, AgentStatus.INCOMPATIBLE)  # D-012


def waiting_label(command: AgentCommand, agent: Agent, tz: str) -> str | None:
    """RTE-1.6: why a PENDING command is waiting, in the company's time zone."""
    if command.status != CommandStatus.PENDING:
        return None
    if agent.status == AgentStatus.REGISTERING:
        return "Waiting — Agent has not connected yet"
    if agent.status == AgentStatus.OFFLINE:
        if agent.last_heartbeat_at is None:
            return "Waiting — Agent offline"
        since = agent.last_heartbeat_at.astimezone(ZoneInfo(tz))
        return f"Waiting — Agent offline since {since:%d %b %Y, %H:%M}"
    return None


def to_out(command: AgentCommand, agent: Agent, tz: str) -> CommandStatusOut:
    return CommandStatusOut(
        command_id=command.command_id,
        agent_id=agent.agent_id,
        agent_name=agent.agent_name,
        sync_mode=command.sync_mode,
        date_from=command.date_from,
        date_to=command.date_to,
        status=command.status,
        created_at=command.created_at,
        created_by=command.created_by,
        claimed_at=command.claimed_at,
        lease_expires_at=command.lease_expires_at,
        completed_at=command.completed_at,
        error_code=command.error_code,
        error_message=command.error_message,
        waiting_label=waiting_label(command, agent, tz),
    )


async def route_agent(
    session: AsyncSession, ctx: CompanyContext, agent_id: uuid.UUID | None
) -> Agent:
    if agent_id is not None:
        agent = await session.scalar(
            scoped(select(Agent), Agent, ctx).where(Agent.agent_id == agent_id)
        )
        if agent is None:  # RTE-1.5: never across company boundaries
            raise AppError(ErrorCode.FORBIDDEN, "Agent not found in this company", 403)
        if agent.status == AgentStatus.REVOKED:
            raise AppError(ErrorCode.AGENT_REVOKED, "This Agent has been revoked", 409)
        if agent.status == AgentStatus.INCOMPATIBLE:
            raise AppError(
                ErrorCode.AGENT_INCOMPATIBLE, "This Agent is below the minimum version", 409
            )
        return agent
    eligible = list(
        (
            await session.execute(
                scoped(select(Agent), Agent, ctx).where(Agent.status.not_in(CANNOT_RECEIVE))
            )
        ).scalars()
    )
    if len(eligible) == 1:  # D-036 #5: even OFFLINE or REGISTERING; the command waits
        return eligible[0]
    if not eligible:
        raise AppError(
            ErrorCode.AGENT_SELECTION_REQUIRED, "No Agent can take commands; register one", 422
        )
    active = [a for a in eligible if a.status == AgentStatus.ACTIVE]
    if len(active) == 1:  # RTE-1.1
        return active[0]
    raise AppError(  # RTE-1.2
        ErrorCode.AGENT_SELECTION_REQUIRED,
        f"This company has {len(eligible)} Agents; choose one (agent_id)",
        422,
    )


async def create_command(
    session: AsyncSession, ctx: CompanyContext, body: SyncRequest, agent_id: uuid.UUID | None
) -> CommandStatusOut:
    """AGT-1.5: creates a PENDING command and nothing else; the Agent collects it by polling."""
    agent = await route_agent(session, ctx, agent_id)
    command = AgentCommand(
        company_id=ctx.company_id,
        agent_id=agent.agent_id,
        command_type=CommandType.RUN_SYNC,
        sync_mode=body.sync_mode,
        date_from=body.date_from,
        date_to=body.date_to,
        status=CommandStatus.PENDING,
        created_by=ctx.user_id,
    )
    session.add(command)
    await session.flush()
    await audit.record(
        session,
        company_id=ctx.company_id,
        user_id=ctx.user_id,
        action="SYNC_REQUESTED",
        entity_type="agent_command",
        entity_id=str(command.command_id),
        after={"agent_id": str(agent.agent_id), "sync_mode": body.sync_mode.value},
        data_range=(
            {"from": body.date_from.isoformat(), "to": body.date_to.isoformat()}
            if body.date_from and body.date_to
            else None
        ),
    )
    company = await session.get(Company, ctx.company_id)
    assert company is not None
    await session.commit()
    return to_out(command, agent, company.company_timezone)


async def get_command(
    session: AsyncSession, ctx: CompanyContext, command_id: uuid.UUID
) -> CommandStatusOut:
    row = (
        await session.execute(
            scoped(select(AgentCommand, Agent, Company.company_timezone), AgentCommand, ctx)
            .join(Agent, Agent.agent_id == AgentCommand.agent_id)
            .join(Company, Company.company_id == AgentCommand.company_id)
            .where(AgentCommand.command_id == command_id)
        )
    ).one_or_none()
    if row is None:
        raise AppError(ErrorCode.NOT_FOUND, "Command not found", 404)
    command, agent, tz = row
    return to_out(command, agent, tz)


# --- the Agent side (claim, progress, result) ---------------------------------------------


def _agent_out(command: AgentCommand) -> AgentCommandOut:
    return AgentCommandOut(
        command_id=command.command_id,
        sync_mode=command.sync_mode,
        date_from=command.date_from,
        date_to=command.date_to,
        status=command.status,
        lease_expires_at=command.lease_expires_at,
    )


def _mine(agent: AgentContext, command_id: uuid.UUID) -> ColumnElement[bool]:
    return and_(
        AgentCommand.command_id == command_id,
        AgentCommand.agent_id == agent.agent_id,
        AgentCommand.company_id == agent.company_id,
    )


async def _not_applicable(
    session: AsyncSession, agent: AgentContext, command_id: uuid.UUID
) -> AppError:
    """No row matched: 404 if it is not this Agent's command (other companies' commands are
    never revealed), else 409 and the row is left exactly as it was (AGT-1.9)."""
    mine = await session.scalar(select(AgentCommand.command_id).where(_mine(agent, command_id)))
    if mine is None:
        return AppError(ErrorCode.NOT_FOUND, "Command not found", 404)
    return AppError(
        ErrorCode.INVALID_COMMAND_STATE, "The command is not in a state that allows this", 409
    )


async def _lease(session: AsyncSession, agent: AgentContext) -> timedelta:
    seconds = await get_setting(session, agent.company_id, "agent.command_lease_seconds")
    return timedelta(seconds=seconds)


async def claim_uncommitted(
    session: AsyncSession, agent: AgentContext, command_id: uuid.UUID, now: datetime
) -> AgentCommand:
    """AGT-1.3: one conditional UPDATE, so a command can be claimed only once. The partial
    unique index allows one command in progress per Agent (D-035 #13). Does not commit."""
    if agent.status == AgentStatus.INCOMPATIBLE:
        raise AppError(ErrorCode.AGENT_INCOMPATIBLE, "This Agent is below the minimum version", 409)
    if agent.status != AgentStatus.ACTIVE:
        raise AppError(
            ErrorCode.INVALID_COMMAND_STATE, "The Agent is not active; send a heartbeat", 409
        )
    timeout = await get_setting(session, agent.company_id, "agent.command_claim_timeout_minutes")
    lease = await _lease(session, agent)
    try:
        async with session.begin_nested():
            command = (
                await session.execute(
                    update(AgentCommand)
                    .where(
                        _mine(agent, command_id),
                        AgentCommand.status == CommandStatus.PENDING,
                        AgentCommand.created_at > now - timedelta(minutes=timeout),  # D-035 #3
                    )
                    .values(
                        status=CommandStatus.CLAIMED, claimed_at=now, lease_expires_at=now + lease
                    )
                    .returning(AgentCommand)
                )
            ).scalar_one_or_none()
    except IntegrityError:
        raise AppError(
            ErrorCode.INVALID_COMMAND_STATE, "Agent already has a command in progress", 409
        ) from None
    if command is None:
        raise await _not_applicable(session, agent, command_id)
    return command


async def claim(
    session: AsyncSession, agent: AgentContext, command_id: uuid.UUID
) -> AgentCommandOut:
    command = await claim_uncommitted(session, agent, command_id, datetime.now(UTC))
    await session.commit()
    return _agent_out(command)


async def progress(
    session: AsyncSession, agent: AgentContext, command_id: uuid.UUID
) -> AgentCommandOut:
    """AGT-1.7: CLAIMED/RUNNING -> RUNNING and the lease renewed, only while the lease is
    unexpired (D-035 #2). Also a heartbeat (D-035 #12)."""
    now = datetime.now(UTC)
    lease = await _lease(session, agent)
    command = (
        await session.execute(
            update(AgentCommand)
            .where(
                _mine(agent, command_id),
                AgentCommand.status.in_([CommandStatus.CLAIMED, CommandStatus.RUNNING]),
                AgentCommand.lease_expires_at > now,
            )
            .values(status=CommandStatus.RUNNING, lease_expires_at=now + lease)
            .returning(AgentCommand)
        )
    ).scalar_one_or_none()
    if command is None:
        raise await _not_applicable(session, agent, command_id)
    await session.execute(
        update(Agent)
        .where(Agent.agent_id == agent.agent_id)
        .values(
            last_heartbeat_at=now,
            status=case(
                (Agent.status == AgentStatus.OFFLINE, AgentStatus.ACTIVE), else_=Agent.status
            ),
        )
    )
    await session.commit()
    return _agent_out(command)


async def result(
    session: AsyncSession, agent: AgentContext, command_id: uuid.UUID, body: ResultRequest
) -> AgentCommandOut:
    """COMPLETED only from RUNNING; FAILED from CLAIMED or RUNNING (D-035 #4); lease unexpired."""
    now = datetime.now(UTC)
    allowed = (
        [CommandStatus.RUNNING]
        if body.status == CommandStatus.COMPLETED
        else [CommandStatus.CLAIMED, CommandStatus.RUNNING]
    )
    command = (
        await session.execute(
            update(AgentCommand)
            .where(
                _mine(agent, command_id),
                AgentCommand.status.in_(allowed),
                AgentCommand.lease_expires_at > now,
            )
            .values(
                status=body.status,
                completed_at=now,
                error_code=body.error_code,
                error_message=body.error_message,
            )
            .returning(AgentCommand)
        )
    ).scalar_one_or_none()
    if command is None:
        raise await _not_applicable(session, agent, command_id)
    await session.commit()
    return _agent_out(command)
