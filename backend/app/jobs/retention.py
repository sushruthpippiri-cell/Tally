"""Retention jobs: delete rows nothing needs any more (SRS 15, P16.3/P16.11).

`audit_logs` is never purged here. It is append-only (SEC-1.13): a trigger rejects DELETE for
everyone and the app role has no DELETE on it, and SRS 15 keeps it for as long as the company's
data is kept.
"""

from datetime import datetime, timedelta

from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.rate_limit import window_start
from app.models.config import RateLimitCounter
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
