"""P5.2/P5.3: the ingest pipeline and master upserts, on committing connections
(SYNC-1.2, SYNC-3.x, SYNC-6.1/6.3/6.5, D-039)."""

import asyncio
from datetime import date
from typing import Any

import pytest
from sqlalchemy import select, text, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.agents import AgentCommand
from app.models.balances import LedgerOpeningBalance, OpeningBillAllocation
from app.models.company import Company
from app.models.enums import CollectionType as C
from app.models.masters import CostCentre, Group, Ledger, StockItem, VoucherType
from app.models.sync import SyncError, SyncWatermark
from app.sync import ingest as ingest_module
from app.sync.ingest import BatchResult
from tally_contract import normalize
from tally_contract.records import (
    CompanyRecord,
    CostCentreRecord,
    GroupRecord,
    LedgerRecord,
    OpeningBill,
    StockItemRecord,
    VoucherTypeRecord,
)
from tally_contract.testing import assert_logged
from tests.sync.helpers import GUID, Factory, count, envelope, lease, setup, upload, watermark


def group(guid: str, alter: int, name: str, parent: str | None = None, **kw: Any) -> GroupRecord:
    return GroupRecord(
        guid=guid, alter_id=alter, name=name, parent_guid=parent, parent_name=None, **kw
    )


def ledger(guid: str, alter: int, name: str, parent: str = "g-sd", **kw: Any) -> LedgerRecord:
    return LedgerRecord(
        guid=guid,
        alter_id=alter,
        name=name,
        parent_group_guid=parent,
        parent_group_name="Sundry Debtors",
        **kw,
    )


async def test_the_company_batch_stores_books_beginning_and_refuses_another_company(
    committed: Factory,
) -> None:
    st = await setup(committed, books_from=None, guid=GUID)
    await lease(committed, st, C.COMPANY)
    ok = CompanyRecord(guid=GUID, alter_id=1, name="Test Co", books_from=date(2023, 4, 1))
    result = await upload(committed, st, envelope(st, C.COMPANY, [ok]))
    assert isinstance(result, BatchResult) and result.written == 1
    other = CompanyRecord(guid="guid-some-other-company", alter_id=2, name="Other")
    refused = await upload(committed, st, envelope(st, C.COMPANY, [other]))
    assert isinstance(refused, BatchResult) and refused.failed == 1
    async with committed() as s:
        company = await s.get(Company, st.company_id)
        assert company is not None and company.books_from == date(2023, 4, 1)
        error = await s.scalar(
            select(SyncError.error_code).where(SyncError.entity_type == "COMPANY")
        )
        assert error == "COMPANY_MISMATCH"


async def test_ledgers_wait_for_the_books_beginning_date(committed: Factory) -> None:
    st = await setup(committed, books_from=None)
    await lease(committed, st, C.LEDGER)
    refused = await upload(committed, st, envelope(st, C.LEDGER, [ledger("l-1", 1, "Cash")]))
    assert refused == "INVALID_COMMAND_STATE"
    assert await count(committed, Ledger, st.company_id) == 0


