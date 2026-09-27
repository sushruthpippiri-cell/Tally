"""P5.4: voucher ingest on committing connections (SRS 6.7, 6.9, AC-01/02/06/08, D-039)."""

from datetime import date
from decimal import Decimal
from typing import Any

import pytest
from sqlalchemy import func, select, text

from app.models.config import AuditLog
from app.models.enums import CollectionType as C
from app.models.sync import SyncError
from app.models.vouchers import Voucher, VoucherEntry
from app.sync.holds import held_back
from app.sync.ingest import BatchResult
from tally_contract.records import LedgerRecord
from tally_contract.testing import assert_logged
from tests.sync.helpers import (
    Factory,
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


async def _vouchers(committed: Factory, st: Any, records: list[Any]) -> BatchResult:
    await lease(committed, st, C.VOUCHER)
    result = await upload(committed, st, envelope(st, C.VOUCHER, records))
    assert isinstance(result, BatchResult), result
    return result


async def _counts(committed: Factory) -> dict[str, int]:
    names = [
        "groups",
        "ledgers",
        "voucher_types",
        "stock_items",
        "cost_centres",
        "vouchers",
        "voucher_entries",
        "bill_allocations",
        "cost_centre_allocations",
        "voucher_items",
    ]
    async with committed() as s:
        return {n: int(await s.scalar(text(f"SELECT count(*) FROM {n}"))) for n in names}


@pytest.mark.req_partial("AC-01")  # "Tally holds X vouchers": the Agent's pull (P7) on live G3
async def test_a_full_sync_twice_adds_nothing_the_second_time(committed: Factory) -> None:
    st = await setup(committed)
    await sync_masters(committed, st)
    await _vouchers(
        committed, st, [sale("v-1", 100, "1180.00"), sale("v-2", 101, "590.00", number="S-2")]
    )
    first = await _counts(committed)
    assert first["vouchers"] == 2 and first["voucher_entries"] == 6
    await sync_masters(committed, st)
    await _vouchers(
        committed, st, [sale("v-1", 100, "1180.00"), sale("v-2", 101, "590.00", number="S-2")]
    )
    assert await _counts(committed) == first
    async with committed() as s:
        keys = (await s.execute(select(Voucher.company_id, Voucher.tally_guid))).all()
        assert sorted(g for _, g in keys) == ["v-1", "v-2"]


@pytest.mark.req_partial("AC-02")  # Tally raising the ALTERID on an edit: live G8
async def test_a_modified_voucher_shows_the_new_amount_and_the_audit_has_both(
    committed: Factory,
) -> None:
    st = await setup(committed)
    await sync_masters(committed, st)
    await _vouchers(committed, st, [sale("v-100", 100, "10000.00")])
    await _vouchers(committed, st, [sale("v-100", 107, "15000.00")])
    async with committed() as s:
        debit = await s.scalar(
            select(VoucherEntry.amount_absolute).where(VoucherEntry.accounting_direction == "DEBIT")
        )
        assert debit == Decimal("15000.00")
        audit = (
            await s.execute(select(AuditLog).where(AuditLog.action == "VOUCHER_MODIFIED"))
        ).scalar_one()
        assert Decimal(audit.before_value["total"]) == Decimal("10000")
        assert Decimal(audit.after_value["total"]) == Decimal("15000")
        assert audit.user_id is None and audit.after_value["alter_id"] == 107


@pytest.mark.req("AC-06")
async def test_a_stale_voucher_is_ignored_and_logged(
    committed: Factory, caplog: pytest.LogCaptureFixture
) -> None:
    st = await setup(committed)
    await sync_masters(committed, st)
    await _vouchers(committed, st, [sale("v-1", 108, "1180.00")])
    result = await _vouchers(committed, st, [sale("v-1", 106, "999.00")])
    assert result.rejected_stale == 1 and result.failed == 0
    assert_logged(
        caplog,
        "stale_alterid",
        level="warning",
        guid="v-1",
        stored_alter_id=108,
        incoming_alter_id=106,
    )
    async with committed() as s:
        assert await s.scalar(select(Voucher.alter_id)) == 108
        assert await s.scalar(select(func.max(VoucherEntry.amount_absolute))) == Decimal("1180.00")
        assert await s.scalar(select(SyncError.error_code)) == "STALE_ALTERID"


@pytest.mark.req("SYNC-3.1", "SYNC-3.2", "SYNC-3.3", "SYNC-3.4", "SYNC-3.5")
async def test_stale_protection_applies_to_every_synced_collection(committed: Factory) -> None:
    st = await setup(committed)
    data = masters()
    await sync_masters(committed, st, data)
    await _vouchers(committed, st, [sale("v-1", 500, "1180.00")])
    for collection, records in [*data.items(), (C.VOUCHER, [sale("v-1", 500, "1180.00")])]:
        record = records[0]
        lower = record.model_copy(update={"alter_id": record.alter_id - 1})
        higher = record.model_copy(update={"alter_id": record.alter_id + 1000})
        await lease(committed, st, collection)
        stale = await upload(committed, st, envelope(st, collection, [lower]))
        equal = await upload(committed, st, envelope(st, collection, [record]))
        applied = await upload(committed, st, envelope(st, collection, [higher]))
        assert isinstance(stale, BatchResult) and stale.rejected_stale == 1, collection
        assert isinstance(equal, BatchResult) and equal.unchanged == 1, collection
        assert isinstance(applied, BatchResult) and applied.written == 1, collection


@pytest.mark.req("AC-08", "DR-VE-3")
async def test_a_modified_voucher_has_its_children_replaced_with_no_orphans(
    committed: Factory,
) -> None:
    st = await setup(committed)
    await sync_masters(committed, st)
    await _vouchers(committed, st, [sale("v-1", 100, "1180.00")])
    before = await _counts(committed)
    assert (
        before["voucher_entries"],
        before["bill_allocations"],
        before["cost_centre_allocations"],
        before["voucher_items"],
    ) == (3, 1, 1, 1)
    await _vouchers(committed, st, [sale("v-1", 150, "2360.00", with_bill=False, with_item=False)])
    after = await _counts(committed)
    assert (
        after["voucher_entries"],
        after["bill_allocations"],
        after["cost_centre_allocations"],
        after["voucher_items"],
    ) == (3, 0, 1, 0)
    async with committed() as s:
        orphans = await s.scalar(
            text(
                "SELECT count(*) FROM voucher_entries e LEFT JOIN vouchers v USING (voucher_id) "
                "WHERE v.voucher_id IS NULL"
            )
        )
        duplicates = await s.scalar(
            text(
                "SELECT count(*) FROM (SELECT voucher_id, line_sequence FROM voucher_entries "
                "GROUP BY 1, 2 HAVING count(*) > 1) d"
            )
        )
        assert (orphans, duplicates) == (0, 0)
        assert await s.scalar(select(func.sum(VoucherEntry.amount_signed))) == 0


@pytest.mark.req_partial("AC-03")  # excluded from standard analytics: P8; Tally's indicator: G9
async def test_a_cancelled_voucher_keeps_its_row_and_is_audited(committed: Factory) -> None:
    st = await setup(committed)
    await sync_masters(committed, st)
    await _vouchers(committed, st, [sale("v-1", 100, "1180.00")])
    await _vouchers(committed, st, [sale("v-1", 120, "1180.00", cancelled=True)])
    async with committed() as s:
        assert await s.scalar(select(Voucher.status)) == "CANCELLED"
        assert (
            await s.scalar(select(AuditLog.action).where(AuditLog.entity_type == "voucher"))
            == "VOUCHER_CANCELLED"
        )


async def test_lines_without_guids_resolve_by_exact_name(committed: Factory) -> None:
    """D-002 fallback while G30 is not passed."""
    st = await setup(committed)
    await sync_masters(committed, st)
    result = await _vouchers(
        committed, st, [sale("v-1", 100, "1180.00", customer=(None, "Sharma Traders"))]
    )
    assert result.written == 1 and result.failed == 0


async def test_a_voucher_whose_ledger_arrives_next_run_is_stored_on_retry(
    committed: Factory,
) -> None:
    """Owner test (D-039 #7): the failing voucher is skipped, the others are stored, the
    watermark stays below it; the next run's master pull brings the ledger and the retry
    stores it."""
    st = await setup(committed)
    await sync_masters(committed, st)
    new_customer = ("l-new", "New Customer")
    batch = [
        sale("v-1", 100, "1180.00"),
        sale("v-2", 110, "590.00", number="S-2", customer=new_customer),
        sale("v-3", 120, "236.00", number="S-3"),
    ]
    first = await _vouchers(committed, st, batch)
    assert (first.status, first.written, first.failed) == ("PARTIAL", 2, 1)
    assert await watermark(committed, st.company_id, C.VOUCHER) == 109
    async with committed() as s:
        error = (await s.execute(select(SyncError))).scalar_one()
        assert (error.error_code, error.tally_guid, error.alter_id) == (
            "UNKNOWN_MASTER_REFERENCE",
            "v-2",
            110,
        )
        assert await held_back(s, st.company_id) == {"VOUCHER": 1}
    # Next run: the master pull brings the ledger, then vouchers from the watermark (109).
    await end_run(committed, st)
    retry = await setup(committed, company_id=st.company_id, name="Head Office (run 2)")
    await sync_masters(
        committed,
        retry,
        {
            C.LEDGER: [
                LedgerRecord(
                    guid="l-new",
                    alter_id=15,
                    name="New Customer",
                    parent_group_guid="g-sd",
                    parent_group_name="Sundry Debtors",
                )
            ]
        },
    )
    second = await _vouchers(committed, retry, [v for v in batch if v.alter_id > 109])
    assert (second.status, second.written, second.unchanged) == ("COMPLETE", 1, 1)
    assert await watermark(committed, st.company_id, C.VOUCHER) == 120
    async with committed() as s:
        assert await s.scalar(select(func.count()).select_from(Voucher)) == 3
        assert await held_back(s, st.company_id) == {}


async def test_a_permanent_failure_never_lets_the_watermark_pass_it(committed: Factory) -> None:
    st = await setup(committed)
    await sync_masters(committed, st)
    stuck = sale("v-stuck", 110, "590.00", number="S-2", customer=("l-ghost", "Ghost Ledger"))
    later = [sale(f"v-{n}", n, "118.00", number=f"S-{n}") for n in (150, 200, 250)]
    current = st
    for run in range(3):
        if run:  # each run is a new command; the previous one released its leases
            await end_run(committed, current)
            current = await setup(committed, company_id=st.company_id, name=f"run-{run}")
        result = await _vouchers(committed, current, [stuck, *later])
        assert result.failed == 1
        assert await watermark(committed, st.company_id, C.VOUCHER) == 109
    async with committed() as s:
        assert await s.scalar(select(func.count()).select_from(Voucher)) == 3  # the rest are stored
        assert await held_back(s, st.company_id) == {"VOUCHER": 1}


async def test_the_backend_rechecks_the_balance(committed: Factory) -> None:
    """D-005: never trust the Agent's arithmetic."""
    st = await setup(committed)
    await sync_masters(committed, st)
    good = sale("v-1", 100, "1180.00")
    bad_entries = [good.entries[0], good.entries[1]]  # the tax line is missing
    bad = sale("v-2", 101, "1180.00", number="S-2").model_copy(update={"entries": bad_entries})
    result = await _vouchers(committed, st, [good, bad])
    assert (result.written, result.failed) == (1, 1)
    async with committed() as s:
        assert await s.scalar(select(SyncError.error_code)) == "DEBIT_CREDIT_IMBALANCE"


@pytest.mark.req("DR-4.4")
@pytest.mark.req_partial("DR-4.1")  # voucher_number display-only in the UI: P13/P14
async def test_voucher_numbers_repeat_across_years_and_companies_without_collision(
    committed: Factory,
) -> None:
    st = await setup(committed)
    await sync_masters(committed, st)
    other = await setup(committed, name="Other Co Agent")
    await sync_masters(committed, other)
    await _vouchers(
        committed,
        st,
        [
            sale("v-a", 100, "118.00", number="1", when=date(2024, 4, 1)),
            sale("v-b", 101, "118.00", number="1", when=date(2025, 4, 1)),
        ],
    )
    await _vouchers(committed, other, [sale("v-a2", 100, "118.00", number="1")])
    async with committed() as s:
        assert (
            await s.scalar(
                select(func.count()).select_from(Voucher).where(Voucher.voucher_number == "1")
            )
            == 3
        )


async def test_references_resolve_only_within_the_company(committed: Factory) -> None:
    st = await setup(committed)
    await sync_masters(committed, st)
    other = await setup(committed, name="Other Co Agent")  # its own company, no masters
    result = await _vouchers(committed, other, [sale("v-x", 100, "1180.00")])
    assert (result.written, result.failed) == (0, 1)


@pytest.mark.req("SYNC-6.3")
async def test_replaying_a_voucher_batch_is_safe(committed: Factory) -> None:
    st = await setup(committed)
    await sync_masters(committed, st)
    await lease(committed, st, C.VOUCHER)
    env = envelope(st, C.VOUCHER, [sale("v-1", 100, "1180.00")])
    await upload(committed, st, env)
    state = await _counts(committed)
    again = await upload(committed, st, env)
    assert isinstance(again, BatchResult) and again.replayed
    assert await _counts(committed) == state
