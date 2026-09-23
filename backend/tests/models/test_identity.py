"""Record identity is (company_id, tally_guid) on every synced table (SRS 6.6)."""

from datetime import date

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.masters import VoucherType
from tests.factories import (
    db_error,
    make_company,
    make_cost_centre,
    make_group,
    make_ledger,
    make_predefined_groups,
    make_stock_item,
    make_voucher,
    make_voucher_type,
)

SYNCED = {  # table -> primary key
    "groups": "group_id",
    "ledgers": "ledger_id",
    "voucher_types": "voucher_type_id",
    "stock_items": "stock_item_id",
    "cost_centres": "cost_centre_id",
    "vouchers": "voucher_id",
}


async def _books(session: AsyncSession, guid: str) -> str:
    """One row per synced table, every one with tally_guid = `guid`. Returns the company id."""
    company = await make_company(session)
    groups = await make_predefined_groups(session, company)
    rows = [
        await make_group(session, company, "Retail", groups["Sundry Debtors"]),
        await make_ledger(session, company, "Customer A", groups["Sundry Debtors"]),
        await make_ledger(session, company, "Sales", groups["Sales Accounts"]),
        await make_voucher_type(session, company, "Sales"),
        await make_stock_item(session, company, "Widget"),
        await make_cost_centre(session, company, "HO"),
    ]
    vtype = rows[3]
    assert isinstance(vtype, VoucherType)
    rows.append(await make_voucher(session, company, vtype, date(2024, 5, 1), number="1"))
    for row in [rows[0], rows[1], rows[3], rows[4], rows[5], rows[6]]:
        row.tally_guid = guid
    await session.flush()
    return str(company.company_id)


@pytest.mark.req("DR-4.1", "DR-4.2", "DR-4.4", "DR-4.6")
@pytest.mark.parametrize("table", SYNCED)
async def test_guid_unique_per_company_not_globally(session: AsyncSession, table: str) -> None:
    company_id = await _books(session, "shared-guid")
    await _books(session, "shared-guid")  # same GUIDs in another company: accepted
    # Copy the row with a fresh primary key, so only (company_id, tally_guid) can clash.
    async with db_error(session, f"uq_{table}_company_id_tally_guid"):
        await session.execute(
            text(
                f"INSERT INTO {table} SELECT (jsonb_populate_record(NULL::{table}, "
                f"to_jsonb(x) || jsonb_build_object('{SYNCED[table]}', gen_random_uuid()))).* "
                f"FROM {table} x WHERE company_id = :c AND tally_guid = 'shared-guid'"
            ),
            {"c": company_id},
        )


@pytest.mark.req("DR-4.1", "DR-4.4")
async def test_voucher_number_is_not_an_identity(session: AsyncSession) -> None:
    """The same number twice in one company (reused across years) and in two companies."""
    company = await make_company(session)
    groups = await make_predefined_groups(session, company)
    await make_ledger(session, company, "Customer A", groups["Sundry Debtors"])
    await make_ledger(session, company, "Sales", groups["Sales Accounts"])
    sales = await make_voucher_type(session, company, "Sales")
    await make_voucher(session, company, sales, date(2024, 5, 1), number="1")
    await make_voucher(session, company, sales, date(2025, 5, 1), number="1")
    await _books(session, "another")  # a second company also has voucher number "1"
