"""Masters as resolved (P6.7, SRS 19.2): groups and voucher types, company-scoped (SEC-1.7)."""

import uuid
from typing import Literal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from app.analytics.classification import load_classes
from app.core.permissions import CompanyContext, scoped
from app.models.masters import CostCentre, Group, Ledger, StockItem, VoucherType
from app.schemas.masters import GroupOut, OptionOut, VoucherTypeOut

OptionKind = Literal["customer", "product", "cost_centre"]
MAX_OPTIONS = 50


async def groups(session: AsyncSession, ctx: CompanyContext) -> list[GroupOut]:
    predefined, anchor, primary = aliased(Group), aliased(Group), aliased(Group)
    rows = await session.execute(
        scoped(select(Group, predefined.name, anchor.name, primary.name), Group, ctx)
        .outerjoin(predefined, predefined.group_id == Group.predefined_group_id)
        .outerjoin(anchor, anchor.group_id == Group.classification_group_id)
        .outerjoin(primary, primary.group_id == Group.primary_group_id)
        .order_by(Group.name)
    )
    return [
        GroupOut(
            group_id=g.group_id,
            name=g.name,
            tally_guid=g.tally_guid,
            parent_group_id=g.parent_group_id,
            is_predefined=g.is_predefined,
            reserved_name=g.reserved_name,
            predefined_group=predefined_name,
            anchor=anchor_name,
            primary_group=primary_name,
            nature=g.nature,
            resolution_status=g.resolution_status,
            status=g.status,
        )
        for g, predefined_name, anchor_name, primary_name in rows.tuples()
    ]


async def voucher_types(session: AsyncSession, ctx: CompanyContext) -> list[VoucherTypeOut]:
    rows = await session.execute(
        scoped(select(VoucherType), VoucherType, ctx).order_by(VoucherType.name)
    )
    return [
        VoucherTypeOut(
            voucher_type_id=t.voucher_type_id,
            name=t.name,
            tally_guid=t.tally_guid,
            parent_voucher_type_id=t.parent_voucher_type_id,
            reserved_name=t.reserved_name,
            base_voucher_type=t.base_voucher_type,
            resolution_status=t.resolution_status,
            status=t.status,
        )
        for t in rows.scalars()
    ]


async def options(
    session: AsyncSession,
    ctx: CompanyContext,
    kind: OptionKind,
    q: str | None,
    option_id: uuid.UUID | None,
) -> list[OptionOut]:
    """Choices for an FR-4.3 filter: customers (ledgers anchored at Sundry Debtors, D-001),
    products (stock items) or cost centres, by name; `q` matches anywhere in the name, `id`
    finds one (a shared link carries only the id)."""
    model: type[Ledger] | type[StockItem] | type[CostCentre]
    if kind == "customer":
        customers = (await load_classes(session, ctx.company_id)).customer
        model, key, where = (
            Ledger,
            Ledger.ledger_id,
            [Ledger.classification_group_id.in_(customers)],
        )
    elif kind == "product":
        model, key, where = StockItem, StockItem.stock_item_id, []
    else:
        model, key, where = CostCentre, CostCentre.cost_centre_id, []
    stmt = scoped(select(key, model.name), model, ctx).where(*where)
    if q:
        stmt = stmt.where(model.name.icontains(q, autoescape=True))
    if option_id is not None:
        stmt = stmt.where(key == option_id)
    rows = await session.execute(stmt.order_by(model.name, key).limit(MAX_OPTIONS))
    return [OptionOut(id=i, name=name) for i, name in rows.tuples()]