@pytest.mark.req("SYNC-3.1")
@pytest.mark.req_partial("SYNC-3.2", "SYNC-3.3", "SYNC-3.4", "SYNC-3.5")  # vouchers: P5.4
@pytest.mark.parametrize(
    ("collection", "model", "make"),
    [
        (C.GROUP, Group, lambda a, n: group("m-1", a, n)),
        (C.LEDGER, Ledger, lambda a, n: ledger("m-1", a, n)),
        (
            C.VOUCHER_TYPE,
            VoucherType,
            lambda a, n: VoucherTypeRecord(guid="m-1", alter_id=a, name=n),
        ),
        (C.STOCK_ITEM, StockItem, lambda a, n: StockItemRecord(guid="m-1", alter_id=a, name=n)),
        (C.COST_CENTRE, CostCentre, lambda a, n: CostCentreRecord(guid="m-1", alter_id=a, name=n)),
    ],
)
async def test_stale_equal_and_higher_alter_ids_for_every_master(
    committed: Factory, caplog: pytest.LogCaptureFixture, collection: C, model: Any, make: Any
) -> None:
    st = await setup(committed)
    await lease(committed, st, collection)
    await upload(committed, st, envelope(st, collection, [make(108, "Original")]))
    stale = await upload(committed, st, envelope(st, collection, [make(106, "Older")]))
    equal = await upload(committed, st, envelope(st, collection, [make(108, "Same ALTERID")]))
    assert isinstance(stale, BatchResult) and stale.rejected_stale == 1 and stale.failed == 0
    assert isinstance(equal, BatchResult) and equal.unchanged == 1 and equal.rejected_stale == 0
    assert_logged(
        caplog, "stale_alterid", level="warning", stored_alter_id=108, incoming_alter_id=106
    )
    async with committed() as s:
        row = (await s.execute(select(model.name, model.alter_id))).one()
        assert tuple(row) == ("Original", 108)
        codes = (await s.execute(select(SyncError.error_code))).scalars().all()
        assert codes == ["STALE_ALTERID"]  # equal is not an error
    higher = await upload(committed, st, envelope(st, collection, [make(110, "Renamed")]))
    assert isinstance(higher, BatchResult) and higher.written == 1
    async with committed() as s:
        assert tuple((await s.execute(select(model.name, model.alter_id))).one()) == (
            "Renamed",
            110,
        )


async def test_openings_are_stored_as_at_books_beginning_and_replaced(committed: Factory) -> None:
    st = await setup(committed, books_from=date(2022, 4, 1))
    await lease(committed, st, C.LEDGER)
    first = ledger(
        "l-gupta",
        5,
        "Gupta Stores",
        opening_balance=normalize.to_amount("-15000.00"),
        opening_bills=[
            OpeningBill(
                reference_name="OB-1",
                bill_date=date(2022, 3, 31),
                amount=normalize.to_amount("-15000.00"),
            )
        ],
    )
    await upload(committed, st, envelope(st, C.LEDGER, [first]))
    async with committed() as s:
        opening = (await s.execute(select(LedgerOpeningBalance))).scalar_one()
        assert (
            opening.financial_year_start,
            opening.amount_absolute,
            opening.accounting_direction,
        ) == (date(2022, 4, 1), 15000, "DEBIT")  # D-039 #5: books-beginning, not the current FY
        assert (await s.execute(select(OpeningBillAllocation.reference_name))).scalars().all() == [
            "OB-1"
        ]
    changed = ledger("l-gupta", 9, "Gupta Stores", opening_balance=None)
    await upload(committed, st, envelope(st, C.LEDGER, [changed]))
    async with committed() as s:
        assert (await s.execute(select(LedgerOpeningBalance))).scalars().all() == []
        assert (await s.execute(select(OpeningBillAllocation))).scalars().all() == []


async def test_parents_are_linked_whenever_they_arrive(committed: Factory) -> None:
    st = await setup(committed)
    await lease(committed, st, C.GROUP)
    await upload(committed, st, envelope(st, C.GROUP, [group("g-child", 3, "Retail", "g-sd")]))
    await upload(committed, st, envelope(st, C.GROUP, [group("g-sd", 7, "Sundry Debtors")]))
    async with committed() as s:
        child = (await s.execute(select(Group).where(Group.tally_guid == "g-child"))).scalar_one()
        parent = (await s.execute(select(Group).where(Group.tally_guid == "g-sd"))).scalar_one()
        assert child.parent_group_id == parent.group_id
        assert (parent.is_predefined, parent.reserved_name) == (
            True,
            "Sundry Debtors",
        )  # G32 fallback
        assert child.resolution_status == "UNRESOLVED_GROUP"  # P6 resolves (D-039 #4)


