"""Sync runs and leases for the Agent (P5.1, SRS 5.9, 6.3, D-039)."""

import uuid
from datetime import UTC, datetime

from sqlalchemy import delete, exists, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import audit
from app.core.agent_credentials import AgentContext
from app.core.errors import AppError
from app.core.gates import collection_sync_mode
from app.models.agents import AgentCommand, SyncSchedule
from app.models.company import Company
from app.models.enums import (
    CollectionType,
    CommandStatus,
    KeyListStatus,
    SyncMode,
    SyncRunStatus,
    WatermarkStatus,
)
from app.models.sync import SyncError, SyncKeyList, SyncKeyListKey, SyncRun, SyncWatermark
from app.schemas.sync import (
    CollectionPlan,
    FinishRequest,
    LeaseOut,
    LeaseRequest,
    ReleaseOut,
    ReleaseRequest,
    RunOut,
    RunPlan,
)
from app.services import schedules
from app.services.settings import get_setting
from app.sync import holds, leases
from app.sync.context import NOT_STORED, error_row
from tally_contract.errors import ErrorCode
from tally_contract.log import get_logger

log = get_logger(__name__)

INITIAL_SYNC_INCOMPLETE = (
    "INITIAL_SYNC_INCOMPLETE: no sync has completed without errors yet, so some data may be "
    "missing; see Sync errors"
)


async def running_command(
    session: AsyncSession, agent: AgentContext, command_id: uuid.UUID, *, lock: bool = False
) -> AgentCommand:
    """The caller's command, which must be RUNNING (D-039 #1). FOR SHARE when `lock`, so the
    lost-Agent job cannot change it under a chunk in flight."""
    stmt = select(AgentCommand).where(
        AgentCommand.command_id == command_id,
        AgentCommand.agent_id == agent.agent_id,
        AgentCommand.company_id == agent.company_id,
    )
    if lock:
        stmt = stmt.with_for_update(read=True)
    command = (
        await session.execute(stmt.execution_options(populate_existing=True))
    ).scalar_one_or_none()
    if command is None:
        raise AppError(ErrorCode.NOT_FOUND, "Command not found", 404)
    if command.status != CommandStatus.RUNNING:
        raise AppError(
            ErrorCode.INVALID_COMMAND_STATE,
            f"The command is {command.status}; only a RUNNING command may sync",
            409,
        )
    return command


async def open_run(
    session: AsyncSession, agent: AgentContext, sync_run_id: uuid.UUID, *, lock: bool = False
) -> tuple[SyncRun, AgentCommand]:
    run = (
        await session.execute(
            select(SyncRun).where(
                SyncRun.sync_run_id == sync_run_id,
                SyncRun.agent_id == agent.agent_id,
                SyncRun.company_id == agent.company_id,
            )
        )
    ).scalar_one_or_none()
    if run is None or run.command_id is None:
        raise AppError(ErrorCode.NOT_FOUND, "Sync run not found", 404)
    command = await running_command(session, agent, run.command_id, lock=lock)
    if run.status != SyncRunStatus.IN_PROGRESS:
        raise AppError(ErrorCode.INVALID_COMMAND_STATE, f"The sync run is {run.status}", 409)
    return run, command


async def key_lists_due(
    session: AsyncSession, company_id: uuid.UUID, sync_run_id: uuid.UUID
) -> set[CollectionType]:
    """SYNC-5.4, D-041 #6: a key list is due every N incremental runs (sync.key_list_interval):
    when the collection has none evaluated yet, or N-1 INCREMENTAL runs started since."""
    every = int(await get_setting(session, company_id, "sync.key_list_interval"))
    last = dict(
        (
            await session.execute(
                select(SyncKeyList.collection_type, func.max(SyncKeyList.evaluated_at))
                .where(SyncKeyList.company_id == company_id, SyncKeyList.evaluated_at.is_not(None))
                .group_by(SyncKeyList.collection_type)
            )
        )
        .tuples()
        .all()
    )
    due: set[CollectionType] = set()
    for collection in CollectionType:
        if collection == CollectionType.COMPANY:
            continue
        since = last.get(collection.value)
        if since is None:
            due.add(collection)
            continue
        runs = await session.scalar(
            select(func.count()).where(
                SyncRun.company_id == company_id,
                SyncRun.sync_mode == SyncMode.INCREMENTAL,
                SyncRun.started_at > since,
                SyncRun.sync_run_id != sync_run_id,
            )
        )
        if int(runs or 0) >= every - 1:
            due.add(collection)
    return due


