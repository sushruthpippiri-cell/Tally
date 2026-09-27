"""P5.5: watermarks (SYNC-1.x, D-039 #2 and #7) on committing connections."""

from datetime import date

import pytest
from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert

from app.models.enums import CollectionType as C
from app.models.enums import SyncMode
from app.models.sync import SyncWatermark
from app.models.vouchers import Voucher, VoucherEntry
from app.schemas.sync import ReleaseRequest
from app.services.sync_runs import release_lease, start_run
from app.sync.ingest import BatchResult
from tally_contract.records import AlterIdWindow, DateWindow, LedgerRecord
from tests.sync.helpers import (
    Factory,
    Setup,
    end_run,
    envelope,
    lease,
    sale,
    setup,
    sync_masters,
    upload,
    watermark,
)

APRIL = DateWindow(date_from=date(2024, 4, 1), date_to=date(2024, 4, 30))
MAY = DateWindow(date_from=date(2024, 5, 1), date_to=date(2024, 5, 31))


async def _set_watermark(committed: Factory, st: Setup, collection: C, value: int) -> None:
    async with committed() as s:
        stmt = insert(SyncWatermark).values(
            company_id=st.company_id, collection_type=collection, last_alter_id=value, status="OK"
        )
        await s.execute(
            stmt.on_conflict_do_update(
                index_elements=[SyncWatermark.company_id, SyncWatermark.collection_type],
                set_={"last_alter_id": value},
            )
        )
        await s.commit()


async def _page(committed: Factory, st: Setup, records: list[object], window: object) -> None:
    result = await upload(committed, st, envelope(st, C.VOUCHER, records, window=window))  # type: ignore[arg-type]
    assert isinstance(result, BatchResult) and result.failed == 0, result


async def _release(committed: Factory, st: Setup, start_max: int | None) -> int:
    async with committed() as s:
        out = await release_lease(
            s,
            st.agent,
            ReleaseRequest(
                sync_run_id=st.run_id,
                collection_type=C.VOUCHER,
                complete=True,
                start_max_alter_id=start_max,
            ),
        )
    return out.last_alter_id


async def _amount(committed: Factory, guid: str) -> str:
    """ALTERID and the debit total of the stored voucher."""
    async with committed() as s:
        row = (
            await s.execute(
                select(Voucher.alter_id, func.sum(VoucherEntry.amount_absolute))
                .join(VoucherEntry, VoucherEntry.voucher_id == Voucher.voucher_id)
                .where(Voucher.tally_guid == guid, VoucherEntry.accounting_direction == "DEBIT")
                .group_by(Voucher.alter_id)
            )
        ).one()
        return f"{row[0]}:{row[1]:.2f}"


@pytest.mark.req("AC-07", "SYNC-1.1")
async def test_each_collection_is_pulled_and_advanced_from_its_own_watermark(
    committed: Factory,
) -> None:
    st = await setup(committed, sync_mode=SyncMode.INCREMENTAL)
    await sync_masters(committed, st)
    await _set_watermark(committed, st, C.VOUCHER, 500)
    await _set_watermark(committed, st, C.LEDGER, 50)
    async with committed() as s:
        plan = (await start_run(s, st.agent, st.command_id)).collections
    assert (plan[C.VOUCHER].watermark, plan[C.LEDGER].watermark) == (500, 50)
    assert not plan[C.LEDGER].full

    # A ledger changed at ALTERID 55: far below the voucher watermark, and still pulled.
    await lease(committed, st, C.LEDGER)
    changed = LedgerRecord(
        guid="l-sharma",
        alter_id=55,
        name="Sharma Traders & Co",
        parent_group_guid="g-sd",
        parent_group_name="Sundry Debtors",
    )
    window = AlterIdWindow(from_alter_id=50, to_alter_id=55)
    result = await upload(committed, st, envelope(st, C.LEDGER, [changed], window=window))
    assert isinstance(result, BatchResult) and result.written == 1, result
    assert await watermark(committed, st.company_id, C.LEDGER) == 55
    assert await watermark(committed, st.company_id, C.VOUCHER) == 500

    await lease(committed, st, C.VOUCHER)
    window = AlterIdWindow(from_alter_id=500, to_alter_id=510)
    await _page(committed, st, [sale("v-510", 510, "1180.00")], window)
    assert await watermark(committed, st.company_id, C.VOUCHER) == 510
    assert await watermark(committed, st.company_id, C.LEDGER) == 55


