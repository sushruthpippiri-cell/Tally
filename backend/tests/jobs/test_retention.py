"""P16.11/P16.3: retention purges (SRS 15)."""

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.jobs.retention import purge_logs, purge_rate_limit_counters
from app.jobs.runner import LOCK_PURGE_LOGS, LOCK_PURGE_RATE_LIMITS, build_scheduler
from app.models.config import AiToolLog, AuditLog, RateLimitCounter
from app.models.enums import ToolCallStatus
from app.models.sync import SyncError, SyncRun
from tally_contract.testing import assert_logged
from tests.factories import make_command, make_company, make_registered_agent, make_sync_run

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


# --- the sync and AI tool logs (SRS 15, D-056 #4) --------------------------------------


async def _run(session: AsyncSession, started: datetime) -> SyncRun:
    company = await make_company(session)
    agent, _ = await make_registered_agent(session, company)
    run = await make_sync_run(session, await make_command(session, agent))
    run.started_at = started
    await session.flush()
    return run


def _error(run: SyncRun, created: datetime, hold: int | None = None) -> SyncError:
    return SyncError(
        company_id=run.company_id,
        sync_run_id=run.sync_run_id,
        entity_type="LEDGER",
        watermark_hold=hold,
        error_code="PARSE_ERROR",
        message="bad record",
        created_at=created,
    )


OLD = NOW - timedelta(days=200)  # past the 180-day default
RECENT = NOW - timedelta(days=10)


@pytest.mark.req("LOG-1.1")
async def test_sync_and_ai_logs_older_than_the_retention_period_go(
    session: AsyncSession, caplog: pytest.LogCaptureFixture
) -> None:
    old_run, recent_run = await _run(session, OLD), await _run(session, RECENT)
    session.add_all(
        [
            _error(old_run, OLD),
            _error(recent_run, RECENT),
            AiToolLog(
                company_id=old_run.company_id,
                tool_name="get_anomaly_evidence",
                status=ToolCallStatus.SUCCESS,
                created_at=OLD,
            ),
            AiToolLog(
                company_id=recent_run.company_id,
                tool_name="get_anomaly_evidence",
                status=ToolCallStatus.SUCCESS,
                created_at=RECENT,
            ),
        ]
    )
    await session.flush()

    assert await purge_logs(session, NOW) == 3  # one error, one run, one tool call

    assert set(await session.scalars(select(SyncRun.sync_run_id))) == {recent_run.sync_run_id}
    assert (await session.scalars(select(SyncError.id))).all() != []
    assert len((await session.scalars(select(AiToolLog.id))).all()) == 1
    assert_logged(caplog, "rows_purged", level="info", table="sync_runs", deleted=1)


@pytest.mark.req("LOG-1.1")
async def test_an_error_still_holding_a_watermark_back_is_never_purged(
    session: AsyncSession,
) -> None:
    """D-039 #7: the watermark may not pass a record that never landed. Deleting the error that
    holds it would let the next run skip that record for good - data loss, not housekeeping."""
    run = await _run(session, OLD)
    session.add_all([_error(run, OLD, hold=4_200), _error(run, OLD)])
    await session.flush()

    assert await purge_logs(session, NOW) == 1  # only the error that holds nothing

    held = (await session.scalars(select(SyncError.watermark_hold))).all()
    assert held == [4_200]
    # And its run survives too, because sync_errors points at it.
    assert (await session.scalars(select(SyncRun.sync_run_id))).all() == [run.sync_run_id]


@pytest.mark.req("SEC-1.13")
async def test_the_purge_never_touches_audit_logs(session: AsyncSession) -> None:
    """SRS 15 keeps the audit log as long as the company's data; SEC-1.13 makes it append-only.
    A trigger would refuse the delete anyway - this proves the job does not try."""
    company = await make_company(session)
    session.add(
        AuditLog(
            company_id=company.company_id,
            user_id=None,
            action="LOGIN",
            entity_type="user",
            result="SUCCESS",
            created_at=OLD,
        )
    )
    await session.flush()

    await purge_logs(session, NOW)

    assert len((await session.scalars(select(AuditLog.id))).all()) == 1
    source = Path(purge_logs.__globals__["__file__"]).read_text(encoding="utf-8")
    assert "AuditLog" not in source


async def test_nothing_is_purged_before_the_retention_period(session: AsyncSession) -> None:
    run = await _run(session, RECENT)
    session.add(_error(run, RECENT))
    await session.flush()
    assert await purge_logs(session, NOW) == 0


def test_the_log_purge_runs_daily_under_its_own_lock() -> None:
    job = build_scheduler().get_job("purge_logs")
    assert job is not None
    assert job.args[0] == LOCK_PURGE_LOGS
    assert job.args[1] is purge_logs
    assert job.trigger.__class__.__name__ == "CronTrigger"  # days, not minutes
