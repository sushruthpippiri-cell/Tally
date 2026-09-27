"""The ingest pipeline for one upload batch (P5.2, SRS 6.5, D-024, D-026, D-039).

    replay?  -> the stored result, no writes (D-024, SYNC-6.3)
    guards   -> command RUNNING, run IN_PROGRESS, live lease held (D-039 #1)
    chunks   -> `sync.db_commit_batch` records per transaction (SYNC-6.1), in ALTERID order,
                each re-checking the guards under row locks, then writing, recording failures
                and moving the watermark (SYNC-1.2); the batch stops at the first failed chunk
                (D-026)
A failing record is skipped, recorded, and holds the watermark below it (D-039 #7).
"""

import uuid
from collections.abc import Awaitable, Callable
from datetime import UTC, date, datetime
from typing import Any, Literal

from pydantic import BaseModel
from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.agent_credentials import AgentContext
from app.core.errors import AppError
from app.models.company import Company
from app.models.enums import CollectionType
from app.models.sync import SyncBatch, SyncError, SyncRun, SyncWatermark
from app.services.settings import get_setting
from app.services.sync_runs import open_run, running_command
from app.sync import holds, leases, masters, snapshots, vouchers
from app.sync.context import (
    SYNC_ERROR_KIND,
    ChunkOutcome,
    IngestContext,
    RecordFailure,
    error_row,
    not_stored,
)
from tally_contract.errors import ErrorCode
from tally_contract.log import get_logger
from tally_contract.records import AlterIdWindow, BatchEnvelope
from tally_contract.version import CONTRACT_VERSION

log = get_logger(__name__)

Writer = Callable[[AsyncSession, IngestContext, list[Any]], Awaitable[ChunkOutcome]]
WRITERS: dict[CollectionType, Writer] = {
    CollectionType.COMPANY: masters.write_company,
    **{c: masters.write_masters for c in masters.MODELS},
    CollectionType.VOUCHER: vouchers.write_vouchers,
}
NEEDS_BOOKS_FROM = (CollectionType.LEDGER, CollectionType.STOCK_ITEM)


class BatchResult(BaseModel):
    batch_id: uuid.UUID
    status: Literal["COMPLETE", "PARTIAL"]
    replayed: bool = False
    written: int = 0
    unchanged: int = 0
    rejected_stale: int = 0
    failed: int = 0
    chunks_committed: int = 0
    watermark: int | None = None
    error: str | None = None  # why the batch stopped early


def _major(version: str) -> str:
    return version.split(".", 1)[0]


async def _replayed(
    session: AsyncSession, agent: AgentContext, env: BatchEnvelope
) -> BatchResult | None:
    stored = await session.get(SyncBatch, env.batch_id)
    if stored is None or stored.company_id != agent.company_id:
        return None
    return BatchResult(
        batch_id=env.batch_id,
        status="COMPLETE",
        replayed=True,
        written=stored.accepted,
        rejected_stale=stored.rejected_stale,
        failed=stored.error_count,
    )


async def _context(
    session: AsyncSession,
    agent: AgentContext,
    env: BatchEnvelope,
    collection: CollectionType,
    is_snapshot: bool,
) -> IngestContext:
    company = await session.get(Company, agent.company_id)
    assert company is not None
    books_from: date | None = company.books_from
    if collection in NEEDS_BOOKS_FROM and not is_snapshot and books_from is None:
        raise AppError(
            ErrorCode.INVALID_COMMAND_STATE,
            "Sync the COMPANY collection first: openings are stored as at books-beginning",
            409,
        )
    return IngestContext(
        company_id=agent.company_id,
        agent_id=agent.agent_id,
        sync_run_id=env.sync_run_id,
        collection=collection,
        now=datetime.now(UTC),
        company_guid=company.tally_guid,
        books_from=books_from,
        snapshots=is_snapshot,
    )


async def _chunk_guard(
    session: AsyncSession, agent: AgentContext, command_id: uuid.UUID, collection: CollectionType
) -> int:
    """Inside the chunk's transaction: the command (FOR SHARE) is still RUNNING and this Agent
    still holds a live lease (FOR UPDATE). Returns the watermark (D-039 #1)."""
    await running_command(session, agent, command_id, lock=True)
    held = await leases.lock_held(session, agent, collection, datetime.now(UTC))
    if held is None:
        raise leases.not_held(collection)
    return held.last_alter_id


