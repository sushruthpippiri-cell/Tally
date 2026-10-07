"""Background jobs (APScheduler, D-035 #8). Each run takes a PostgreSQL advisory lock, so with
several backend replicas only one runs a job at a time and nothing is done twice (D-017)."""

from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from typing import Any

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from structlog.contextvars import bound_contextvars

from app.core.db import session_factory
from tally_contract.log import get_logger

log = get_logger(__name__)

Job = Callable[[AsyncSession, datetime], Awaitable[int]]

# One advisory-lock key per job; any fixed, distinct 64-bit numbers.
LOCK_MARK_OFFLINE = 3_001
LOCK_COMMAND_TIMEOUTS = 3_002
LOCK_FIRE_SCHEDULES = 3_003
LOCK_RECONCILE_RUNS = 3_004
LOCK_ANOMALY_RULES = 3_005
LOCK_ANOMALY_EXPLANATIONS = 3_006
LOCK_PURGE_RATE_LIMITS = 3_007
LOCK_PURGE_LOGS = 3_008


async def run_exclusive(
    lock_key: int,
    job: Job,
    factory: async_sessionmaker[AsyncSession] | None = None,
) -> int | None:
    """Run `job` in one transaction holding the lock; None if another run holds it."""
    # A job has no request and so no request_id; its name is what ties its records together
    # (P16.3). Anything the job logs, including per-company lines, carries it.
    with bound_contextvars(job=job.__name__):
        async with (factory or session_factory())() as session, session.begin():
            if not await session.scalar(select(func.pg_try_advisory_xact_lock(lock_key))):
                log.info("job_skipped_locked", lock_key=lock_key)
                return None
            changed = await job(session, datetime.now(UTC))
            log.info("job_ran", changed=changed)
            return changed


def build_scheduler() -> AsyncIOScheduler:
    from app.jobs.agents import mark_offline
    from app.jobs.anomaly import anomaly_explanations, anomaly_rules
    from app.jobs.commands import command_timeouts
    from app.jobs.reconciliation import reconcile_runs
    from app.jobs.retention import purge_logs, purge_rate_limit_counters
    from app.jobs.schedules import fire_schedules

    minutely: dict[str, Any] = {"trigger": "interval", "seconds": 60}
    # Retention is about days, so once a day is enough; 03:10 UTC keeps it away from the
    # start-of-day scheduled syncs. Only one replica runs it - the advisory lock sees to that.
    daily: dict[str, Any] = {"trigger": "cron", "hour": 3, "minute": 10}

    scheduler = AsyncIOScheduler(timezone=UTC)
    for job_id, lock, job, trigger in (
        ("mark_offline", LOCK_MARK_OFFLINE, mark_offline, minutely),
        ("command_timeouts", LOCK_COMMAND_TIMEOUTS, command_timeouts, minutely),
        ("fire_schedules", LOCK_FIRE_SCHEDULES, fire_schedules, minutely),
        ("reconcile_runs", LOCK_RECONCILE_RUNS, reconcile_runs, minutely),
        ("anomaly_rules", LOCK_ANOMALY_RULES, anomaly_rules, minutely),
        ("anomaly_explanations", LOCK_ANOMALY_EXPLANATIONS, anomaly_explanations, minutely),
        # Deletes only windows already finished, so a small batch each minute - kinder to
        # vacuum than one large delete, and the table never carries more than a few windows.
        ("purge_rate_limit_counters", LOCK_PURGE_RATE_LIMITS, purge_rate_limit_counters, minutely),
        ("purge_logs", LOCK_PURGE_LOGS, purge_logs, daily),
    ):
        scheduler.add_job(
            run_exclusive,
            args=[lock, job],
            id=job_id,
            max_instances=1,
            coalesce=True,
            **trigger,
        )
    return scheduler
