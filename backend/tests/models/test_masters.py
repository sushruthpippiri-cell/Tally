"""P1.4: masters (SRS 5.5 + D-001)."""

import pytest
from sqlalchemy import delete, text, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.masters import CostCentre, Group, Ledger, StockItem, VoucherType
from tests.factories import (
    db_error,
    make_company,
    make_cost_centre,
    make_group,
    make_ledger,
    make_predefined_groups,
    make_stock_item,
    make_voucher_type,
)

MASTERS = [Group, Ledger, VoucherType, StockItem, CostCentre]


async def _one_of_each(session: AsyncSession) -> dict[type, object]:
    company = await make_company(session)
    groups = await make_predefined_groups(session, company)
    return {
        Group: groups["Sundry Debtors"],
        Ledger: await make_ledger(session, company, "Sharma Traders", groups["Sundry Debtors"]),
        VoucherType: await make_voucher_type(session, company, "Sales"),
        StockItem: await make_stock_item(session, company, "Widget"),
        CostCentre: await make_cost_centre(session, company, "Head Office"),
    }


@pytest.mark.req("DR-ML-1")
@pytest.mark.parametrize("model", MASTERS, ids=lambda m: m.__tablename__)
async def test_masters_cannot_be_deleted(session: AsyncSession, model: type) -> None:
    """Sync runs as the app role: DELETE hits the trigger, TRUNCATE lacks the privilege."""
    await _one_of_each(session)
    async with db_error(session, "DR-ML-1"):
        await session.execute(delete(model))
    async with db_error(session, "permission denied"):
        await session.execute(text(f"TRUNCATE {model.__tablename__} CASCADE"))


async def test_master_lifecycle_is_a_status_change(session: AsyncSession) -> None:
    ledger = (await _one_of_each(session))[Ledger]
    assert isinstance(ledger, Ledger)
    await session.execute(
        update(Ledger).where(Ledger.ledger_id == ledger.ledger_id).values(status="MISSING_IN_TALLY")
    )


@pytest.mark.parametrize(
    "table", ["groups", "ledgers", "voucher_types", "stock_items", "cost_centres"]
)
async def test_unknown_master_status_rejected(session: AsyncSession, table: str) -> None:
    await _one_of_each(session)
    async with db_error(session, f"ck_{table}_status"):
        await session.execute(text(f"UPDATE {table} SET status = 'DELETED'"))


async def test_twenty_eight_predefined_groups_anchor_to_themselves(session: AsyncSession) -> None:
    groups = await make_predefined_groups(session, await make_company(session))
    assert len(groups) == 28
    debtors, current_assets = groups["Sundry Debtors"], groups["Current Assets"]
    assert debtors.classification_group_id == debtors.group_id  # D-001 example 2
    assert debtors.primary_group_id == current_assets.group_id
    assert debtors.nature == "ASSET"


async def test_reserved_name_is_unique_per_company(session: AsyncSession) -> None:
    a, b = await make_company(session), await make_company(session)
    await make_predefined_groups(session, a)
    await make_predefined_groups(session, b)  # every company has its own copy
    async with db_error(session, "uq_groups_company_id_reserved_name"):
        await session.execute(
            text(
                "INSERT INTO groups (company_id, tally_guid, alter_id, status, name, "
                "reserved_name, is_predefined, resolution_status) VALUES "
                "(:c, 'dup', 1, 'ACTIVE', 'x', 'Sundry Debtors', true, 'UNRESOLVED_GROUP')"
            ),
            {"c": a.company_id},
        )


async def test_user_groups_have_no_reserved_name_constraint(session: AsyncSession) -> None:
    company = await make_company(session)
    groups = await make_predefined_groups(session, company)
    await make_group(session, company, "Retail", groups["Sundry Debtors"])
    await make_group(session, company, "Retail 2", groups["Sundry Debtors"])  # NULLs don't clash


@pytest.mark.parametrize("missing", ["classification_group_id", "nature"])
async def test_resolved_group_needs_anchor_and_nature(session: AsyncSession, missing: str) -> None:
    company = await make_company(session)
    groups = await make_predefined_groups(session, company)
    group = await make_group(session, company, "Retail", groups["Sundry Debtors"])
    async with db_error(session, "ck_groups_resolved_has_anchor"):
        await session.execute(
            update(Group).where(Group.group_id == group.group_id).values({missing: None})
        )


async def test_unresolved_group_may_lack_anchor(session: AsyncSession) -> None:
    company = await make_company(session)
    session.add(
        Group(
            company_id=company.company_id,
            tally_guid="orphan",
            alter_id=1,
            status="ACTIVE",
            name="Project X",
            is_predefined=False,
            parent_tally_guid="not-synced-yet",
            resolution_status="UNRESOLVED_GROUP",
        )
    )
    await session.flush()


async def test_ledger_cannot_point_at_another_companys_group(session: AsyncSession) -> None:
    a, b = await make_company(session), await make_company(session)
    b_groups = await make_predefined_groups(session, b)
    async with db_error(session, "fk_ledgers_company_id_group_id"):
        session.add(
            Ledger(
                company_id=a.company_id,
                tally_guid="l1",
                alter_id=1,
                status="ACTIVE",
                name="Leak",
                group_id=b_groups["Sundry Debtors"].group_id,
            )
        )
        await session.flush()


async def test_voucher_type_base_inherits_from_parent(session: AsyncSession) -> None:
    company = await make_company(session)
    sales = await make_voucher_type(session, company, "Sales")
    pos = await make_voucher_type(session, company, "POS Invoice", parent=sales)
    assert (pos.base_voucher_type, pos.reserved_name) == ("SALES", None)
    async with db_error(session, "ck_voucher_types_base_voucher_type"):
        await session.execute(
            update(VoucherType)
            .where(VoucherType.voucher_type_id == pos.voucher_type_id)
            .values(base_voucher_type="POS")
        )


def test_ledgers_have_no_closing_balance_column() -> None:
    """SRS 5.5: balances are computed, never stored."""
    assert not any("closing" in c for c in Ledger.__table__.c.keys())
