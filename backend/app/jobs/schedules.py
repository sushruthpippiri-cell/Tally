"""Fire due schedules (RTE-1.3, D-036 #2-4). One command per due schedule, however many runs
were missed; for one Agent, simultaneous firings are created INCREMENTAL first so that a
RECONCILIATION compares against the latest data."""

from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import audit
from app.models.agents import Agent, AgentCommand, SyncSchedule
from app.models.company import Company
from app.models.enums import CommandStatus, CommandType, SyncMode
from app.services.commands import CANNOT_RECEIVE
from app.services.schedules import next_fire
from tally_contract.log import get_logger

log = get_logger(__name__)

MODE_ORDER = {
    SyncMode.INCREMENTAL: 0,
    SyncMode.FULL: 1,
    SyncMode.DATE_RANGE: 2,
    SyncMode.RECONCILIATION: 3,
}


async def fire_schedules(session: AsyncSession, now: datetime) -> int:
    due = (
        (
            await session.execute(
                select(SyncSchedule, Agent, Company.company_timezone)
                .join(Agent, Agent.agent_id == SyncSchedule.agent_id)
                .join(Company, Company.company_id == SyncSchedule.company_id)
                .where(SyncSchedule.is_active, SyncSchedule.next_fire_at <= now)
                .with_for_update(of=SyncSchedule, skip_locked=True)
            )
        )
        .tuples()
        .all()
    )
    created = 0
    for schedule, agent, tz in sorted(
        due, key=lambda row: (str(row[1].agent_id), MODE_ORDER[SyncMode(row[0].sync_mode)])
    ):
        schedule.next_fire_at = next_fire(schedule.cron_expression, tz, now)
        if agent.status in CANNOT_RECEIVE:  # D-012 / D-036 #4
            log.info(
                "schedule_skipped", schedule_id=str(schedule.schedule_id), agent_status=agent.status
            )
            continue
        command = AgentCommand(
            company_id=schedule.company_id,
            agent_id=schedule.agent_id,
            command_type=CommandType.RUN_SYNC,
            sync_mode=schedule.sync_mode,
            status=CommandStatus.PENDING,
            created_by=None,
            created_at=now,  # same instant for all; seq keeps the creation order (D-036 #1)
        )
        session.add(command)
        await session.flush()
        await audit.record(
            session,
            company_id=schedule.company_id,
            user_id=None,
            action="SYNC_REQUESTED",
            entity_type="agent_command",
            entity_id=str(command.command_id),
            after={
                "agent_id": str(schedule.agent_id),
                "sync_mode": schedule.sync_mode,
                "schedule_id": str(schedule.schedule_id),
            },
        )
        created += 1
    return created
