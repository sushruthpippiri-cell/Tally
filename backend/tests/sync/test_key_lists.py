"""P6.2/P6.3: deletion detection by key list, reappearance and master lifecycle (SYNC-5.x,
DR-ML-1-4, D-007, D-041) on committing connections."""

import uuid
from datetime import date
from typing import Any

import pytest
from sqlalchemy import func, select, update

from app.core.errors import AppError
from app.core.permissions import CompanyContext
from app.models.company import Company
from app.models.config import AuditLog, CompanySetting
from app.models.enums import CollectionType as C
from app.models.enums import RoleName, SettingDataType
from app.models.masters import CostCentre, Ledger
from app.models.sync import SyncKeyList, SyncKeyListKey, SyncWatermark
from app.models.vouchers import Voucher, VoucherEntry
from app.schemas.sync import FinishRequest, KeyListOut
from app.services.sync_runs import finish_run, key_lists_due
from app.sync import keylists
from app.sync.ingest import BatchResult
from tally_contract.records import (
    AlterIdWindow,
    CostCentreRecord,
    DateWindow,
    KeyListChunk,
    KeyRecord,
    LedgerRecord,
)
from tally_contract.testing import assert_logged
from tests.factories import make_user
from tests.sync.helpers import (
    Factory,
    Setup,
    data_quality_items,
    end_run,
    envelope,
    lease,
    masters,
    sale,
    setup,
    sync_masters,
    upload,
    watermark,
)

APRIL = DateWindow(date_from=date(2024, 4, 1), date_to=date(2024, 4, 30))


async def _key_list(
    committed: Factory,
    st: Setup,
    collection: C,
    keys: list[tuple[str, int]],
    *,
    window: DateWindow | None = None,
    per_chunk: int = 10_000,
    order: list[int] | None = None,
) -> KeyListOut | str:
    list_id = uuid.uuid4()
    parts = [keys[i : i + per_chunk] for i in range(0, len(keys), per_chunk)] or [[]]
    out: KeyListOut | str = ""
    for seq in order or range(len(parts)):
        chunk = KeyListChunk(
            collection_type=collection,
            command_id=st.command_id,
            sync_run_id=st.run_id,
            list_id=list_id,
            chunk_seq=seq,
            is_final=seq == len(parts) - 1,
            window=window,
            keys=[KeyRecord(guid=g, alter_id=a) for g, a in parts[seq]],
        )
        async with committed() as s:
            try:
                out = await keylists.receive(s, st.agent, st.command_id, chunk)
            except AppError as exc:
                return exc.code.value
    return out


async def _statuses(committed: Factory, model: Any) -> dict[str, str]:
    async with committed() as s:
        rows = await s.execute(select(model.tally_guid, model.status))
        return {g: st for g, st in rows.tuples()}


async def _actions(committed: Factory, action: str) -> int:
    async with committed() as s:
        return int(await s.scalar(select(func.count()).where(AuditLog.action == action)) or 0)


async def _cost_centres(committed: Factory, st: Setup, n: int) -> list[tuple[str, int]]:
    await lease(committed, st, C.COST_CENTRE)
    records = [
        CostCentreRecord(guid=f"cc-{i}", alter_id=i, name=f"CC {i}") for i in range(1, n + 1)
    ]
    result = await upload(committed, st, envelope(st, C.COST_CENTRE, records))
    assert isinstance(result, BatchResult) and result.written == n, result
    return [(r.guid, r.alter_id) for r in records]


async def _vouchers(committed: Factory, st: Setup, records: list[Any]) -> None:
    await lease(committed, st, C.VOUCHER)
    result = await upload(committed, st, envelope(st, C.VOUCHER, records))
    assert isinstance(result, BatchResult) and result.failed == 0, result


# --- missing ------------------------------------------------------------------------------