@pytest.mark.req_partial("SYNC-6.3")  # vouchers replayed: P5.4
async def test_a_replayed_batch_returns_the_stored_result_and_changes_nothing(
    committed: Factory,
) -> None:
    st = await setup(committed)
    await lease(committed, st, C.COST_CENTRE)
    env = envelope(st, C.COST_CENTRE, [CostCentreRecord(guid="cc-1", alter_id=4, name="Retail")])
    first = await upload(committed, st, env)
    again = await upload(committed, st, env)
    assert isinstance(first, BatchResult) and isinstance(again, BatchResult)
    assert again.replayed and again.written == first.written == 1
    assert await count(committed, CostCentre, st.company_id) == 1


@pytest.mark.req("SYNC-6.1", "SYNC-1.2")
async def test_chunks_commit_separately_and_the_batch_stops_at_the_first_failed_chunk(
    committed: Factory, monkeypatch: pytest.MonkeyPatch
) -> None:
    st = await setup(committed, chunk_size=2)
    await lease(committed, st, C.COST_CENTRE)
    records = [CostCentreRecord(guid=f"cc-{i}", alter_id=i, name=f"CC {i}") for i in range(1, 6)]
    real = ingest_module.WRITERS[C.COST_CENTRE]
    calls = 0

    async def failing_second_chunk(session: AsyncSession, ctx: Any, chunk: list[Any]) -> Any:
        nonlocal calls
        calls += 1
        if calls == 2:
            raise RuntimeError("database went away")
        return await real(session, ctx, chunk)

    monkeypatch.setitem(ingest_module.WRITERS, C.COST_CENTRE, failing_second_chunk)
    result = await upload(committed, st, envelope(st, C.COST_CENTRE, records))
    assert isinstance(result, BatchResult)
    assert (result.status, result.chunks_committed, result.written) == ("PARTIAL", 1, 2)
    assert await count(committed, CostCentre, st.company_id) == 2  # chunk 1 only
    assert await watermark(committed, st.company_id, C.COST_CENTRE) == 2  # chunk 1's max
    monkeypatch.setitem(ingest_module.WRITERS, C.COST_CENTRE, real)
    rerun = await upload(committed, st, envelope(st, C.COST_CENTRE, records))
    assert isinstance(rerun, BatchResult) and rerun.status == "COMPLETE"
    assert await count(committed, CostCentre, st.company_id) == 5  # no duplicates
    assert await watermark(committed, st.company_id, C.COST_CENTRE) == 5


@pytest.mark.req_partial("SYNC-6.5")  # parse errors from the Agent: test_failed_records.py
async def test_a_failing_record_is_skipped_and_holds_the_watermark_below_it(
    committed: Factory,
) -> None:
    """D-039 #7: two groups claiming the same reserved name - the second cannot be stored."""
    st = await setup(committed)
    await lease(committed, st, C.GROUP)
    records = [
        group("g-1", 10, "Sales Accounts", reserved_name="Sales Accounts"),
        group("g-2", 20, "Sales Duplicate", reserved_name="Sales Accounts"),
        group("g-3", 30, "Retail"),
    ]
    result = await upload(committed, st, envelope(st, C.GROUP, records))
    assert isinstance(result, BatchResult)
    assert (result.status, result.written, result.failed) == ("PARTIAL", 2, 1)
    assert await watermark(committed, st.company_id, C.GROUP) == 19  # below the failure at 20
    async with committed() as s:
        error = (await s.execute(select(SyncError))).scalar_one()
        assert (error.tally_guid, error.alter_id, error.watermark_hold) == ("g-2", 20, 19)


