"""P1.7: sync control (SRS 5.9) and the batch dedupe table (D-024)."""

import uuid
from datetime import UTC, datetime

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.agents import Agent
from app.models.enums import CollectionType
from app.models.sync import SyncBatch, SyncError, SyncRun, SyncWatermark
from tests.factories import db_error, make_agent, make_company


async def _run(session: AsyncSession, agent: Agent) -> SyncRun:
    run = SyncRun(
        company_id=agent.company_id,
        agent_id=agent.agent_id,
        sync_mode="FULL",
        started_at=datetime.now(UTC),
        status="IN_PROGRESS",
    )
    session.add(run)
    await session.flush()
    return run


async def test_one_watermark_per_company_and_collection(session: AsyncSession) -> None:
    company = await make_company(session)
    for collection in CollectionType:
        session.add(SyncWatermark(company_id=company.company_id, collection_type=collection))
    await session.flush()
    async with db_error(session, "pk_sync_watermarks"):
        session.add(SyncWatermark(company_id=company.company_id, collection_type="VOUCHER"))
        await session.flush()


@pytest.mark.parametrize(
    ("table", "column", "value"),
    [
        ("sync_watermarks", "collection_type", "BILL"),
        ("sync_watermarks", "status", "RUNNING"),
        ("sync_runs", "status", "DONE"),
        ("sync_runs", "sync_mode", "PARTIAL"),
    ],
)
async def test_unknown_enum_values_rejected(
    session: AsyncSession, table: str, column: str, value: str
) -> None:
    agent = await make_agent(session, await make_company(session))
    await _run(session, agent)
    session.add(SyncWatermark(company_id=agent.company_id, collection_type="GROUP"))
    await session.flush()
    async with db_error(session, f"ck_{table}_{column}"):
        await session.execute(text(f"UPDATE {table} SET {column} = :v"), {"v": value})


async def test_watermark_starts_never_synced_at_zero(session: AsyncSession) -> None:
    company = await make_company(session)
    mark = SyncWatermark(company_id=company.company_id, collection_type="LEDGER")
    session.add(mark)
    await session.flush()
    await session.refresh(mark)
    assert (mark.status, mark.last_alter_id) == ("NEVER_SYNCED", 0)


@pytest.mark.req("SEC-1.7")
async def test_watermark_lock_holder_must_be_same_company_agent(session: AsyncSession) -> None:
    agent = await make_agent(session, await make_company(session))
    other = await make_company(session)
    async with db_error(session, "fk_sync_watermarks_company_id_locked_by_agent_id"):
        session.add(
            SyncWatermark(
                company_id=other.company_id,
                collection_type="VOUCHER",
                locked_by_agent_id=agent.agent_id,
            )
        )
        await session.flush()


async def test_replayed_batch_id_is_rejected(session: AsyncSession) -> None:
    """D-024: the batch_id is the key a replay is detected by."""
    agent = await make_agent(session, await make_company(session))
    run = await _run(session, agent)
    batch_id = uuid.uuid4()

    def batch() -> SyncBatch:
        return SyncBatch(
            batch_id=batch_id,
            company_id=agent.company_id,
            sync_run_id=run.sync_run_id,
            collection_type="VOUCHER",
            batch_seq=1,
            committed_at=datetime.now(UTC),
            accepted=10,
            rejected_stale=0,
            error_count=0,
        )

    session.add(batch())
    await session.flush()
    session.expunge_all()
    async with db_error(session, "pk_sync_batches"):
        session.add(batch())
        await session.flush()


@pytest.mark.req("SEC-1.7")
async def test_sync_error_belongs_to_a_run_of_the_same_company(session: AsyncSession) -> None:
    run = await _run(session, await make_agent(session, await make_company(session)))
    other = await make_company(session)
    session.add(
        SyncError(
            company_id=run.company_id,
            sync_run_id=run.sync_run_id,
            entity_type="VOUCHER",
            tally_guid="g",
            error_code="STALE_ALTERID",
            message="older alter id",
        )
    )
    await session.flush()
    async with db_error(session, "fk_sync_errors_company_id_sync_run_id"):
        session.add(
            SyncError(
                company_id=other.company_id,
                sync_run_id=run.sync_run_id,
                entity_type="VOUCHER",
                error_code="STALE_ALTERID",
                message="x",
            )
        )
        await session.flush()


async def test_reconciliation_result_is_pass_or_fail(session: AsyncSession) -> None:
    company = await make_company(session)
    async with db_error(session, "ck_reconciliation_results_result"):
        await session.execute(
            text(
                "INSERT INTO reconciliation_results (company_id, run_at, metric, period_start, "
                "period_end, tally_value, local_value, absolute_difference, result) VALUES "
                "(:c, now(), 'SALES_CREDITS', '2024-04-01', '2025-03-31', 1, 1, 0, 'OK')"
            ),
            {"c": company.company_id},
        )