@pytest.mark.req("SYNC-5.2", "AC-04")
async def test_an_active_voucher_missing_from_the_key_list_becomes_missing_in_tally(
    committed: Factory,
) -> None:
    st = await setup(committed)
    await sync_masters(committed, st)
    batch = [sale(f"v-{n}", n, "1180.00", number=f"S-{n}") for n in (100, 110, 120)]
    await _vouchers(committed, st, batch)
    out = await _key_list(committed, st, C.VOUCHER, [("v-100", 100), ("v-120", 120)])
    assert isinstance(out, KeyListOut)
    assert (out.status, out.candidates, out.marked_missing) == ("APPLIED", 3, 1)
    assert await _statuses(committed, Voucher) == {
        "v-100": "ACTIVE",
        "v-110": "MISSING_IN_TALLY",  # the row is kept
        "v-120": "ACTIVE",
    }
    assert await _actions(committed, "MISSING_IN_TALLY") == 1
    listed = await data_quality_items(committed, st.company_id, "missing_vouchers")
    assert [i["tally_guid"] for i in listed or []] == ["v-110"]
    async with committed() as s:  # staged keys are gone; the list stays as history
        assert await s.scalar(select(func.count()).select_from(SyncKeyListKey)) == 0


@pytest.mark.req("DR-ML-1", "DR-ML-2", "DR-ML-3")
@pytest.mark.req_partial("AC-10")  # P10's full reconciliation is the other detector
async def test_a_ledger_missing_from_its_key_list_keeps_its_row_and_its_vouchers(
    committed: Factory,
) -> None:
    st = await setup(committed)
    await sync_masters(committed, st)
    await _vouchers(committed, st, [sale("v-1", 100, "1180.00")])
    async with committed() as s:
        sharma = (
            await s.execute(select(Ledger).where(Ledger.tally_guid == "l-sharma"))
        ).scalar_one()
        entries_before = await s.scalar(
            select(func.count()).where(VoucherEntry.ledger_id == sharma.ledger_id)
        )
    keys = [(r.guid, r.alter_id) for r in masters()[C.LEDGER] if r.guid != "l-sharma"]
    out = await _key_list(committed, st, C.LEDGER, keys)
    assert isinstance(out, KeyListOut) and out.marked_missing == 1
    async with committed() as s:
        row = await s.get(Ledger, sharma.ledger_id)
        assert row is not None and row.status == "MISSING_IN_TALLY"
        assert entries_before == await s.scalar(
            select(func.count()).where(VoucherEntry.ledger_id == sharma.ledger_id)
        )
        voucher = (await s.execute(select(Voucher))).scalar_one()
        assert voucher.status == "ACTIVE"  # past-period analytics are unaffected
    review = await data_quality_items(committed, st.company_id, "missing_masters")
    assert [(i["master_type"], i["name"]) for i in review or []] == [("LEDGER", "Sharma Traders")]


async def test_a_cancelled_voucher_is_never_a_candidate(committed: Factory) -> None:
    st = await setup(committed)
    await sync_masters(committed, st)
    await _vouchers(
        committed,
        st,
        [sale("v-1", 100, "1180.00"), sale("v-2", 110, "590.00", number="S-2", cancelled=True)],
    )
    out = await _key_list(committed, st, C.VOUCHER, [("v-1", 100)])
    assert isinstance(out, KeyListOut) and (out.candidates, out.marked_missing) == (1, 0)
    assert (await _statuses(committed, Voucher))["v-2"] == "CANCELLED"


# --- owner item 5: the window --------------------------------------------------------------


async def test_a_windowed_key_list_marks_only_records_inside_its_window(committed: Factory) -> None:
    st = await setup(committed)
    await sync_masters(committed, st)
    april = [
        sale(f"a-{n}", n, "1180.00", number=f"A-{n}", when=date(2024, 4, n)) for n in (1, 2, 3)
    ]
    may = [
        sale(f"m-{n}", 100 + n, "590.00", number=f"M-{n}", when=date(2024, 5, n)) for n in (1, 2)
    ]
    await _vouchers(committed, st, april + may)
    async with committed() as s:  # a May voucher already missing, to come back
        await s.execute(
            update(Voucher).where(Voucher.tally_guid == "m-2").values(status="MISSING_IN_TALLY")
        )
        await s.commit()
    keys = [("a-1", 1), ("a-3", 3), ("m-2", 102)]  # a-2 is gone; m-1 lies outside the window
    out = await _key_list(committed, st, C.VOUCHER, keys, window=APRIL)
    assert isinstance(out, KeyListOut)
    assert (out.candidates, out.marked_missing, out.reappeared) == (3, 1, 1)
    assert await _statuses(committed, Voucher) == {
        "a-1": "ACTIVE",
        "a-2": "MISSING_IN_TALLY",
        "a-3": "ACTIVE",
        "m-1": "ACTIVE",  # outside the window: never touched
        "m-2": "ACTIVE",  # present anywhere in the list: restored
    }