async def start_run(session: AsyncSession, agent: AgentContext, command_id: uuid.UUID) -> RunPlan:
    command = await running_command(session, agent, command_id)
    now = datetime.now(UTC)
    run = SyncRun(
        company_id=agent.company_id,
        agent_id=agent.agent_id,
        command_id=command_id,
        sync_mode=command.sync_mode,
        started_at=now,
        status=SyncRunStatus.IN_PROGRESS,
    )
    session.add(run)
    await session.flush()
    stored = {
        w.collection_type: w
        for w in (
            await session.execute(
                select(SyncWatermark).where(SyncWatermark.company_id == agent.company_id)
            )
        ).scalars()
    }
    plan: dict[CollectionType, CollectionPlan] = {}
    due = await key_lists_due(session, agent.company_id, run.sync_run_id)
    for collection in CollectionType:
        mode = collection_sync_mode(collection.value)
        watermark = stored.get(collection.value)
        never = watermark is None or watermark.status == WatermarkStatus.NEVER_SYNCED
        plan[collection] = CollectionPlan(
            mode=mode,
            watermark=watermark.last_alter_id if watermark else 0,
            full=command.sync_mode == SyncMode.FULL or mode == "FULL_ONLY" or never,
            key_list_due=collection in due,
        )
    await session.commit()
    return RunPlan(
        sync_run_id=run.sync_run_id,
        sync_mode=SyncMode(command.sync_mode),
        date_from=command.date_from,
        date_to=command.date_to,
        collections=plan,
    )


async def acquire_lease(session: AsyncSession, agent: AgentContext, body: LeaseRequest) -> LeaseOut:
    await open_run(session, agent, body.sync_run_id)
    row = await leases.acquire(session, agent, body.collection_type, datetime.now(UTC))
    await session.commit()
    assert row.lock_expires_at is not None
    return LeaseOut(
        collection_type=body.collection_type,
        last_alter_id=row.last_alter_id,
        lock_expires_at=row.lock_expires_at,
    )


async def renew_leases(session: AsyncSession, agent: AgentContext) -> int:
    renewed = await leases.renew_all(session, agent, datetime.now(UTC))
    await session.commit()
    return renewed


async def release_lease(
    session: AsyncSession, agent: AgentContext, body: ReleaseRequest
) -> ReleaseOut:
    """With `complete` + `start_max_alter_id`, a FULL pull may move the watermark to the max
    ALTERID read before it began, never past a record that failed in this run, and never for
    a DATE_RANGE run, never for a full-only collection (D-039 #2, #7, D-040 #7)."""
    run = (
        await session.execute(
            select(SyncRun).where(
                SyncRun.sync_run_id == body.sync_run_id,
                SyncRun.agent_id == agent.agent_id,
                SyncRun.company_id == agent.company_id,
            )
        )
    ).scalar_one_or_none()
    if run is None:
        raise AppError(ErrorCode.NOT_FOUND, "Sync run not found", 404)
    advance_to = None
    if (
        body.complete
        and body.start_max_alter_id is not None
        and run.sync_mode != SyncMode.DATE_RANGE
        and collection_sync_mode(body.collection_type.value) != "FULL_ONLY"  # D-040 #7
    ):
        advance_to = holds.capped(
            body.start_max_alter_id,
            await holds.run_cap(session, run.sync_run_id, body.collection_type),
        )
    last = await leases.release(session, agent, body.collection_type, datetime.now(UTC), advance_to)
    await session.commit()
    return ReleaseOut(collection_type=body.collection_type, last_alter_id=last)


async def close_run(
    session: AsyncSession, run: SyncRun, reported: SyncRunStatus, now: datetime
) -> SyncRunStatus:
    """D-040 #1 (SYNC-6.4): reported FAILED -> PARTIAL if anything was committed, else FAILED;
    reported COMPLETED -> PARTIAL if any data was not stored, else COMPLETED."""
    if reported == SyncRunStatus.FAILED:
        status = SyncRunStatus.PARTIAL if run.records_fetched else SyncRunStatus.FAILED
    else:
        missing = await session.scalar(
            select(
                exists().where(
                    SyncError.sync_run_id == run.sync_run_id, SyncError.error_code.in_(NOT_STORED)
                )
            )
        )
        status = SyncRunStatus.PARTIAL if missing else SyncRunStatus.COMPLETED
    run.status, run.ended_at = status, now
    await _abandon_key_lists(session, run.sync_run_id)
    await session.flush()
    log.info("sync_run_closed", sync_run_id=str(run.sync_run_id), status=status.value)
    if run.sync_mode == SyncMode.FULL and status != SyncRunStatus.FAILED:
        await _activate_first_full(session, run, now)
    return status


