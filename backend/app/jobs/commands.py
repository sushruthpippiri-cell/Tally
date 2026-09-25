"""Command timeouts (AGT-1.8, AGT-1.10). Never reassigned, never retried (AGT-1.4, AGT-1.9):
these jobs only move a command to a final state."""

from datetime import datetime

from sqlalchemy import func, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.jobs.agents import company_int_setting
from app.models.agents import AgentCommand
from app.models.enums import CommandStatus
from tally_contract.log import get_logger

log = get_logger(__name__)

LOST_REASON = "Lease expired: no progress from the Agent before the deadline"


async def on_command_lost(session: AsyncSession, command: AgentCommand) -> None:
    """Hook for P5: fail the command's sync run and release the leases it holds.
    ponytail: a no-op until P5 introduces sync runs and leases."""


async def expire_pending(session: AsyncSession, now: datetime) -> int:
    """AGT-1.10: PENDING and not claimed within the company's claim timeout -> EXPIRED."""
    minutes = company_int_setting(AgentCommand.company_id, "agent.command_claim_timeout_minutes")
    rows = await session.execute(
        update(AgentCommand)
        .where(
            AgentCommand.status == CommandStatus.PENDING,
            AgentCommand.created_at <= now - func.make_interval(0, 0, 0, 0, 0, minutes),
        )
        .values(
            status=CommandStatus.EXPIRED,
            completed_at=now,
            error_message=func.concat("Not claimed within ", minutes, " minutes"),
        )
        .returning(AgentCommand.command_id, AgentCommand.agent_id)
        .execution_options(synchronize_session=False)
    )
    expired = rows.all()
    for command_id, agent_id in expired:
        log.info("command_expired", command_id=str(command_id), agent_id=str(agent_id))
    return len(expired)


async def mark_lost(session: AsyncSession, now: datetime) -> int:
    """AGT-1.8: CLAIMED/RUNNING past lease_expires_at -> FAILED_AGENT_LOST, reason recorded.
    Progress and result need an unexpired lease, so they can never race this back (D-035 #2)."""
    rows = await session.execute(
        update(AgentCommand)
        .where(
            AgentCommand.status.in_([CommandStatus.CLAIMED, CommandStatus.RUNNING]),
            AgentCommand.lease_expires_at <= now,
        )
        .values(status=CommandStatus.FAILED_AGENT_LOST, completed_at=now, error_message=LOST_REASON)
        .returning(AgentCommand)
        .execution_options(synchronize_session=False)
    )
    lost = list(rows.scalars())
    for command in lost:
        log.warning(
            "command_agent_lost",
            command_id=str(command.command_id),
            agent_id=str(command.agent_id),
            lease_expires_at=command.lease_expires_at.isoformat()
            if command.lease_expires_at
            else None,
        )
        await on_command_lost(session, command)
    return len(lost)


async def command_timeouts(session: AsyncSession, now: datetime) -> int:
    return await expire_pending(session, now) + await mark_lost(session, now)