# --- owner item 2: the D-007 guard ---------------------------------------------------------


async def test_an_empty_key_list_marks_nothing(
    committed: Factory, caplog: pytest.LogCaptureFixture
) -> None:
    st = await setup(committed)
    await _cost_centres(committed, st, 10)
    out = await _key_list(committed, st, C.COST_CENTRE, [])
    assert isinstance(out, KeyListOut) and (out.status, out.marked_missing) == ("SUSPICIOUS", 0)
    assert set((await _statuses(committed, CostCentre)).values()) == {"ACTIVE"}
    assert_logged(caplog, "key_list_suspicious", level="warning", collection="COST_CENTRE")
    flagged = await data_quality_items(committed, st.company_id, "suspicious_key_lists")
    assert [i["list_id"] for i in flagged or []] == [str(out.list_id)]
    # A later list that applies clears it.
    applied = await _key_list(committed, st, C.COST_CENTRE, [(f"cc-{i}", i) for i in range(1, 11)])
    assert isinstance(applied, KeyListOut) and applied.status == "APPLIED"
    assert await data_quality_items(committed, st.company_id, "suspicious_key_lists") == []


@pytest.mark.parametrize(
    ("local", "listed", "applied"),
    [
        (1000, 500, False),  # a truncated list: 500 would go missing
        (30, 1, False),  # a small collection is protected too (the floor is 5, not 50)
        (30, 27, True),  # 3 missing: within max(5, 6)
        (100, 80, True),  # 20 missing: exactly the ratio
        (100, 79, False),  # 21 missing: over it
    ],
)
async def test_an_implausibly_short_key_list_marks_nothing(
    committed: Factory, caplog: pytest.LogCaptureFixture, local: int, listed: int, applied: bool
) -> None:
    st = await setup(committed)
    keys = await _cost_centres(committed, st, local)
    out = await _key_list(committed, st, C.COST_CENTRE, keys[:listed], per_chunk=400)
    assert isinstance(out, KeyListOut)
    missing = sum(
        s == "MISSING_IN_TALLY" for s in (await _statuses(committed, CostCentre)).values()
    )
    if applied:
        assert (out.status, missing) == ("APPLIED", local - listed)
    else:
        assert (out.status, missing) == ("SUSPICIOUS", 0)
        assert_logged(
            caplog, "key_list_suspicious", level="warning", would_be_missing=local - listed
        )


async def test_the_guard_never_blocks_reappearance(committed: Factory) -> None:
    st = await setup(committed)
    keys = await _cost_centres(committed, st, 30)
    async with committed() as s:
        await s.execute(
            update(CostCentre)
            .where(CostCentre.tally_guid == "cc-1")
            .values(status="MISSING_IN_TALLY")
        )
        await s.commit()
    out = await _key_list(committed, st, C.COST_CENTRE, keys[:1])  # suspicious, yet cc-1 is back
    assert isinstance(out, KeyListOut) and (out.status, out.reappeared) == ("SUSPICIOUS", 1)
    assert (await _statuses(committed, CostCentre))["cc-1"] == "ACTIVE"