async def _abandon_key_lists(session: AsyncSession, sync_run_id: uuid.UUID) -> None:
    """A closed run leaves no half-received key list behind (D-041 #1)."""
    rows = await session.execute(
        update(SyncKeyList)
        .where(
            SyncKeyList.sync_run_id == sync_run_id,
            SyncKeyList.status == KeyListStatus.RECEIVING,
        )
        .values(status=KeyListStatus.ABANDONED)
        .returning(SyncKeyList.list_id)
        .execution_options(synchronize_session=False)
    )
    abandoned = [list_id for (list_id,) in rows.all()]
    if abandoned:
        await session.execute(delete(SyncKeyListKey).where(SyncKeyListKey.list_id.in_(abandoned)))


async def _activate_first_full(session: AsyncSession, run: SyncRun, now: datetime) -> None:
    """D-036 #6, D-040 #6: the Agent's first FULL run that stored data (COMPLETED or PARTIAL)
    switches on its inactive default schedules. Only the first, so a schedule an Owner turned
    off stays off."""
    earlier = await session.scalar(
        select(
            exists().where(
                SyncRun.company_id == run.company_id,
                SyncRun.agent_id == run.agent_id,
                SyncRun.sync_mode == SyncMode.FULL,
                SyncRun.status.in_([SyncRunStatus.COMPLETED, SyncRunStatus.PARTIAL]),
                SyncRun.sync_run_id != run.sync_run_id,
            )
        )
    )
    if earlier:
        return
    company = await session.get(Company, run.company_id)
    assert company is not None
    defaults = await session.execute(
        select(SyncSchedule).where(
            SyncSchedule.company_id == run.company_id,
            SyncSchedule.agent_id == run.agent_id,
            SyncSchedule.is_active.is_(False),
            SyncSchedule.created_by.is_(None),
        )
    )
    for schedule in defaults.scalars():
        schedules.activate(schedule, company.company_timezone, now)
        await audit.record(
            session,
            company_id=run.company_id,
            user_id=None,
            action="SCHEDULE_ACTIVATED",
            entity_type="sync_schedule",
            entity_id=str(schedule.schedule_id),
            before={"is_active": False},
            after={"is_active": True, "reason": "first full sync"},
        )


async def close_command_runs(
    session: AsyncSession,
    command: AgentCommand,
    reported: SyncRunStatus,
    now: datetime,
    lost_reason: str | None = None,
) -> None:
    """The command's result, or its loss (D-040 #3, #4), closes the runs it left open."""
    runs = await session.execute(
        select(SyncRun)
        .where(
            SyncRun.company_id == command.company_id,
            SyncRun.command_id == command.command_id,
            SyncRun.status == SyncRunStatus.IN_PROGRESS,
        )
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    for run in runs.scalars().all():
        if lost_reason is not None:
            session.add(
                error_row(
                    company_id=run.company_id,
                    sync_run_id=run.sync_run_id,
                    entity_type="RUN",
                    code=ErrorCode.AGENT_LOST,
                    message=lost_reason,
                )
            )
        await close_run(session, run, reported, now)


async def initial_sync_incomplete(session: AsyncSession, company_id: uuid.UUID) -> bool:
    """D-040 #6: a run has finished but none has COMPLETED."""
    runs = SyncRun.company_id == company_id
    finished = await session.scalar(
        select(exists().where(runs, SyncRun.status != SyncRunStatus.IN_PROGRESS))
    )
    completed = await session.scalar(
        select(exists().where(runs, SyncRun.status == SyncRunStatus.COMPLETED))
    )
    return bool(finished) and not completed


async def finish_run(
    session: AsyncSession,
    agent: AgentContext,
    command_id: uuid.UUID,
    sync_run_id: uuid.UUID,
    body: FinishRequest,
) -> RunOut:
    """The Agent's view of the run, plus what it could not sync (D-040 #1, #2)."""
    run, _ = await open_run(session, agent, sync_run_id)
    if run.command_id != command_id:
        raise AppError(ErrorCode.NOT_FOUND, "Sync run not found", 404)
    for problem in body.problems:
        entity = problem.collection_type.value if problem.collection_type else "RUN"
        session.add(
            error_row(
                company_id=agent.company_id,
                sync_run_id=run.sync_run_id,
                entity_type=entity,
                code=ErrorCode(problem.code),
                message=problem.message,
            )
        )
        log.warning("sync_run_problem", code=problem.code, collection=entity)
    await session.flush()
    await close_run(session, run, SyncRunStatus(body.status), datetime.now(UTC))
    await leases.release_all(session, agent.company_id, agent.agent_id)
    await session.commit()
    return RunOut(
        sync_run_id=run.sync_run_id,
        status=SyncRunStatus(run.status),
        records_fetched=run.records_fetched,
        records_failed=run.records_failed,
        started_at=run.started_at,
        ended_at=run.ended_at,
    )
