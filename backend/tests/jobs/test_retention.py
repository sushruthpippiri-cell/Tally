"""P16.11/P16.3: retention purges (SRS 15)."""

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.jobs.retention import purge_rate_limit_counters
from app.jobs.runner import LOCK_PURGE_RATE_LIMITS, build_scheduler
from app.models.config import RateLimitCounter
from tally_contract.testing import assert_logged

NOW = datetime(2026, 10, 6, 12, 0, tzinfo=UTC)


async def _windows(session: AsyncSession) -> set[datetime]:
    rows = await session.scalars(select(RateLimitCounter.window_start))
    return set(rows)


@pytest.mark.req("SEC-1.9")
async def test_finished_rate_limit_windows_are_purged_and_live_ones_kept(
    session: AsyncSession, caplog: pytest.LogCaptureFixture
) -> None:
    """One row per key per window, so without this the table grows by millions of rows a day."""
    minute = timedelta(seconds=60)
    current, previous, stale, ancient = NOW, NOW - minute, NOW - 2 * minute, NOW - 90 * minute
    session.add_all(
        RateLimitCounter(bucket_key=f"ip:1.2.3.{i}", window_start=start, count=7)
        for i, start in enumerate((current, previous, stale, ancient))
    )
    await session.flush()

    deleted = await purge_rate_limit_counters(session, NOW)

    # The window in progress and the one before it survive: a request arriving at a boundary may
    # still be counting into the window that just ended, and replicas' clocks are not in step.
    assert deleted == 2
    assert await _windows(session) == {current, previous}
    assert_logged(caplog, "rate_limit_counters_purged", level="info", deleted=2)


async def test_purging_an_empty_table_changes_nothing_and_logs_nothing(
    session: AsyncSession, caplog: pytest.LogCaptureFixture
) -> None:
    assert await purge_rate_limit_counters(session, NOW) == 0
    assert "rate_limit_counters_purged" not in caplog.text


async def test_the_purge_is_scheduled_under_its_own_lock() -> None:
    job = build_scheduler().get_job("purge_rate_limit_counters")
    assert job is not None
    assert job.args[0] == LOCK_PURGE_RATE_LIMITS
    assert job.args[1] is purge_rate_limit_counters