async def test_a_confirmed_suspicious_list_lets_the_next_list_apply_once(
    committed: Factory,
) -> None:
    st = await setup(committed)
    keys = await _cost_centres(committed, st, 30)
    first = await _key_list(committed, st, C.COST_CENTRE, keys[:10])
    assert isinstance(first, KeyListOut) and first.status == "SUSPICIOUS"
    async with committed() as s:
        company = await s.get(Company, st.company_id)
        owner = await make_user(s, company, RoleName.OWNER)
        await s.commit()
        ctx = CompanyContext(st.company_id, owner.user_id, frozenset())
        with pytest.raises(AppError):  # another company's list is not found
            await keylists.confirm(
                s, CompanyContext(uuid.uuid4(), ctx.user_id, frozenset()), first.list_id
            )
    async with committed() as s:
        confirmed = await keylists.confirm(s, ctx, first.list_id)
    assert confirmed.status == "CONFIRMED"
    assert await _actions(committed, "KEY_LIST_CONFIRMED") == 1
    second = await _key_list(committed, st, C.COST_CENTRE, keys[:10])  # a fresh list
    assert isinstance(second, KeyListOut) and (second.status, second.marked_missing) == (
        "APPLIED",
        20,
    )
    async with committed() as s:
        assert await s.scalar(
            select(SyncKeyList.guard_waived).where(SyncKeyList.list_id == second.list_id)
        )
    third = await _key_list(committed, st, C.COST_CENTRE, [])  # the waiver was used up
    assert isinstance(third, KeyListOut) and third.status == "SUSPICIOUS"


# --- owner item 3: reappearance never depends on ALTERID -----------------------------------


async def _missing(committed: Factory, model: Any, guid: str) -> None:
    async with committed() as s:
        await s.execute(
            update(model).where(model.tally_guid == guid).values(status="MISSING_IN_TALLY")
        )
        await s.commit()


@pytest.mark.req("AC-11", "DR-ML-4")
async def test_a_missing_ledger_listed_again_with_the_same_alter_id_is_active_again(
    committed: Factory,
) -> None:
    st = await setup(committed)
    await sync_masters(committed, st)
    await _missing(committed, Ledger, "l-sharma")
    keys = [(r.guid, r.alter_id) for r in masters()[C.LEDGER]]  # l-sharma at its stored 12
    out = await _key_list(committed, st, C.LEDGER, keys)
    assert isinstance(out, KeyListOut) and out.reappeared == 1
    assert (await _statuses(committed, Ledger))["l-sharma"] == "ACTIVE"
    async with committed() as s:
        audit = (
            await s.execute(select(AuditLog).where(AuditLog.action == "REAPPEARED"))
        ).scalar_one()
    assert audit.after_value == {"status": "ACTIVE", "tally_guid": "l-sharma", "source": "key list"}


@pytest.mark.parametrize("alter", [11, 12, 20], ids=["stale", "equal", "higher"])
async def test_a_missing_ledger_pulled_again_is_active_whatever_its_alter_id(
    committed: Factory, alter: int
) -> None:
    st = await setup(committed)
    await sync_masters(committed, st)
    await _missing(committed, Ledger, "l-sharma")
    again = LedgerRecord(
        guid="l-sharma",
        alter_id=alter,
        name="Sharma Traders",
        parent_group_guid="g-sd",
        parent_group_name="Sundry Debtors",
    )
    window = AlterIdWindow(from_alter_id=0, to_alter_id=alter)
    result = await upload(committed, st, envelope(st, C.LEDGER, [again], window=window))
    assert isinstance(result, BatchResult), result
    assert (await _statuses(committed, Ledger))["l-sharma"] == "ACTIVE"
    assert await _actions(committed, "REAPPEARED") == 1


async def test_a_missing_voucher_pulled_again_with_the_same_alter_id_is_active(
    committed: Factory,
) -> None:
    st = await setup(committed)
    await sync_masters(committed, st)
    await _vouchers(committed, st, [sale("v-1", 100, "1180.00")])
    await _missing(committed, Voucher, "v-1")
    result = await upload(committed, st, envelope(st, C.VOUCHER, [sale("v-1", 100, "1180.00")]))
    assert isinstance(result, BatchResult) and result.unchanged == 1
    assert (await _statuses(committed, Voucher))["v-1"] == "ACTIVE"
    assert await _actions(committed, "REAPPEARED") == 1


# --- missed changes, chunks, frequency ------------------------------------------------------


async def test_a_key_newer_than_the_stored_record_lowers_the_watermark(
    committed: Factory, caplog: pytest.LogCaptureFixture
) -> None:
    st = await setup(committed)
    await sync_masters(committed, st)
    assert await watermark(committed, st.company_id, C.LEDGER) == 13
    keys = [(r.guid, r.alter_id) for r in masters()[C.LEDGER]]
    keys = [(g, 11 if g == "l-cash" else a) for g, a in keys]  # l-cash (stored 10) changed at 11
    out = await _key_list(committed, st, C.LEDGER, keys)
    assert isinstance(out, KeyListOut) and out.missed_changes == 1
    assert await watermark(committed, st.company_id, C.LEDGER) == 10  # re-pulled next run
    assert_logged(caplog, "key_list_missed_change", level="warning", watermark_to=10)