def _error_row(ctx: IngestContext, failure: RecordFailure, hold: int | None) -> SyncError:
    return error_row(
        company_id=ctx.company_id,
        sync_run_id=ctx.sync_run_id,
        entity_type=ctx.entity_type,
        code=failure.code,
        message=failure.message,
        guid=failure.guid,
        alter_id=failure.alter_id,
        hold=hold,
    )


async def _record(
    session: AsyncSession, ctx: IngestContext, outcome: ChunkOutcome, pre_batch_watermark: int
) -> int:
    """Write this chunk's stale records and failures to sync_errors. Returns how many records
    were not stored (D-040 #1); only those hold the watermark (D-039 #7)."""
    for guid, stored, incoming in outcome.stale:  # SYNC-3.2: logged, never an error to retry
        session.add(
            _error_row(
                ctx,
                RecordFailure(
                    guid,
                    incoming,
                    ErrorCode.STALE_ALTERID,
                    f"incoming ALTERID {incoming} is lower than stored {stored}; ignored",
                ),
                None,
            )
        )
        log.warning(
            "stale_alterid",
            code=ErrorCode.STALE_ALTERID.value,
            collection=ctx.collection.value,
            guid=guid,
            stored_alter_id=stored,
            incoming_alter_id=incoming,
        )
    failed = 0
    for failure in outcome.failures:  # D-039 #7: held below the failure, retried next run
        hold: int | None = None
        if not_stored(failure.code) and not ctx.snapshots:  # snapshots have no watermark
            hold = failure.alter_id - 1 if failure.alter_id is not None else pre_batch_watermark
        failed += not_stored(failure.code)
        session.add(_error_row(ctx, failure, hold))
        log.warning(
            "sync_record_failed",
            code=failure.code.value,
            collection=ctx.entity_type,
            guid=failure.guid,
            alter_id=failure.alter_id,
            message=failure.message,
        )
    await session.flush()
    return failed


async def _chunk_failed(
    session: AsyncSession,
    ctx: IngestContext,
    index: int,
    size: int,
    hold: int | None,
    exc: Exception,
) -> None:
    """D-040 #5: in its own transaction after the rollback. The chunk's records are known only
    as a range, so the watermark is held where it stood before the chunk."""
    log.error("sync_chunk_failed", collection=ctx.entity_type, chunk=index, error=str(exc))
    session.add(
        _error_row(
            ctx,
            RecordFailure(
                None,
                None,
                ErrorCode.CHUNK_FAILED,
                f"chunk {index + 1} ({size} records) could not be written: {type(exc).__name__}",
            ),
            None if ctx.snapshots else hold,
        )
    )
    await session.execute(
        update(SyncRun)
        .where(SyncRun.sync_run_id == ctx.sync_run_id)
        .values(records_failed=SyncRun.records_failed + size)
        .execution_options(synchronize_session=False)
    )
    await session.commit()


