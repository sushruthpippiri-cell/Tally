"""P1.10: the shared factories build data the way later phases expect (D-001, SRS 5.8)."""

from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.balances import LedgerOpeningBalance
from app.models.defaults import PREDEFINED_GROUP_NAMES
from app.models.vouchers import BillAllocation, VoucherItem
from tests.factories import (
    make_company,
    make_group,
    make_ledger,
    make_predefined_groups,
    make_stock_item,
    make_voucher,
    make_voucher_type,
)


async def test_predefined_groups_match_the_shared_list(session: AsyncSession) -> None:
    groups = await make_predefined_groups(session, await make_company(session))
    assert set(groups) == PREDEFINED_GROUP_NAMES
    assert all(g.reserved_name == name and g.is_predefined for name, g in groups.items())


async def test_nested_user_groups_roll_up_to_the_predefined_anchor(session: AsyncSession) -> None:
    """D-001 example 1: Amazon Sales -> Marketplace -> Online -> Sales Accounts."""
    company = await make_company(session)
    groups = await make_predefined_groups(session, company)
    online = await make_group(session, company, "Sales - Online", groups["Sales Accounts"])
    market = await make_group(session, company, "Sales - Online - Marketplace", online)
    ledger = await make_ledger(session, company, "Amazon Sales", market)
    assert ledger.classification_group_id == groups["Sales Accounts"].group_id
    assert ledger.group_id == market.group_id  # the immediate parent is never the anchor


async def test_user_top_level_group_is_its_own_anchor(session: AsyncSession) -> None:
    """D-001 example 3: a group directly under Primary, nature from Tally (G14)."""
    company = await make_company(session)
    schemes = await make_group(session, company, "Government Schemes", None, nature="ASSET")
    assert schemes.classification_group_id == schemes.group_id
    assert (schemes.predefined_group_id, schemes.primary_group_id) == (None, None)
    with pytest.raises(ValueError, match="nature"):
        await make_group(session, company, "No Nature", None)


async def test_ledger_opening_defaults_to_company_fy_start(session: AsyncSession) -> None:
    company = await make_company(session, fy_start=date(2025, 4, 1))
    groups = await make_predefined_groups(session, company)
    ledger = await make_ledger(
        session, company, "Cash", groups["Cash-in-Hand"], opening=("DEBIT", "1500.25")
    )
    opening = await session.get(LedgerOpeningBalance, (ledger.ledger_id, date(2025, 4, 1)))
    assert opening is not None
    assert (opening.accounting_direction, opening.amount_absolute) == ("DEBIT", Decimal("1500.25"))


@pytest.mark.parametrize(
    ("name", "base"),
    [("Sales", "SALES"), ("Credit Note", "CREDIT_NOTE"), ("Stock Journal", "OTHER")],
)
async def test_voucher_type_base_from_name(session: AsyncSession, name: str, base: str) -> None:
    vtype = await make_voucher_type(session, await make_company(session), name)
    assert vtype.base_voucher_type == base


async def test_voucher_with_items_and_bills(session: AsyncSession) -> None:
    company = await make_company(session)
    groups = await make_predefined_groups(session, company)
    await make_ledger(session, company, "Customer A", groups["Sundry Debtors"])
    await make_ledger(session, company, "Sales", groups["Sales Accounts"])
    await make_stock_item(session, company, "Widget")
    voucher = await make_voucher(
        session,
        company,
        await make_voucher_type(session, company, "Sales"),
        date(2024, 6, 1),
        items=[("Widget", "4", "2500", "10000")],
        bills=[(0, "NEW_REF", "INV-7", "10000")],
    )
    item = await session.scalar(
        select(VoucherItem).where(VoucherItem.voucher_id == voucher.voucher_id)
    )
    assert item is not None and (item.quantity, item.amount, item.unit) == (4, 10000, "Nos")
    bill = await session.scalar(select(BillAllocation))
    assert bill is not None
    assert (bill.accounting_direction, bill.reference_name) == ("DEBIT", "INV-7")  # from entry 0
    assert await session.scalar(select(func.count()).select_from(BillAllocation)) == 1


async def test_voucher_with_unknown_ledger_fails_loudly(session: AsyncSession) -> None:
    company = await make_company(session)
    with pytest.raises(LookupError, match="Customer A"):
        await make_voucher(
            session, company, await make_voucher_type(session, company, "Sales"), date(2024, 6, 1)
        )
