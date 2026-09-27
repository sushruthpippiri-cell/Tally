"""P5.7: how a sync run ends (SYNC-6.4, SYNC-6.6, AC-05, D-040 #1-5) on committing
connections."""

import asyncio
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from sqlalchemy import select, text, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.jobs import commands as command_jobs
from app.models.agents import AgentCommand, SyncSchedule
from app.models.enums import CollectionType as C
from app.models.enums import CommandStatus
from app.models.masters import CostCentre
from app.models.sync import SyncError, SyncRun, SyncWatermark
from app.schemas.commands import ResultRequest
from app.schemas.sync import FinishRequest, RunProblem
from app.services import commands
from app.services.sync_runs import finish_run, initial_sync_incomplete
from app.sync import ingest as ingest_module
from app.sync.ingest import BatchResult
from tally_contract.errors import ErrorCode
from tally_contract.records import AlterIdWindow, CostCentreRecord, ParseError
from tally_contract.testing import assert_logged
from tests.sync.helpers import Factory, Setup, count, envelope, lease, setup, upload, watermark


def cc(n: int, alter: int | None = None) -> CostCentreRecord:
    return CostCentreRecord(guid=f"cc-{n}", alter_id=alter or n, name=f"CC {n}")


async def _finish(
    committed: Factory, st: Setup, status: str, problems: list[dict[str, Any]] | None = None
) -> str:
    body = FinishRequest(
        status=status,  # type: ignore[arg-type]
        problems=[RunProblem.model_validate(p) for p in problems or []],
    )
    async with committed() as s:
        out = await finish_run(s, st.agent, st.command_id, st.run_id, body)
    return out.status.value


async def _run(committed: Factory, st: Setup) -> SyncRun:
    async with committed() as s:
        run = await s.get(SyncRun, st.run_id)
        assert run is not None
        return run


async def _cc(committed: Factory, st: Setup, records: list[Any], **kw: Any) -> BatchResult:
    result = await upload(committed, st, envelope(st, C.COST_CENTRE, records, **kw))
    assert isinstance(result, BatchResult), result
    return result


