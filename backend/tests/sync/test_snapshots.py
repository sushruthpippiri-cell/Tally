"""P5.6: stock snapshots (FR-STK-15, D-040 #8) on committing connections."""

from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import select, update

from app.models.agents import AgentCommand
from app.models.balances import StockSnapshot
from app.models.enums import CollectionType as C
from app.models.sync import SyncError
from app.sync.ingest import BatchResult
from tally_contract import normalize
from tally_contract.records import LedgerClosingBalanceRecord, StockSnapshotRecord
from tests.sync.helpers import Factory, Setup, count, envelope, lease, setup, sync_masters, upload

DAY = date(2026, 3, 16)


def snap(guid: str, qty: str, when: date = DAY) -> StockSnapshotRecord:
    return StockSnapshotRecord(
        stock_item_guid=guid, as_of_date=when, closing_quantity=Decimal(qty), unit="Nos"
    )


async def _ready(committed: Factory) -> Setup:
    st = await setup(committed)
    await sync_masters(committed, st)  # holds and releases nothing: the leases stay held
    return st


async def _stored(committed: Factory) -> list[tuple[date, Decimal]]:
    async with committed() as s:
        rows = await s.execute(
            select(StockSnapshot.as_of_date, StockSnapshot.closing_quantity).order_by(
                StockSnapshot.as_of_date
            )
        )
        return [(d, q) for d, q in rows.tuples()]


@pytest.mark.req_partial("FR-STK-15")  # the Agent's pull of Tally's closing quantity: P7 (G18)
async def test_snapshots_are_stored_and_a_resend_replaces_them(committed: Factory) -> None:
    st = await _ready(committed)
    first = await upload(
        committed,
        st,
        envelope(st, None, [snap("s-soap", "40"), snap("s-soap", "35", date(2026, 3, 15))]),
    )
    assert isinstance(first, BatchResult) and first.written == 2, first
    again = await upload(committed, st, envelope(st, None, [snap("s-soap", "38")]))
    assert isinstance(again, BatchResult) and again.written == 1, again
    assert await _stored(committed) == [(date(2026, 3, 15), Decimal("35")), (DAY, Decimal("38"))]
    async with committed() as s:
        run_ids = set((await s.execute(select(StockSnapshot.sync_run_id))).scalars())
    assert run_ids == {st.run_id}


async def test_an_unknown_item_is_recorded_without_holding_anything(committed: Factory) -> None:
    st = await _ready(committed)
    result = await upload(
        committed, st, envelope(st, None, [snap("s-soap", "40"), snap("s-ghost", "1")])
    )
    assert isinstance(result, BatchResult), result
    assert (result.status, result.written, result.failed) == ("PARTIAL", 1, 1)
    async with committed() as s:
        error = (await s.execute(select(SyncError))).scalar_one()
    assert (error.entity_type, error.error_code, error.tally_guid, error.watermark_hold) == (
        "STOCK_SNAPSHOT",
        "UNKNOWN_MASTER_REFERENCE",
        "s-ghost",
        None,
    )


@pytest.mark.parametrize("problem", ["no_lease", "lost_command"])
async def test_snapshots_need_the_stock_item_lease_and_a_running_command(
    committed: Factory, problem: str
) -> None:
    st = await setup(committed)
    if problem == "lost_command":
        await lease(committed, st, C.STOCK_ITEM)
        async with committed() as s:
            await s.execute(update(AgentCommand).values(status="FAILED_AGENT_LOST"))
            await s.commit()
    result = await upload(committed, st, envelope(st, None, [snap("s-soap", "40")]))
    assert result == ("SYNC_LOCKED" if problem == "no_lease" else "INVALID_COMMAND_STATE")
    assert await count(committed, StockSnapshot, st.company_id) == 0


async def test_other_records_without_a_collection_wait_for_p10(committed: Factory) -> None:
    st = await _ready(committed)
    balance = LedgerClosingBalanceRecord(
        ledger_guid="l-cash", as_of_date=DAY, balance=normalize.to_amount("-100.00", True)
    )
    assert await upload(committed, st, envelope(st, None, [balance])) == "VALIDATION_ERROR"