async def test_chunks_may_arrive_out_of_order_or_twice_and_are_evaluated_once(
    committed: Factory,
) -> None:
    st = await setup(committed)
    keys = await _cost_centres(committed, st, 30)
    waiting = await _key_list(committed, st, C.COST_CENTRE, keys, per_chunk=10, order=[2])
    assert isinstance(waiting, KeyListOut)
    assert (waiting.status, waiting.waiting_for) == ("RECEIVING", [0, 1])
    list_id = waiting.list_id

    async def send(seq: int) -> KeyListOut:
        chunk = KeyListChunk(
            collection_type=C.COST_CENTRE,
            command_id=st.command_id,
            sync_run_id=st.run_id,
            list_id=list_id,
            chunk_seq=seq,
            is_final=seq == 2,
            keys=[KeyRecord(guid=g, alter_id=a) for g, a in keys[seq * 10 : seq * 10 + 10]],
        )
        async with committed() as s:
            return await keylists.receive(s, st.agent, st.command_id, chunk)

    assert (await send(0)).waiting_for == [1]
    assert (await send(0)).waiting_for == [1]  # a replayed chunk changes nothing
    done = await send(1)
    assert (done.status, done.keys_count, done.marked_missing) == ("APPLIED", 30, 0)
    assert (await send(1)).status == "APPLIED"  # a replay after evaluation: the stored answer


async def test_a_lost_lease_evaluates_nothing_and_a_closed_run_abandons_the_list(
    committed: Factory,
) -> None:
    st = await setup(committed)
    keys = await _cost_centres(committed, st, 30)
    first = await _key_list(committed, st, C.COST_CENTRE, keys, per_chunk=10, order=[0])
    assert isinstance(first, KeyListOut) and first.status == "RECEIVING"
    await end_run(committed, st)  # the lease is gone
    assert await _key_list(committed, st, C.COST_CENTRE, keys[:1]) == "SYNC_LOCKED"
    async with committed() as s:
        await finish_run(s, st.agent, st.command_id, st.run_id, FinishRequest(status="COMPLETED"))
    async with committed() as s:
        status = await s.scalar(
            select(SyncKeyList.status).where(SyncKeyList.list_id == first.list_id)
        )
        assert status == "ABANDONED"
        assert await s.scalar(select(func.count()).select_from(SyncKeyListKey)) == 0
    assert set((await _statuses(committed, CostCentre)).values()) == {"ACTIVE"}


@pytest.mark.req_partial("SYNC-5.4")  # the Agent acting on it: P7
async def test_a_key_list_is_due_every_n_incremental_runs(committed: Factory) -> None:
    from app.models.enums import SyncMode

    st = await setup(committed, sync_mode=SyncMode.INCREMENTAL)
    async with committed() as s:
        assert C.COST_CENTRE in await key_lists_due(s, st.company_id, st.run_id)  # N = 1: always
        s.add(
            CompanySetting(
                company_id=st.company_id,
                setting_key="sync.key_list_interval",
                setting_value=3,
                data_type=SettingDataType.INTEGER,
            )
        )
        await s.commit()
    keys = await _cost_centres(committed, st, 10)
    due = []
    current = st
    for n in range(5):
        async with committed() as s:
            due.append(C.COST_CENTRE in await key_lists_due(s, st.company_id, current.run_id))
        if due[-1]:
            out = await _key_list(committed, current, C.COST_CENTRE, keys)
            assert isinstance(out, KeyListOut) and out.status == "APPLIED"
        await end_run(committed, current)
        async with committed() as s:
            await s.execute(update(SyncWatermark).values(locked_by_agent_id=None))
            await s.commit()
        current = await setup(
            committed, company_id=st.company_id, sync_mode=SyncMode.INCREMENTAL, name=f"run {n}"
        )
        await lease(committed, current, C.COST_CENTRE)
    assert due == [True, False, False, True, False]
