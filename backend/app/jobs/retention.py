"""Retention jobs: delete rows nothing needs any more (SRS 15, P16.3/P16.11).

`audit_logs` is never purged here. It is append-only (SEC-1.13): a trigger rejects DELETE for
everyone and the app role has no DELETE on it, and SRS 15 keeps it for as long as the company's
data is kept.
"""

from datetime import datetime, timedelta

from sqlalchemy import Delete, delete, exists, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.rate_limit import window_start
from app.models.config import AiToolLog, RateLimitCounter
from app.models.sync import SyncError, SyncRun
from tally_contract.log import get_logger

log = get_logger(__name__)

# Keep the current window and the one before it: a request arriving at a boundary may still be
# counting into the window that just ended, and replicas' clocks are not exactly in step.
_KEEP_WINDOWS = 2


async def purge_rate_limit_counters(session: AsyncSession, now: datetime) -> int:
    """Delete finished rate-limit windows (P16.11).

    One row per key per window, so under real traffic this grows by millions of rows a day and
    the table would be nothing but dead tuples; the index on window_start makes the delete cheap.
    """
    seconds = get_settings().rate_limit_window_seconds
    # Align to the window boundary first: `now` sits somewhere inside the current window, so
    # subtracting from it would otherwise delete part of the window we mean to keep.
    cutoff = window_start(now.timestamp(), seconds) - (_KEEP_WINDOWS - 1) * timedelta(
        seconds=seconds
    )
    result = await session.execute(
        delete(RateLimitCounter).where(RateLimitCounter.window_start < cutoff)
    )
    deleted = int(result.rowcount)  # type: ignore[attr-defined]
    if deleted:
        log.info("rate_limit_counters_purged", deleted=deleted, cutoff=cutoff.isoformat())
    return deleted


async def _deleted(session: AsyncSession, statement: Delete, table: str) -> int:
    result = await session.execute(statement)
    count = int(result.rowcount)  # type: ignore[attr-defined]
    if count:
        log.info("rows_purged", table=table, deleted=count)
    return count


async def purge_logs(session: AsyncSession, now: datetime) -> int:
    """Delete sync and AI tool log rows past `log_retention_days` (SRS 15, D-056 #4).

    SRS 15 asks for at least 90 days on all three; the configured default is 180. `audit_logs`
    is not touched - it is kept for as long as the company's data is, and the app role could
    not delete from it anyway (SEC-1.13).
    """
    cutoff = now - timedelta(days=get_settings().log_retention_days)
    deleted = 0

    # A sync error that still holds a watermark back (D-039 #7) must outlive its retention
    # period: deleting it would let the watermark advance past a record that never landed, so
    # the record would never be fetched again. That is silent data loss dressed as tidying up.
    deleted += await _deleted(
        session,
        delete(SyncError).where(SyncError.created_at < cutoff, SyncError.watermark_hold.is_(None)),
        "sync_errors",
    )

    # sync_errors has a composite FK to sync_runs with no cascade, so a run goes only once
    # nothing references it - which also keeps the run that owns a held-back error.
    deleted += await _deleted(
        session,
        delete(SyncRun).where(
            SyncRun.started_at < cutoff,
            ~exists(
                select(SyncError.id).where(
                    SyncError.sync_run_id == SyncRun.sync_run_id,
                    SyncError.company_id == SyncRun.company_id,
                )
            ),
        ),
        "sync_runs",
    )

    deleted += await _deleted(
        session, delete(AiToolLog).where(AiToolLog.created_at < cutoff), "ai_tool_log"
    )
    return deleted