@pytest.mark.parametrize("problem", ["no_lease", "lost_command"])
async def test_a_batch_without_its_lease_or_from_a_lost_command_changes_nothing(
    committed: Factory, problem: str
) -> None:
    st = await setup(committed)
    if problem == "lost_command":
        await lease(committed, st, C.COST_CENTRE)
        async with committed() as s:
            await s.execute(update(AgentCommand).values(status="FAILED_AGENT_LOST"))
            await s.commit()
    result = await upload(
        committed,
        st,
        envelope(st, C.COST_CENTRE, [CostCentreRecord(guid="cc", alter_id=1, name="X")]),
    )
    assert result == ("SYNC_LOCKED" if problem == "no_lease" else "INVALID_COMMAND_STATE")
    assert await count(committed, CostCentre, st.company_id) == 0
    assert await watermark(committed, st.company_id, C.COST_CENTRE) == 0


async def test_a_command_lost_mid_batch_stops_every_later_chunk(
    committed: Factory, monkeypatch: pytest.MonkeyPatch
) -> None:
    """D-039 #1 on real connections: the lost-Agent update waits for the chunk in flight (its
    FOR SHARE lock), then every later chunk sees FAILED_AGENT_LOST and writes nothing."""
    st = await setup(committed, chunk_size=1)
    await lease(committed, st, C.COST_CENTRE)
    real = ingest_module.WRITERS[C.COST_CENTRE]
    lost: list[asyncio.Task[None]] = []

    async def mark_lost() -> None:
        async with committed() as s:
            await s.execute(
                update(AgentCommand)
                .where(AgentCommand.command_id == st.command_id)
                .values(status="FAILED_AGENT_LOST")
            )
            await s.commit()

    async def first_chunk_then_lost(session: AsyncSession, ctx: Any, chunk: list[Any]) -> Any:
        if not lost:
            lost.append(asyncio.create_task(mark_lost()))
            await asyncio.sleep(0.3)
            assert not lost[0].done(), "the lost job must wait for the chunk in flight"
        return await real(session, ctx, chunk)

    monkeypatch.setitem(ingest_module.WRITERS, C.COST_CENTRE, first_chunk_then_lost)
    records = [CostCentreRecord(guid=f"cc-{i}", alter_id=i, name=f"CC {i}") for i in range(1, 4)]
    result = await upload(committed, st, envelope(st, C.COST_CENTRE, records))
    await lost[0]
    assert isinstance(result, BatchResult) and result.chunks_committed == 1
    assert "FAILED_AGENT_LOST" in (result.error or "")
    assert await count(committed, CostCentre, st.company_id) == 1


async def test_a_lease_taken_over_mid_batch_stops_every_later_chunk(
    committed: Factory, monkeypatch: pytest.MonkeyPatch
) -> None:
    st = await setup(committed, chunk_size=1)
    other = await setup(committed, name="Standby", company_id=st.company_id)
    await lease(committed, st, C.COST_CENTRE)
    real = ingest_module.WRITERS[C.COST_CENTRE]
    takeover: list[asyncio.Task[None]] = []

    async def take_over() -> None:
        async with committed() as s:
            await s.execute(update(SyncWatermark).values(locked_by_agent_id=other.agent.agent_id))
            await s.commit()

    async def first_chunk_then_takeover(session: AsyncSession, ctx: Any, chunk: list[Any]) -> Any:
        if not takeover:
            takeover.append(asyncio.create_task(take_over()))
            await asyncio.sleep(0.3)
            assert not takeover[0].done(), "a takeover must wait for the chunk in flight"
        return await real(session, ctx, chunk)

    monkeypatch.setitem(ingest_module.WRITERS, C.COST_CENTRE, first_chunk_then_takeover)
    records = [CostCentreRecord(guid=f"cc-{i}", alter_id=i, name=f"CC {i}") for i in range(1, 4)]
    result = await upload(committed, st, envelope(st, C.COST_CENTRE, records))
    await takeover[0]
    assert isinstance(result, BatchResult) and result.chunks_committed == 1
    assert await count(committed, CostCentre, st.company_id) == 1
    async with committed() as s:
        assert await s.scalar(text("SELECT count(*) FROM sync_batches")) == 0  # never COMPLETE
