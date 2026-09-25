"""Owner/Admin management of Agents (SRS 4.4, FR-4.4, AGT-4.2, AGT-5.4, D-036 #6)."""

import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import audit
from app.core.agent_credentials import new_credential
from app.core.errors import AppError
from app.core.permissions import CompanyContext, scoped
from app.models.agents import Agent, SyncSchedule
from app.models.enums import AgentStatus, TallyStatus
from app.schemas.agents import AgentOut, AgentsView, RotatedCredential, TallySettingsUpdate
from app.services.schedules import deactivate_for_agent
from app.services.settings import get_setting
from tally_contract.errors import ErrorCode

NO_ACTIVE_SCHEDULE = (
    "NO_ACTIVE_SCHEDULE: an Agent is ACTIVE but no schedule is active, so no automatic "
    "syncs will run"
)


def _warnings(agent: Agent) -> list[str]:
    warnings = []
    if agent.last_tally_status == TallyStatus.COMPANY_MISMATCH:
        warnings.append("COMPANY_MISMATCH: re-register this Agent (AGT-3.4)")
    if agent.status == AgentStatus.INCOMPATIBLE:
        warnings.append("INCOMPATIBLE: upgrade the Agent or its TDL package")
    if agent.queue_status and agent.queue_status.get("full"):
        warnings.append("QUEUE_FULL: the Agent's local queue is full")
    return warnings


async def list_agents(session: AsyncSession, ctx: CompanyContext) -> AgentsView:
    agents = list(
        (
            await session.execute(scoped(select(Agent), Agent, ctx).order_by(Agent.agent_name))
        ).scalars()
    )
    advisory_days = await get_setting(session, ctx.company_id, "agent.tally_uptime_advisory_days")
    rows = [
        AgentOut(
            agent_id=a.agent_id,
            agent_name=a.agent_name,
            status=a.status,
            agent_version=a.agent_version,
            tdl_version=a.tdl_version,
            tally_version=a.tally_version,
            tally_company_name=a.tally_company_name,
            tally_host=a.tally_host,
            tally_port=a.tally_port,
            extraction_batch_size=a.extraction_batch_size,
            last_heartbeat_at=a.last_heartbeat_at,
            offline_since=a.last_heartbeat_at if a.status == AgentStatus.OFFLINE else None,
            tally_uptime_seconds=a.tally_uptime_seconds,
            uptime_advisory=(a.tally_uptime_seconds or 0) > advisory_days * 86_400,
            queue_status=a.queue_status,
            last_tally_status=a.last_tally_status,
            tally_status_since=a.tally_status_since,
            registered_at=a.registered_at,
            revoked_at=a.revoked_at,
            warnings=_warnings(a),
        )
        for a in agents
    ]
    warnings = []
    if any(a.status == AgentStatus.ACTIVE for a in agents):
        active_schedules = await session.scalar(
            scoped(select(func.count()).select_from(SyncSchedule), SyncSchedule, ctx).where(
                SyncSchedule.is_active
            )
        )
        if not active_schedules:
            warnings.append(NO_ACTIVE_SCHEDULE)
    return AgentsView(agents=rows, warnings=warnings)


async def _missing_or_revoked(
    session: AsyncSession, ctx: CompanyContext, agent_id: uuid.UUID
) -> AppError:
    found = await session.scalar(
        scoped(select(Agent.agent_id), Agent, ctx).where(Agent.agent_id == agent_id)
    )
    if found is None:
        return AppError(ErrorCode.NOT_FOUND, "Agent not found", 404)
    return AppError(ErrorCode.AGENT_REVOKED, "This Agent has been revoked", 409)


async def rotate_uncommitted(
    session: AsyncSession, ctx: CompanyContext, agent_id: uuid.UUID
) -> RotatedCredential:
    """SEC-2.1: one UPDATE replaces salt and hash, so the old credential stops working in the
    same instant the new one starts; no window where both work. Same agent_id (SEC-2.3)."""
    credential, salt, credential_hash = new_credential(agent_id)
    rotated = await session.scalar(
        update(Agent)
        .where(
            Agent.agent_id == agent_id,
            Agent.company_id == ctx.company_id,
            Agent.status != AgentStatus.REVOKED,
        )
        .values(credential_hash=credential_hash, credential_salt=salt)
        .returning(Agent.agent_id)
        .execution_options(synchronize_session=False)
    )
    if rotated is None:
        raise await _missing_or_revoked(session, ctx, agent_id)
    await audit.record(
        session,
        company_id=ctx.company_id,
        user_id=ctx.user_id,
        action="AGENT_CREDENTIAL_ROTATED",
        entity_type="agent",
        entity_id=str(agent_id),
    )
    return RotatedCredential(agent_id=agent_id, credential=credential)


async def rotate(
    session: AsyncSession, ctx: CompanyContext, agent_id: uuid.UUID
) -> RotatedCredential:
    rotated = await rotate_uncommitted(session, ctx, agent_id)
    await session.commit()
    return rotated


async def revoke_uncommitted(
    session: AsyncSession, ctx: CompanyContext, agent_id: uuid.UUID
) -> None:
    """Permanent (SEC-2.3). Its schedules stop in the same transaction (D-036 #6)."""
    revoked = await session.scalar(
        update(Agent)
        .where(
            Agent.agent_id == agent_id,
            Agent.company_id == ctx.company_id,
            Agent.status != AgentStatus.REVOKED,
        )
        .values(status=AgentStatus.REVOKED, revoked_at=datetime.now(UTC))
        .returning(Agent.agent_id)
        .execution_options(synchronize_session=False)
    )
    if revoked is None:
        raise await _missing_or_revoked(session, ctx, agent_id)
    await deactivate_for_agent(session, ctx.company_id, agent_id, ctx.user_id, "agent revoked")
    await audit.record(
        session,
        company_id=ctx.company_id,
        user_id=ctx.user_id,
        action="AGENT_REVOKED",
        entity_type="agent",
        entity_id=str(agent_id),
    )


async def revoke(session: AsyncSession, ctx: CompanyContext, agent_id: uuid.UUID) -> None:
    await revoke_uncommitted(session, ctx, agent_id)
    await session.commit()


def _tally_fields(agent: Agent) -> dict[str, Any]:
    return {
        "tally_host": agent.tally_host,
        "tally_port": agent.tally_port,
        "tally_company_name": agent.tally_company_name,
        "extraction_batch_size": agent.extraction_batch_size,
    }


async def update_tally_settings(
    session: AsyncSession, ctx: CompanyContext, agent_id: uuid.UUID, body: TallySettingsUpdate
) -> AgentsView:
    """AGT-4.2, AGT-5.4: delivered to the Agent in the next heartbeat's config."""
    agent = await session.scalar(
        scoped(select(Agent), Agent, ctx).where(Agent.agent_id == agent_id)
    )
    if agent is None:
        raise AppError(ErrorCode.NOT_FOUND, "Agent not found", 404)
    if agent.status == AgentStatus.REVOKED:
        raise AppError(ErrorCode.AGENT_REVOKED, "This Agent has been revoked", 409)
    before = _tally_fields(agent)
    for key, value in body.model_dump(exclude_none=True).items():
        setattr(agent, key, value)
    changed_before, changed_after = audit.diff(before, _tally_fields(agent))
    if changed_after:
        await audit.record(
            session,
            company_id=ctx.company_id,
            user_id=ctx.user_id,
            action="AGENT_TALLY_SETTINGS_CHANGED",
            entity_type="agent",
            entity_id=str(agent_id),
            before=changed_before,
            after=changed_after,
        )
    await session.commit()
    return await list_agents(session, ctx)
