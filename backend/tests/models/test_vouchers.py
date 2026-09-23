"""P1.6: vouchers and child rows (SRS 5.7, 5.8, 6.9; D-003, D-004)."""

from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import delete, func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.company import Company
from app.models.masters import VoucherType
from app.models.vouchers import BillAllocation, Voucher, VoucherEntry, VoucherItem
from tests.factories import (
    db_error,
    make_company,
    make_ledger,
    make_predefined_groups,
    make_stock_item,
    make_voucher,
    make_voucher_type,
)

D = date(2024, 5, 10)


async def _books(session: AsyncSession) -> tuple[Company, VoucherType]:
    company = await make_company(session)
    groups = await make_predefined_groups(session, company)
    await make_ledger(session, company, "Customer A", groups["Sundry Debtors"])
    await make_ledger(session, company, "Sales", groups["Sales Accounts"])
    await make_stock_item(session, company, "Widget")
    return company, await make_voucher_type(session, company, "Sales")


async def _entry_id(session: AsyncSession, voucher: Voucher) -> int:
    entry_id = await session.scalar(
        select(VoucherEntry.voucher_entry_id).where(VoucherEntry.voucher_id == voucher.voucher_id)
    )
    assert entry_id is not None
    return entry_id


async def test_factory_fills_normalized_fields(session: AsyncSession) -> None:
    company, sales = await _books(session)
    voucher = await make_voucher(session, company, sales, D)
    rows = (
        await session.execute(
            select(
                VoucherEntry.accounting_direction,
                VoucherEntry.is_debit,
                VoucherEntry.amount_absolute,
                VoucherEntry.amount_signed,
            )
            .where(VoucherEntry.voucher_id == voucher.voucher_id)
            .order_by(VoucherEntry.line_sequence)
        )
    ).all()
    assert [tuple(r) for r in rows] == [
        ("DEBIT", True, Decimal("10000"), Decimal("10000")),
        ("CREDIT", False, Decimal("10000"), Decimal("-10000")),
    ]


async def test_factory_refuses_unbalanced_voucher(session: AsyncSession) -> None:
    company, sales = await _books(session)
    with pytest.raises(ValueError, match="unbalanced"):
        await make_voucher(
            session,
            company,
            sales,
            D,
            entries=[("Customer A", "DEBIT", "100"), ("Sales", "CREDIT", "99.99")],
        )


@pytest.mark.parametrize(
    ("columns", "constraint"),
    [
        ("'DEBIT', true, -5, -5", "amount_absolute"),  # negative absolute
        ("'DEBIT', true, 5, -5", "amount_signed"),  # debit must be positive
        ("'CREDIT', false, 5, 5", "amount_signed"),  # credit must be negative
        ("'CREDIT', true, 5, -5", "is_debit"),  # is_debit disagrees with direction
        ("'DR', true, 5, 5", "accounting_direction"),
    ],
)
async def test_entry_checks(session: AsyncSession, columns: str, constraint: str) -> None:
    company, sales = await _books(session)
    voucher = await make_voucher(session, company, sales, D)
    ledger_id = await session.scalar(
        select(VoucherEntry.ledger_id).where(VoucherEntry.voucher_id == voucher.voucher_id)
    )
    async with db_error(session, f"ck_voucher_entries_{constraint}"):
        await session.execute(
            text(
                "INSERT INTO voucher_entries (company_id, voucher_id, ledger_id, line_sequence, "
                "amount_raw, accounting_direction, is_debit, amount_absolute, amount_signed) "
                f"VALUES (:c, :v, :l, 9, 'raw', {columns})"
            ),
            {"c": company.company_id, "v": voucher.voucher_id, "l": ledger_id},
        )


@pytest.mark.parametrize("bad", ["DELETED", "active"])
async def test_unknown_voucher_status_rejected(session: AsyncSession, bad: str) -> None:
    company, sales = await _books(session)
    await make_voucher(session, company, sales, D)
    async with db_error(session, "ck_vouchers_status"):
        await session.execute(text("UPDATE vouchers SET status = :s"), {"s": bad})


async def test_unknown_allocation_type_rejected(session: AsyncSession) -> None:
    company, sales = await _books(session)
    voucher = await make_voucher(
        session, company, sales, D, bills=[(0, "NEW_REF", "INV-1", "10000")]
    )
    async with db_error(session, "ck_bill_allocations_allocation_type"):
        await session.execute(
            text("UPDATE bill_allocations SET allocation_type = 'New Ref'"),
        )
    assert voucher.voucher_id


async def test_vouchers_cannot_be_deleted(session: AsyncSession) -> None:
    """SRS 5.1-5 (no requirement ID): vouchers are never hard-deleted."""
    company, sales = await _books(session)
    await make_voucher(session, company, sales, D, status="CANCELLED")
    async with db_error(session, "never deleted"):
        await session.execute(delete(Voucher))


async def test_child_rows_can_be_replaced(session: AsyncSession) -> None:
    """The schema allows SRS 6.9 child replacement (children delete and cascade, the header
    stays). DR-VE-3/4 themselves are sync behaviour, proven in P5."""
    company, sales = await _books(session)
    voucher = await make_voucher(
        session,
        company,
        sales,
        D,
        items=[("Widget", "2", "5000", "10000")],
        bills=[(0, "NEW_REF", "INV-1", "10000")],
    )
    await session.execute(delete(VoucherEntry).where(VoucherEntry.voucher_id == voucher.voucher_id))
    await session.execute(delete(VoucherItem).where(VoucherItem.voucher_id == voucher.voucher_id))
    assert await session.scalar(select(func.count()).select_from(BillAllocation)) == 0  # cascade
    assert await session.scalar(select(func.count()).select_from(Voucher)) == 1


async def test_entry_cannot_use_another_companys_ledger(session: AsyncSession) -> None:
    company, sales = await _books(session)
    voucher = await make_voucher(session, company, sales, D)
    other, _ = await _books(session)
    foreign_ledger = await session.scalar(
        text("SELECT ledger_id FROM ledgers WHERE company_id = :c LIMIT 1"),
        {"c": other.company_id},
    )
    async with db_error(session, "fk_voucher_entries_company_id_ledger_id"):
        session.add(
            VoucherEntry(
                company_id=company.company_id,
                voucher_id=voucher.voucher_id,
                ledger_id=foreign_ledger,
                line_sequence=5,
                amount_raw="1",
                is_debit=True,
                amount_absolute=Decimal(1),
                amount_signed=Decimal(1),
                accounting_direction="DEBIT",
            )
        )
        await session.flush()
    assert await _entry_id(session, voucher)


async def test_voucher_date_is_a_date(session: AsyncSession) -> None:
    """D-020: no time component, so no timezone can shift it."""
    assert Voucher.__table__.c.voucher_date.type.python_type is date
