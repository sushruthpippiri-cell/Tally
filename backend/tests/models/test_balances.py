"""P1.5: opening balances, stock snapshots and opening bill allocations (SRS 5.6, D-022)."""

from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.balances import OpeningBillAllocation, StockOpeningBalance, StockSnapshot
from app.models.company import Company
from app.models.masters import Ledger
from tests.factories import (
    db_error,
    make_company,
    make_ledger,
    make_opening_balance,
    make_predefined_groups,
    make_stock_item,
)


async def _ledger(session: AsyncSession) -> tuple[Company, Ledger]:
    company = await make_company(session)
    groups = await make_predefined_groups(session, company)
    return company, await make_ledger(session, company, "Sharma", groups["Sundry Debtors"])


async def test_ledger_opening_is_one_per_financial_year(session: AsyncSession) -> None:
    company, ledger = await _ledger(session)
    await make_opening_balance(session, company, ledger, "DEBIT", "5000")
    await make_opening_balance(session, company, ledger, "DEBIT", "7000", date(2025, 4, 1))
    async with db_error(session, "pk_ledger_opening_balances"):
        await make_opening_balance(session, company, ledger, "CREDIT", "1")


@pytest.mark.parametrize(
    ("direction", "amount", "constraint"),
    [("DEBIT", "-1", "amount_absolute"), ("DR", "1", "accounting_direction")],
)
async def test_ledger_opening_is_normalized(
    session: AsyncSession, direction: str, amount: str, constraint: str
) -> None:
    company, ledger = await _ledger(session)
    async with db_error(session, f"ck_ledger_opening_balances_{constraint}"):
        await session.execute(
            text("INSERT INTO ledger_opening_balances VALUES (:c, :l, '2024-04-01', :a, :d)"),
            {"c": company.company_id, "l": ledger.ledger_id, "a": Decimal(amount), "d": direction},
        )


async def test_stock_opening_and_snapshot_keys(session: AsyncSession) -> None:
    company = await make_company(session)
    item = await make_stock_item(session, company, "Widget")
    fy = company.financial_year_start
    common = {"company_id": company.company_id, "stock_item_id": item.stock_item_id}
    session.add(StockOpeningBalance(**common, financial_year_start=fy, quantity=Decimal("10.5")))
    session.add(StockSnapshot(**common, as_of_date=date(2024, 9, 30), closing_quantity=Decimal(3)))
    await session.flush()
    async with db_error(session, "pk_stock_snapshots"):
        session.add(StockSnapshot(**common, as_of_date=date(2024, 9, 30), closing_quantity=1))
        await session.flush()


async def test_opening_bill_is_unique_per_ledger_year_and_reference(session: AsyncSession) -> None:
    company, ledger = await _ledger(session)

    def bill() -> OpeningBillAllocation:
        return OpeningBillAllocation(
            company_id=company.company_id,
            ledger_id=ledger.ledger_id,
            financial_year_start=company.financial_year_start,
            reference_name="INV-1",
            amount_absolute=Decimal("100"),
            accounting_direction="DEBIT",
        )

    session.add(bill())
    await session.flush()
    async with db_error(session, "uq_opening_bill_allocations_bill"):
        session.add(bill())
        await session.flush()


@pytest.mark.req("SEC-1.7")
async def test_opening_balance_cannot_cross_companies(session: AsyncSession) -> None:
    _, ledger = await _ledger(session)
    other = await make_company(session)
    async with db_error(session, "fk_ledger_opening_balances_company_id_ledger_id"):
        await make_opening_balance(session, other, ledger, "DEBIT", "1")
