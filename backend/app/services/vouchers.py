"""One voucher as synced (FR-DD-1's last level) and an entity's audit history (LOG-1.2).

Read-only display: amounts are the normalized absolute amounts with their direction
(ACC-DATA-1), custom fields are shown and never summed (DR-UDF-2). Every query is scoped to
the authorised company (SEC-1.7): another company's voucher is simply not found."""

import uuid
from collections import defaultdict
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError
from app.core.permissions import CompanyContext
from app.models.config import AuditLog, CustomFieldMapping
from app.models.enums import AccountingDirection, CollectionType
from app.models.masters import CostCentre, Ledger, StockItem, VoucherType
from app.models.vouchers import (
    BillAllocation,
    CostCentreAllocation,
    Voucher,
    VoucherEntry,
    VoucherItem,
)
from app.schemas.vouchers import (
    AuditEntryOut,
    BillOut,
    CentreOut,
    CustomFieldOut,
    Direction,
    EntryOut,
    ItemOut,
    VoucherDetailOut,
)
from tally_contract.errors import ErrorCode


def _dr_cr(direction: str) -> Direction:
    return "Dr" if direction == AccountingDirection.DEBIT else "Cr"


async def detail(
    session: AsyncSession, ctx: CompanyContext, voucher_id: uuid.UUID
) -> VoucherDetailOut:
    company = ctx.company_id
    found = (
        await session.execute(
            select(Voucher, VoucherType.name, VoucherType.base_voucher_type)
            .join(
                VoucherType,
                (VoucherType.company_id == Voucher.company_id)
                & (VoucherType.voucher_type_id == Voucher.voucher_type_id),
            )
            .where(Voucher.company_id == company, Voucher.voucher_id == voucher_id)
        )
    ).first()
    if found is None:
        raise AppError(ErrorCode.NOT_FOUND, "Voucher not found", 404)
    voucher, type_name, base = found

    entries = (
        await session.execute(
            select(VoucherEntry, Ledger.name)
            .join(
                Ledger,
                (Ledger.company_id == VoucherEntry.company_id)
                & (Ledger.ledger_id == VoucherEntry.ledger_id),
            )
            .where(VoucherEntry.company_id == company, VoucherEntry.voucher_id == voucher_id)
            .order_by(VoucherEntry.line_sequence)
        )
    ).all()
    entry_ids = [e.voucher_entry_id for e, _ in entries]
    bills: dict[int, list[BillOut]] = defaultdict(list)
    for b in await session.scalars(
        select(BillAllocation)
        .where(BillAllocation.company_id == company, BillAllocation.voucher_entry_id.in_(entry_ids))
        .order_by(BillAllocation.id)
    ):
        bills[b.voucher_entry_id].append(
            BillOut(
                allocation_type=b.allocation_type,
                reference_name=b.reference_name,
                due_date=b.due_date,
                amount=b.amount_absolute,
                direction=_dr_cr(b.accounting_direction),
            )
        )
    centres: dict[int, list[CentreOut]] = defaultdict(list)
    for a, centre_name in (
        await session.execute(
            select(CostCentreAllocation, CostCentre.name)
            .join(
                CostCentre,
                (CostCentre.company_id == CostCentreAllocation.company_id)
                & (CostCentre.cost_centre_id == CostCentreAllocation.cost_centre_id),
            )
            .where(
                CostCentreAllocation.company_id == company,
                CostCentreAllocation.voucher_entry_id.in_(entry_ids),
            )
            .order_by(CostCentreAllocation.id)
        )
    ).tuples():
        centres[a.voucher_entry_id].append(
            CentreOut(
                cost_centre_id=a.cost_centre_id,
                cost_centre_name=centre_name,
                amount=a.amount_absolute,
            )
        )
    items = (
        await session.execute(
            select(VoucherItem, StockItem.name)
            .join(
                StockItem,
                (StockItem.company_id == VoucherItem.company_id)
                & (StockItem.stock_item_id == VoucherItem.stock_item_id),
            )
            .where(VoucherItem.company_id == company, VoucherItem.voucher_id == voucher_id)
            .order_by(VoucherItem.id)
        )
    ).tuples()
    return VoucherDetailOut(
        voucher_id=voucher.voucher_id,
        tally_guid=voucher.tally_guid,
        alter_id=voucher.alter_id,
        voucher_number=voucher.voucher_number,
        voucher_date=voucher.voucher_date,
        voucher_type_name=type_name,
        base_voucher_type=base,
        status=voucher.status,
        narration=voucher.narration,
        last_synced_at=voucher.last_synced_at,
        entries=[
            EntryOut(
                line=e.line_sequence,
                ledger_id=e.ledger_id,
                ledger_name=ledger_name,
                direction=_dr_cr(e.accounting_direction),
                amount=e.amount_absolute,
                bills=bills[e.voucher_entry_id],
                cost_centres=centres[e.voucher_entry_id],
            )
            for e, ledger_name in entries
        ],
        items=[
            ItemOut(
                stock_item_id=i.stock_item_id,
                stock_item_name=item_name,
                quantity=i.quantity,
                unit=i.unit,
                rate=i.rate,
                amount=i.amount,
                custom_fields=i.custom_fields,
            )
            for i, item_name in items
        ],
        custom_fields=await _custom_fields(session, company, voucher.custom_fields or {}),
    )


async def _custom_fields(
    session: AsyncSession, company_id: uuid.UUID, values: dict[str, Any]
) -> list[CustomFieldOut]:
    """Mapped fields first, in the mapping's key order, each with its Tally field; then any
    stored value whose mapping has since been removed."""
    found = await session.execute(
        select(CustomFieldMapping.field_key, CustomFieldMapping.tally_field).where(
            CustomFieldMapping.company_id == company_id,
            CustomFieldMapping.collection_type == CollectionType.VOUCHER,
        )
    )
    mapped = {key: field for key, field in found.tuples()}
    keys = sorted(values, key=lambda k: (k not in mapped, k))
    return [CustomFieldOut(field_key=k, tally_field=mapped.get(k), value=values[k]) for k in keys]


async def history(
    session: AsyncSession,
    ctx: CompanyContext,
    entity_type: str,
    entity_id: str,
    limit: int,
    offset: int,
) -> list[AuditEntryOut]:
    """An entity's audit entries in this company, newest first."""
    rows = await session.scalars(
        select(AuditLog)
        .where(
            AuditLog.company_id == ctx.company_id,
            AuditLog.entity_type == entity_type,
            AuditLog.entity_id == entity_id,
        )
        .order_by(AuditLog.created_at.desc(), AuditLog.id.desc())
        .limit(limit)
        .offset(offset)
    )
    return [
        AuditEntryOut(
            id=r.id,
            created_at=r.created_at,
            user_id=r.user_id,
            action=r.action,
            entity_type=r.entity_type,
            entity_id=r.entity_id,
            before=r.before_value,
            after=r.after_value,
            data_range=r.data_range,
            result=r.result,
        )
        for r in rows
    ]
