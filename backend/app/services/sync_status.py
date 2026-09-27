"""What the dashboard shows about syncing (P5.8, SRS 19.2, AC-12). Read-only; every query is
scoped to the caller's company (SEC-1.7)."""

import uuid
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.gates import collection_sync_mode
from app.core.permissions import CompanyContext, scoped
from app.models.agents import Agent
from app.models.enums import CollectionType, SyncMode, SyncRunStatus, WatermarkStatus
from app.models.sync import SyncError, SyncRun, SyncWatermark
from app.schemas.sync import (
    CollectionStatus,
    LeaseStatus,
    RunSummary,
    SyncErrorOut,
    SyncStatusOut,
)
from app.services.sync_runs import INITIAL_SYNC_INCOMPLETE, initial_sync_incomplete
from app.sync.holds import held_back

LABELS = {"INCREMENTAL": "Incremental", "FULL_ONLY": "Full sync only"}


def _summary(run: SyncRun) -> RunSummary:
    return RunSummary(
        sync_run_id=run.sync_run_id,
        agent_id=run.agent_id,
        command_id=run.command_id,
        sync_mode=SyncMode(run.sync_mode),
        status=SyncRunStatus(run.status),
        records_fetched=run.records_fetched,
        records_failed=run.records_failed,
        started_at=run.started_at,
        ended_at=run.ended_at,
    )


async def _watermarks(
    session: AsyncSession, ctx: CompanyContext
) -> list[tuple[SyncWatermark, str | None]]:
    rows = await session.execute(
        scoped(select(SyncWatermark, Agent.agent_name), SyncWatermark, ctx).outerjoin(
            Agent, Agent.agent_id == SyncWatermark.locked_by_agent_id
        )
    )
    return [(w, name) for w, name in rows.tuples()]


async def status(session: AsyncSession, ctx: CompanyContext) -> SyncStatusOut:
    now = datetime.now(UTC)
    stored = {w.collection_type: (w, name) for w, name in await _watermarks(session, ctx)}
    held = await held_back(session, ctx.company_id)
    collections = []
    for collection in CollectionType:
        mode = collection_sync_mode(collection.value)
        w, holder = stored.get(collection.value, (None, None))
        live = w is not None and w.lock_expires_at is not None and w.lock_expires_at > now
        collections.append(
            CollectionStatus(
                collection_type=collection,
                mode=mode,
                label=LABELS[mode],
                watermark=w.last_alter_id if w else 0,
                status=w.status if w else WatermarkStatus.NEVER_SYNCED.value,
                last_successful_sync_at=w.last_successful_sync_at if w else None,
                lease_holder=holder if live else None,
                lease_expires_at=w.lock_expires_at if live and w else None,
                held_back=held.get(collection.value, 0),
            )
        )
    last = (
        await session.execute(
            scoped(select(SyncRun), SyncRun, ctx)
            .order_by(SyncRun.started_at.desc(), SyncRun.sync_run_id)
            .limit(1)
        )
    ).scalar_one_or_none()
    warnings = []
    if await initial_sync_incomplete(session, ctx.company_id):
        warnings.append(INITIAL_SYNC_INCOMPLETE)
    return SyncStatusOut(
        collections=collections,
        last_run=_summary(last) if last else None,
        warnings=warnings,
    )


async def leases(session: AsyncSession, ctx: CompanyContext) -> list[LeaseStatus]:
    """Every held lease, live or expired (SYNC-4.2/4.3)."""
    now = datetime.now(UTC)
    return [
        LeaseStatus(
            collection_type=CollectionType(w.collection_type),
            holder_agent_id=w.locked_by_agent_id,
            holder_name=name or "",
            acquired_at=w.lock_acquired_at,
            expires_at=w.lock_expires_at,
            live=w.lock_expires_at is not None and w.lock_expires_at > now,
        )
        for w, name in await _watermarks(session, ctx)
        if w.locked_by_agent_id is not None
    ]


async def runs(
    session: AsyncSession, ctx: CompanyContext, limit: int, before: datetime | None
) -> list[RunSummary]:
    """Newest first; pass the last row's `started_at` as `before` for the next page."""
    stmt = scoped(select(SyncRun), SyncRun, ctx)
    if before is not None:
        stmt = stmt.where(SyncRun.started_at < before)
    rows = await session.execute(
        stmt.order_by(SyncRun.started_at.desc(), SyncRun.sync_run_id).limit(limit)
    )
    return [_summary(r) for r in rows.scalars()]


async def errors(
    session: AsyncSession,
    ctx: CompanyContext,
    *,
    sync_run_id: uuid.UUID | None,
    code: str | None,
    limit: int,
    before: int | None,
) -> list[SyncErrorOut]:
    """Newest first; pass the last row's `id` as `before` for the next page."""
    stmt = scoped(select(SyncError), SyncError, ctx)
    if sync_run_id is not None:
        stmt = stmt.where(SyncError.sync_run_id == sync_run_id)
    if code is not None:
        stmt = stmt.where(SyncError.error_code == code)
    if before is not None:
        stmt = stmt.where(SyncError.id < before)
    rows = await session.execute(stmt.order_by(SyncError.id.desc()).limit(limit))
    return [
        SyncErrorOut(
            id=e.id,
            sync_run_id=e.sync_run_id,
            entity_type=e.entity_type,
            tally_guid=e.tally_guid,
            alter_id=e.alter_id,
            error_code=e.error_code,
            message=e.message,
            watermark_hold=e.watermark_hold,
            created_at=e.created_at,
        )
        for e in rows.scalars()
    ]
