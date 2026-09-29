"""P10.5: when reconciliation runs (REC-1.4, D-048 #6). Every trigger creates a RECONCILIATION
command; the job compares each such run once, after it ends COMPLETED or PARTIAL."""

from datetime import UTC, datetime

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.jobs.reconciliation import reconcile_runs
from app.models.agents import AgentCommand
from app.models.config import AuditLog
from app.models.enums import SyncMode, SyncRunStatus
from app.models.sync import ReconciliationRun, SyncRun
from app.services import sync_runs
from tests.factories import make_command, make_company, make_registered_agent, make_sync_run


async def _run(
    session: AsyncSession, mode: SyncMode, status: SyncRunStatus = SyncRunStatus.COMPLETED
) -> SyncRun:
    company = await make_company(session, tally_guid=f"guid-{mode}-{status}")
    agent, _ = await make_registered_agent(session, company)
    run = await make_sync_run(session, await make_command(session, agent, mode))
    run.status, run.ended_at = status, datetime.now(UTC)
    await session.flush()
    return run


async def _compared(session: AsyncSession) -> set[object]:
    return set((await session.execute(select(ReconciliationRun.sync_run_id))).scalars())


@pytest.mark.req("REC-1.4")
async def test_the_job_compares_finished_reconciliation_runs_once_and_nothing_else(
    session: AsyncSession,
) -> None:
    due = [
        await _run(session, SyncMode.RECONCILIATION),
        await _run(session, SyncMode.RECONCILIATION, SyncRunStatus.PARTIAL),
    ]
    for mode, status in (
        (SyncMode.RECONCILIATION, SyncRunStatus.IN_PROGRESS),  # not finished
        (SyncMode.RECONCILIATION, SyncRunStatus.FAILED),  # stored nothing
        (SyncMode.INCREMENTAL, SyncRunStatus.COMPLETED),
        (SyncMode.FULL, SyncRunStatus.COMPLETED),  # followed by its own RECONCILIATION run
    ):
        await _run(session, mode, status)
    assert await reconcile_runs(session, datetime.now(UTC)) == 2
    assert await _compared(session) == {r.sync_run_id for r in due}
    assert await reconcile_runs(session, datetime.now(UTC)) == 0  # once only


@pytest.mark.req_partial("REC-1.4")  # the comparison that follows: the job test above
@pytest.mark.parametrize(
    ("mode", "reported", "queued"),
    [
        (SyncMode.FULL, SyncRunStatus.COMPLETED, True),
        (SyncMode.FULL, SyncRunStatus.FAILED, False),  # nothing stored: records_fetched = 0
        (SyncMode.INCREMENTAL, SyncRunStatus.COMPLETED, False),
        (SyncMode.RECONCILIATION, SyncRunStatus.COMPLETED, False),  # never a loop
    ],
)
async def test_a_full_sync_that_stored_data_queues_a_reconciliation_on_its_agent(
    session: AsyncSession, mode: SyncMode, reported: SyncRunStatus, queued: bool
) -> None:
    run = await _run(session, mode, SyncRunStatus.IN_PROGRESS)
    await sync_runs.close_run(session, run, reported, datetime.now(UTC))
    commands = (
        (
            await session.execute(
                select(AgentCommand).where(
                    AgentCommand.agent_id == run.agent_id,
                    AgentCommand.sync_mode == SyncMode.RECONCILIATION,
                    AgentCommand.status == "PENDING",
                    AgentCommand.command_id != run.command_id,
                )
            )
        )
        .scalars()
        .all()
    )
    assert len(commands) == int(queued)
    audited = await session.scalar(
        select(func.count()).where(
            AuditLog.company_id == run.company_id, AuditLog.action == "RECONCILIATION_QUEUED"
        )
    )
    assert audited == int(queued)
