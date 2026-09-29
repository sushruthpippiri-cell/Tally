"""P11.1: the stored allocation types (AGE-BILL-1, 2, 5), from the P4 fixture through the real
parser and ingest; an unknown type is stored UNSUPPORTED and listed in Data Quality."""

from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import select

from app.models.enums import CollectionType as C
from app.models.vouchers import BillAllocation
from app.sync.ingest import BatchResult
from tally_contract.enums import CollectionType as TallyCollection
from tally_contract.parser import parse_collection
from tally_contract.records import LedgerRecord
from tally_tools.fixtures import SYNTHETIC
from tests.sync.helpers import (
    Factory,
    data_quality_items,
    envelope,
    lease,
    setup,
    sync_masters,
    upload,
)


@pytest.mark.req("AGE-BILL-1")
@pytest.mark.req_partial("AGE-BILL-5")  # the exact exported values: GATE-G25 live capture
async def test_each_allocation_type_is_stored_and_an_unknown_one_is_listed(
    committed: Factory,
) -> None:
    st = await setup(committed)
    await sync_masters(committed, st)
    await lease(committed, st, C.LEDGER)
    extra = [
        LedgerRecord(
            guid="l-hdfc", alter_id=90, name="HDFC Current", parent_group_guid="g-cash",
            parent_group_name="Cash-in-Hand",
        ),
        LedgerRecord(
            guid="l-mehta", alter_id=91, name="Mehta & Sons", parent_group_guid="g-sd",
            parent_group_name="Sundry Debtors",
        ),
    ]  # fmt: skip
    assert isinstance(await upload(committed, st, envelope(st, C.LEDGER, extra)), BatchResult)
    vouchers = parse_collection(
        (SYNTHETIC / "bill_allocations_all_types.xml").read_bytes(), TallyCollection.VOUCHER
    ).records
    await lease(committed, st, C.VOUCHER)
    result = await upload(committed, st, envelope(st, C.VOUCHER, vouchers))
    assert isinstance(result, BatchResult) and result.failed == 0, result
    async with committed() as s:
        stored = {
            (r.reference_name, r.allocation_type, r.accounting_direction, r.amount_absolute)
            for r in (await s.execute(select(BillAllocation))).scalars()
        }
    assert stored == {
        ("S-1", "AGST_REF", "CREDIT", Decimal("1000.0000")),
        ("ADV-1", "ADVANCE", "CREDIT", Decimal("300.0000")),
        (None, "ON_ACCOUNT", "CREDIT", Decimal("100.0000")),
        ("S-9", "UNSUPPORTED", "CREDIT", Decimal("100.0000")),
        ("S-4", "NEW_REF", "DEBIT", Decimal("500.0000")),
    }
    listed = await data_quality_items(committed, st.company_id, "unsupported_bill_allocations")
    assert [(i["reference_name"], i["allocation_type_raw"]) for i in listed or []] == [
        ("S-9", "Bill-by-Bill")
    ]
    assert listed and listed[0]["voucher_date"] == date(2024, 7, 1).isoformat()
