"""Sync runs and leases for the Agent (P5.1, SRS 5.9, 6.3, D-039)."""

import uuid
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.agent_credentials import AgentContext
from app.core.errors import AppError
from app.core.gates import collection_sync_mode
from app.models.agents import AgentCommand
from app.models.enums import CollectionType, CommandStatus, SyncMode, SyncRunStatus, WatermarkStatus
from app.models.sync import SyncRun, SyncWatermark
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
from app.sync import holds, leases
from tally_contract.errors import ErrorCode


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
    for collection in CollectionType:
        mode = collection_sync_mode(collection.value)
        watermark = stored.get(collection.value)
        never = watermark is None or watermark.status == WatermarkStatus.NEVER_SYNCED
        plan[collection] = CollectionPlan(
            mode=mode,
            watermark=watermark.last_alter_id if watermark else 0,
            full=command.sync_mode == SyncMode.FULL or mode == "FULL_ONLY" or never,
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
    a DATE_RANGE run (D-039 #2, #7)."""
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
    ):
        advance_to = holds.capped(
            body.start_max_alter_id,
            await holds.run_cap(session, run.sync_run_id, body.collection_type),
        )
    last = await leases.release(session, agent, body.collection_type, datetime.now(UTC), advance_to)
    await session.commit()
    return ReleaseOut(collection_type=body.collection_type, last_alter_id=last)


async def finish_run(
    session: AsyncSession,
    agent: AgentContext,
    command_id: uuid.UUID,
    sync_run_id: uuid.UUID,
    body: FinishRequest,
) -> RunOut:
    """Basic bookkeeping; P5.7 adds the full PARTIAL rules and schedule activation."""
    run, _ = await open_run(session, agent, sync_run_id)
    if run.command_id != command_id:
        raise AppError(ErrorCode.NOT_FOUND, "Sync run not found", 404)
    status = SyncRunStatus(body.status)
    if status == SyncRunStatus.COMPLETED and run.records_failed:
        status = SyncRunStatus.PARTIAL  # D-039 #7: failing records make the run PARTIAL
    run.status, run.ended_at = status, datetime.now(UTC)
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
