"""Compare each finished RECONCILIATION run (REC-1.4, D-048 #6).

Every trigger (the daily schedule, a FULL sync ending, `POST .../reconciliation/run`) creates a
RECONCILIATION command, so this is the one place comparisons happen. A run is compared once,
when it has ended COMPLETED or PARTIAL; its `reconciliation_runs` row marks it done.
"""

from datetime import datetime

from sqlalchemy import exists, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.enums import SyncMode, SyncRunStatus
from app.models.sync import ReconciliationRun, SyncRun
from app.reconciliation.compare import reconcile_run


async def reconcile_runs(session: AsyncSession, now: datetime) -> int:
    runs = await session.execute(
        select(SyncRun)
        .where(
            SyncRun.sync_mode == SyncMode.RECONCILIATION,
            SyncRun.status.in_([SyncRunStatus.COMPLETED, SyncRunStatus.PARTIAL]),
            ~exists().where(ReconciliationRun.sync_run_id == SyncRun.sync_run_id),
        )
        .order_by(SyncRun.ended_at)
    )
    done = 0
    for run in runs.scalars().all():  # ponytail: one transaction for all; they are daily
        await reconcile_run(session, run, now)
        done += 1
    return done