@pytest.mark.req("AC-05", "SYNC-6.4")
async def test_a_run_failing_part_way_is_partial_and_the_next_resumes_without_duplicates(
    committed: Factory, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    st = await setup(committed, chunk_size=2)
    await lease(committed, st, C.COST_CENTRE)
    real = ingest_module.WRITERS[C.COST_CENTRE]
    calls = 0

    async def third_chunk_fails(session: AsyncSession, ctx: Any, chunk: list[Any]) -> Any:
        nonlocal calls
        calls += 1
        if calls == 3:
            raise RuntimeError("disk full")
        return await real(session, ctx, chunk)

    monkeypatch.setitem(ingest_module.WRITERS, C.COST_CENTRE, third_chunk_fails)
    result = await _cc(committed, st, [cc(n) for n in range(1, 11)])
    assert (result.status, result.chunks_committed) == ("PARTIAL", 2)
    assert await count(committed, CostCentre, st.company_id) == 4  # committed chunks remain
    assert await watermark(committed, st.company_id, C.COST_CENTRE) == 4  # the last one's max
    assert_logged(caplog, "sync_chunk_failed", level="error", chunk=2)
    async with committed() as s:
        error = (await s.execute(select(SyncError))).scalar_one()
    assert (error.error_code, error.watermark_hold) == ("CHUNK_FAILED", 4)

    # A later batch in the same run is stored but cannot move the watermark past the hole.
    monkeypatch.setitem(ingest_module.WRITERS, C.COST_CENTRE, real)
    window = AlterIdWindow(from_alter_id=6, to_alter_id=10)
    later = await _cc(committed, st, [cc(n) for n in range(7, 11)], window=window)
    assert later.written == 4
    assert await watermark(committed, st.company_id, C.COST_CENTRE) == 4
    assert await _finish(committed, st, "FAILED") == "PARTIAL"

    # The next run resumes from the watermark: nothing lost, nothing duplicated.
    nxt = await setup(committed, company_id=st.company_id, name="run 2")
    await lease(committed, nxt, C.COST_CENTRE)
    window = AlterIdWindow(from_alter_id=4, to_alter_id=10)
    resumed = await _cc(committed, nxt, [cc(n) for n in range(5, 11)], window=window)
    assert (resumed.written, resumed.unchanged) == (2, 4)
    assert await count(committed, CostCentre, st.company_id) == 10
    assert await watermark(committed, st.company_id, C.COST_CENTRE) == 10
    assert await _finish(committed, nxt, "COMPLETED") == "COMPLETED"


@pytest.mark.req("SYNC-6.6")
async def test_tally_unreachable_fails_the_run_and_changes_nothing(committed: Factory) -> None:
    st = await setup(committed)  # a FULL command
    async with committed() as s:
        s.add(
            SyncSchedule(
                company_id=st.company_id,
                agent_id=st.agent.agent_id,
                cron_expression="0 * * * *",
                sync_mode="INCREMENTAL",
                is_active=False,
            )
        )
        await s.commit()
    await lease(committed, st, C.VOUCHER)
    tables = ["groups", "ledgers", "vouchers", "voucher_entries", "stock_snapshots"]

    async def state() -> list[Any]:
        async with committed() as s:
            counts = [await s.scalar(text(f"SELECT count(*) FROM {t}")) for t in tables]
            marks = (await s.execute(select(SyncWatermark.last_alter_id))).scalars().all()
            return [counts, list(marks)]

    before = await state()
    problem = {"code": "TALLY_UNREACHABLE", "message": "connection refused on localhost:9000"}
    assert await _finish(committed, st, "FAILED", [problem]) == "FAILED"
    assert await state() == before
    async with committed() as s:
        assert await s.scalar(select(SyncWatermark.locked_by_agent_id)) is None  # released
        assert await s.scalar(select(SyncSchedule.is_active)) is False  # a FAILED full: off


@pytest.mark.parametrize("code", ["SYNC_LOCKED", "TALLY_EXPORT_TIMEOUT"])
async def test_a_skipped_collection_or_segment_makes_a_completed_run_partial(
    committed: Factory, code: str
) -> None:
    st = await setup(committed)
    problem = {"collection_type": "VOUCHER", "code": code, "message": "not synced"}
    assert await _finish(committed, st, "COMPLETED", [problem]) == "PARTIAL"
    async with committed() as s:
        error = (await s.execute(select(SyncError))).scalar_one()
    assert (error.entity_type, error.error_code, error.watermark_hold) == ("VOUCHER", code, None)


async def test_informational_errors_leave_the_run_completed(committed: Factory) -> None:
    """Owner test (D-040 #1): a stale record and a mapped field missing from Tally (DR-UDF-3,
    logged on every run) do not make the run PARTIAL."""
    st = await setup(committed)
    await lease(committed, st, C.COST_CENTRE)
    await _cc(committed, st, [cc(1, alter=5)])
    stale = await _cc(committed, st, [cc(1, alter=3)])
    missing_udf = ParseError(
        guid="cc-2", code=ErrorCode.UDF_NOT_FOUND, message="UDF_REGION not in the export"
    )
    udf = await _cc(committed, st, [cc(2)], parse_errors=[missing_udf])
    assert (stale.rejected_stale, udf.failed, udf.status) == (1, 0, "COMPLETE")
    assert await _finish(committed, st, "COMPLETED") == "COMPLETED"
    assert (await _run(committed, st)).records_failed == 0
    async with committed() as s:
        codes = set((await s.execute(select(SyncError.error_code))).scalars())
        assert codes == {"STALE_ALTERID", "UDF_NOT_FOUND"}
        assert await initial_sync_incomplete(s, st.company_id) is False


@pytest.mark.parametrize("committed_first", [True, False])
async def test_a_failed_run_is_partial_only_if_it_stored_something(
    committed: Factory, committed_first: bool
) -> None:
    st = await setup(committed)
    if committed_first:
        await lease(committed, st, C.COST_CENTRE)
        await _cc(committed, st, [cc(1)])
    expected = "PARTIAL" if committed_first else "FAILED"
    assert await _finish(committed, st, "FAILED") == expected
    async with committed() as s:
        assert await initial_sync_incomplete(s, st.company_id) is True


async def test_the_command_result_closes_runs_left_open(committed: Factory) -> None:
    st = await setup(committed)
    await lease(committed, st, C.COST_CENTRE)
    await _cc(committed, st, [cc(1)])
    async with committed() as s:
        await commands.result(
            s, st.agent, st.command_id, ResultRequest(status=CommandStatus.COMPLETED)
        )
    run = await _run(committed, st)
    assert (run.status, run.ended_at is not None) == ("COMPLETED", True)


async def test_a_command_lost_mid_batch_closes_its_run_and_frees_its_leases(
    committed: Factory, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Owner item 2 on real connections: the lost job waits for the chunk in flight, closes
    the run (PARTIAL: a chunk had committed, AC-05), records AGENT_LOST and releases the
    leases; the standby can take the collection at once, and the lost Agent's next batch is
    refused and writes nothing."""
    st = await setup(committed, chunk_size=1)
    standby = await setup(committed, company_id=st.company_id, name="Standby")
    later = datetime.now(UTC) + timedelta(hours=1)
    async with committed() as s:  # only the first Agent's command lease lapses
        await s.execute(
            update(AgentCommand)
            .where(AgentCommand.command_id == standby.command_id)
            .values(lease_expires_at=later + timedelta(days=1))
        )
        await s.commit()
    await lease(committed, st, C.COST_CENTRE)
    real = ingest_module.WRITERS[C.COST_CENTRE]
    job: list[asyncio.Task[int]] = []

    async def lost_job() -> int:
        async with committed() as s:
            n = await command_jobs.mark_lost(s, later)
            await s.commit()
            return n

    async def first_chunk_then_lost(session: AsyncSession, ctx: Any, chunk: list[Any]) -> Any:
        if not job:
            job.append(asyncio.create_task(lost_job()))
            await asyncio.sleep(0.3)
            assert not job[0].done(), "the lost job must wait for the chunk in flight"
        return await real(session, ctx, chunk)

    monkeypatch.setitem(ingest_module.WRITERS, C.COST_CENTRE, first_chunk_then_lost)
    result = await _cc(committed, st, [cc(n) for n in range(1, 4)])
    assert await job[0] == 1
    assert result.chunks_committed == 1
    run = await _run(committed, st)
    assert run.status == "PARTIAL"
    async with committed() as s:
        error = (await s.execute(select(SyncError))).scalar_one()
        assert (error.entity_type, error.error_code) == ("RUN", "AGENT_LOST")
        assert await s.scalar(select(SyncWatermark.locked_by_agent_id)) is None

    await lease(committed, standby, C.COST_CENTRE)  # free at once, no waiting for expiry
    monkeypatch.setitem(ingest_module.WRITERS, C.COST_CENTRE, real)
    late = await upload(committed, st, envelope(st, C.COST_CENTRE, [cc(9)]))
    assert late == "INVALID_COMMAND_STATE"
    assert await count(committed, CostCentre, st.company_id) == 1