async def ingest(
    session: AsyncSession, agent: AgentContext, command_id: uuid.UUID, env: BatchEnvelope
) -> BatchResult:
    if _major(env.contract_version) != _major(CONTRACT_VERSION):
        raise AppError(
            ErrorCode.VALIDATION_ERROR,
            f"Contract {env.contract_version} is not compatible with {CONTRACT_VERSION}",
            422,
        )
    replay = await _replayed(session, agent, env)
    if replay is not None:
        return replay
    unclassified = {e.code for e in env.parse_errors} - SYNC_ERROR_KIND.keys()
    if unclassified:
        raise AppError(
            ErrorCode.VALIDATION_ERROR,
            f"Parse errors with unclassified codes: {sorted(unclassified)}",
            422,
        )
    is_snapshot = env.collection_type is None
    if is_snapshot:
        if any(r.record_type != "STOCK_SNAPSHOT" for r in env.records):
            raise AppError(
                ErrorCode.VALIDATION_ERROR,
                "Without a collection only stock snapshots are accepted; balances and "
                "reconciliation totals come in P10",
                422,
            )
        collection = CollectionType.STOCK_ITEM  # snapshots ride on the item lease (D-040 #8)
        writer: Writer = snapshots.write_snapshots
    else:
        assert env.collection_type is not None
        collection = env.collection_type
        if collection not in WRITERS:
            raise AppError(
                ErrorCode.VALIDATION_ERROR, f"{collection} batches are not accepted yet", 422
            )
        writer = WRITERS[collection]

    run, _ = await open_run(session, agent, env.sync_run_id)
    if run.command_id != command_id:
        raise AppError(ErrorCode.NOT_FOUND, "Sync run not found", 404)
    pre_batch_watermark = await _chunk_guard(session, agent, command_id, collection)
    ctx = await _context(session, agent, env, collection, is_snapshot)
    await session.commit()  # nothing written; releases the checks' row locks

    windowed = isinstance(env.window, AlterIdWindow)
    size = await get_setting(session, agent.company_id, "sync.db_commit_batch")
    result = BatchResult(batch_id=env.batch_id, status="COMPLETE")
    chunks = [env.records[i : i + size] for i in range(0, len(env.records), size)] or [[]]
    for index, chunk in enumerate(chunks):
        try:
            watermark = await _chunk_guard(session, agent, command_id, collection)
            outcome = await writer(session, ctx, list(chunk))
            if index == 0:  # the Agent's parse errors: ALTERID unknown (D-039 #7)
                outcome.failures += [
                    RecordFailure(e.guid, None, e.code, e.message) for e in env.parse_errors
                ]
            failed = await _record(session, ctx, outcome, pre_batch_watermark)
            await session.execute(
                update(SyncRun)
                .where(SyncRun.sync_run_id == ctx.sync_run_id)
                .values(
                    records_fetched=SyncRun.records_fetched + len(chunk),
                    records_failed=SyncRun.records_failed + failed,
                )
                .execution_options(synchronize_session=False)
            )
            if (
                windowed and chunk and not is_snapshot
            ):  # D-039 #2: only ALTERID pages move it, per chunk
                cap = await holds.run_cap(session, ctx.sync_run_id, collection)
                watermark = await _advance(
                    session,
                    agent,
                    collection,
                    watermark,
                    max(getattr(r, "alter_id", 0) for r in chunk),  # collection records
                    cap,
                    ctx.now,
                )
            await session.commit()
        except AppError as exc:
            await session.rollback()
            return _stopped(result, exc.message)
        except Exception as exc:  # a chunk that cannot be written stops the batch (D-026)
            await session.rollback()
            held = result.watermark if result.watermark is not None else pre_batch_watermark
            await _chunk_failed(session, ctx, index, len(chunk), held, exc)
            return _stopped(result, f"chunk {index + 1} failed: {type(exc).__name__}")
        result.written += outcome.written
        result.unchanged += outcome.unchanged
        result.rejected_stale += len(outcome.stale)
        result.failed += failed
        result.chunks_committed += 1
        result.watermark = watermark
    if result.failed:
        result.status = "PARTIAL"
    if is_snapshot:  # a replay repeats the same upsert (D-040 #8)
        await session.commit()
        return result
    session.add(
        SyncBatch(
            batch_id=env.batch_id,
            company_id=agent.company_id,
            sync_run_id=env.sync_run_id,
            collection_type=collection.value,
            batch_seq=env.batch_seq,
            committed_at=datetime.now(UTC),
            accepted=result.written,
            rejected_stale=result.rejected_stale,
            error_count=result.failed,
        )
    )
    await session.commit()
    return result


def _stopped(result: BatchResult, why: str) -> BatchResult:
    result.status = "PARTIAL"
    result.error = why
    return result


async def _advance(
    session: AsyncSession,
    agent: AgentContext,
    collection: CollectionType,
    watermark: int,
    chunk_max: int,
    cap: int | None,
    now: datetime,
) -> int:
    """SYNC-1.2: in the chunk's own transaction; never past a failing record (D-039 #7)."""
    target = max(watermark, holds.capped(chunk_max, cap))
    if target == watermark:
        return watermark
    await session.execute(
        update(SyncWatermark)
        .where(
            SyncWatermark.company_id == agent.company_id,
            SyncWatermark.collection_type == collection,
            SyncWatermark.locked_by_agent_id == agent.agent_id,
        )
        .values(last_alter_id=target, last_successful_sync_at=now, status="OK")
        .execution_options(synchronize_session=False)
    )
    return target
