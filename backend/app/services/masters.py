"""Masters as resolved (P6.7, SRS 19.2): groups and voucher types, company-scoped (SEC-1.7)."""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from app.core.permissions import CompanyContext, scoped
from app.models.masters import Group, VoucherType
from app.schemas.masters import GroupOut, VoucherTypeOut


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
