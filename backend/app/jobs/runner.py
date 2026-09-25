"""Background jobs (APScheduler, D-035 #8). Each run takes a PostgreSQL advisory lock, so with
several backend replicas only one runs a job at a time and nothing is done twice (D-017)."""

from collections.abc import Awaitable, Callable
from datetime import UTC, datetime

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.db import session_factory
from tally_contract.log import get_logger

log = get_logger(__name__)

Job = Callable[[AsyncSession, datetime], Awaitable[int]]

# One advisory-lock key per job; any fixed, distinct 64-bit numbers.
LOCK_MARK_OFFLINE = 3_001


async def run_exclusive(
    lock_key: int,
    job: Job,
    factory: async_sessionmaker[AsyncSession] | None = None,
) -> int | None:
    """Run `job` in one transaction holding the lock; None if another run holds it."""
    async with (factory or session_factory())() as session, session.begin():
        if not await session.scalar(select(func.pg_try_advisory_xact_lock(lock_key))):
            log.info("job_skipped_locked", job=job.__name__, lock_key=lock_key)
            return None
        changed = await job(session, datetime.now(UTC))
        log.info("job_ran", job=job.__name__, changed=changed)
        return changed


def build_scheduler() -> AsyncIOScheduler:
    from app.jobs.agents import mark_offline

    scheduler = AsyncIOScheduler(timezone=UTC)
    scheduler.add_job(
        run_exclusive,
        "interval",
        seconds=60,
        args=[LOCK_MARK_OFFLINE, mark_offline],
        id="mark_offline",
        max_instances=1,
        coalesce=True,
    )
    return scheduler
