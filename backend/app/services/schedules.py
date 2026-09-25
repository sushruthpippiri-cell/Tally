"""Sync schedules (RTE-1.3, D-023, D-036). Cron is evaluated in company_timezone (TZ-1.1);
`next_fire_at` is set while a schedule is active and null while it is not."""

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from apscheduler.triggers.cron import CronTrigger
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import audit
from app.core.errors import AppError
from app.core.permissions import CompanyContext, scoped
from app.models.agents import Agent, SyncSchedule
from app.models.company import Company
from app.schemas.schedules import ScheduleCreate, ScheduleOut, ScheduleUpdate
from app.services.commands import route_agent
from tally_contract.errors import ErrorCode


def next_fire(cron: str, tz: str, after: datetime) -> datetime:
    """The first occurrence strictly after `after`, in UTC."""
    trigger = CronTrigger.from_crontab(cron, timezone=ZoneInfo(tz))
    fire: datetime = trigger.get_next_fire_time(None, after + timedelta(microseconds=1))
    return fire.astimezone(UTC)


def _check_cron(cron: str, tz: str) -> None:
    try:
        CronTrigger.from_crontab(cron, timezone=ZoneInfo(tz))
    except ValueError as exc:
        raise AppError(
            ErrorCode.VALIDATION_ERROR,
            f"Invalid cron expression: {exc}",
            422,
            {"errors": [{"key": "cron_expression", "message": str(exc)}]},
        ) from None


def activate(schedule: SyncSchedule, tz: str, now: datetime) -> None:
    """Switch a schedule on from `now`. P5 calls this for a new Agent's default schedules
    after its first FULL sync (D-036 #6); the caller audits."""
    schedule.is_active = True
    schedule.next_fire_at = next_fire(schedule.cron_expression, tz, now)


def _fields(s: SyncSchedule) -> dict[str, Any]:
    return {
        "cron_expression": s.cron_expression,
        "sync_mode": s.sync_mode,
        "is_active": s.is_active,
    }


def _out(s: SyncSchedule, agent_name: str) -> ScheduleOut:
    return ScheduleOut(
        schedule_id=s.schedule_id,
        agent_id=s.agent_id,
        agent_name=agent_name,
        cron_expression=s.cron_expression,
        sync_mode=s.sync_mode,
        is_active=s.is_active,
        next_fire_at=s.next_fire_at,
        created_by=s.created_by,
    )


async def _tz(session: AsyncSession, ctx: CompanyContext) -> str:
    company = await session.get(Company, ctx.company_id)
    assert company is not None
    return company.company_timezone


async def list_schedules(session: AsyncSession, ctx: CompanyContext) -> list[ScheduleOut]:
    rows = await session.execute(
        scoped(select(SyncSchedule, Agent.agent_name), SyncSchedule, ctx)
        .join(Agent, Agent.agent_id == SyncSchedule.agent_id)
        .order_by(Agent.agent_name, SyncSchedule.cron_expression)
    )
    return [_out(s, name) for s, name in rows.tuples()]


async def create_schedule(
    session: AsyncSession, ctx: CompanyContext, body: ScheduleCreate
) -> ScheduleOut:
    tz = await _tz(session, ctx)
    _check_cron(body.cron_expression, tz)
    agent = await route_agent(session, ctx, body.agent_id)  # 403 other company, 409 revoked
    schedule = SyncSchedule(
        company_id=ctx.company_id,
        agent_id=agent.agent_id,
        cron_expression=body.cron_expression,
        sync_mode=body.sync_mode,
        is_active=False,
        created_by=ctx.user_id,
    )
    if body.is_active:
        activate(schedule, tz, datetime.now(UTC))
    session.add(schedule)
    await session.flush()
    await audit.record(
        session,
        company_id=ctx.company_id,
        user_id=ctx.user_id,
        action="SCHEDULE_CREATED",
        entity_type="sync_schedule",
        entity_id=str(schedule.schedule_id),
        after=_fields(schedule) | {"agent_id": str(agent.agent_id)},
    )
    await session.commit()
    return _out(schedule, agent.agent_name)


async def update_schedule(
    session: AsyncSession, ctx: CompanyContext, schedule_id: uuid.UUID, body: ScheduleUpdate
) -> ScheduleOut:
    row = (
        await session.execute(
            scoped(select(SyncSchedule, Agent.agent_name), SyncSchedule, ctx)
            .join(Agent, Agent.agent_id == SyncSchedule.agent_id)
            .where(SyncSchedule.schedule_id == schedule_id)
        )
    ).one_or_none()
    if row is None:
        raise AppError(ErrorCode.NOT_FOUND, "Schedule not found", 404)
    schedule, agent_name = row
    tz = await _tz(session, ctx)
    before = _fields(schedule)
    if body.cron_expression is not None:
        _check_cron(body.cron_expression, tz)
        schedule.cron_expression = body.cron_expression
    if body.sync_mode is not None:
        schedule.sync_mode = body.sync_mode
    active = schedule.is_active if body.is_active is None else body.is_active
    if active:
        activate(schedule, tz, datetime.now(UTC))  # recomputed from now for the new cron
    else:
        schedule.is_active, schedule.next_fire_at = False, None
    changed_before, changed_after = audit.diff(before, _fields(schedule))
    if changed_after:
        await audit.record(
            session,
            company_id=ctx.company_id,
            user_id=ctx.user_id,
            action="SCHEDULE_UPDATED",
            entity_type="sync_schedule",
            entity_id=str(schedule_id),
            before=changed_before,
            after=changed_after,
        )
    await session.commit()
    return _out(schedule, agent_name)


async def deactivate_for_agent(
    session: AsyncSession,
    company_id: uuid.UUID,
    agent_id: uuid.UUID,
    user_id: uuid.UUID | None,
    reason: str,
) -> int:
    """Revoking an Agent stops its schedules in the same transaction (D-036 #6)."""
    schedules = (
        await session.execute(
            select(SyncSchedule).where(
                SyncSchedule.company_id == company_id,
                SyncSchedule.agent_id == agent_id,
                SyncSchedule.is_active,
            )
        )
    ).scalars()
    count = 0
    for schedule in schedules:
        schedule.is_active, schedule.next_fire_at = False, None
        await audit.record(
            session,
            company_id=company_id,
            user_id=user_id,
            action="SCHEDULE_DEACTIVATED",
            entity_type="sync_schedule",
            entity_id=str(schedule.schedule_id),
            before={"is_active": True},
            after={"is_active": False, "reason": reason},
        )
        count += 1
    return count