async def test_a_date_range_run_stores_records_but_never_moves_the_watermark(
    committed: Factory,
) -> None:
    st = await setup(
        committed, sync_mode=SyncMode.DATE_RANGE, dates=(APRIL.date_from, APRIL.date_to)
    )
    await sync_masters(committed, st)
    await lease(committed, st, C.VOUCHER)
    await _page(committed, st, [sale("v-1", 100, "1180.00")], APRIL)
    assert await watermark(committed, st.company_id, C.VOUCHER) == 0
    assert await _release(committed, st, start_max=100) == 0  # not even on "complete"
    assert await _amount(committed, "v-1") == "100:1180.00"


async def test_a_record_edited_during_a_date_paged_full_pull_is_picked_up_next_time(
    committed: Factory,
) -> None:
    """Owner test (D-039 #2): the pre-pull max is 100. R (ALTERID 50, April) is pulled on the
    April page; Tally then edits it to ALTERID 120 before the May page. On complete the
    watermark moves to 100, not to the end-of-pull max, so the next incremental re-pulls R."""
    st = await setup(committed, sync_mode=SyncMode.FULL)
    await sync_masters(committed, st)
    await lease(committed, st, C.VOUCHER)
    await _page(committed, st, [sale("r", 50, "1180.00")], APRIL)
    # R is edited in Tally here (ALTERID 120); its April page has already been pulled.
    may = [sale("v-100", 100, "590.00", number="S-2", when=date(2024, 5, 2))]
    await _page(committed, st, may, MAY)
    assert await watermark(committed, st.company_id, C.VOUCHER) == 0  # pages never move it
    assert await _release(committed, st, start_max=100) == 100

    await end_run(committed, st)
    nxt = await setup(
        committed, company_id=st.company_id, sync_mode=SyncMode.INCREMENTAL, name="run 2"
    )
    await lease(committed, nxt, C.VOUCHER)
    window = AlterIdWindow(from_alter_id=100, to_alter_id=120)
    await _page(committed, nxt, [sale("r", 120, "2360.00")], window)
    assert await _amount(committed, "r") == "120:2360.00"
    assert await watermark(committed, st.company_id, C.VOUCHER) == 120


async def test_without_the_pre_pull_max_a_date_paged_full_pull_does_not_advance(
    committed: Factory,
) -> None:
    st = await setup(committed, sync_mode=SyncMode.FULL)
    await sync_masters(committed, st)
    await lease(committed, st, C.VOUCHER)
    await _page(committed, st, [sale("v-1", 100, "1180.00")], APRIL)
    assert await _release(committed, st, start_max=None) == 0  # G33 not passed


async def test_complete_never_moves_the_watermark_past_a_failed_record(committed: Factory) -> None:
    st = await setup(committed, sync_mode=SyncMode.FULL)
    await sync_masters(committed, st)
    await lease(committed, st, C.VOUCHER)
    ghost = sale("v-ghost", 60, "590.00", number="S-2", customer=("l-ghost", "Ghost"))
    result = await upload(
        committed, st, envelope(st, C.VOUCHER, [sale("v-1", 40, "1180.00"), ghost], window=APRIL)
    )
    assert isinstance(result, BatchResult) and result.failed == 1, result
    assert await _release(committed, st, start_max=100) == 59  # held below ALTERID 60
