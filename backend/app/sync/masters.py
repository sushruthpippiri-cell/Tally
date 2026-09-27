"""Master upserts with stale-record protection (P5.3, SYNC-3.x, DR-4.2).

Every record is compared with the stored ALTERID for its (company_id, GUID): lower -> rejected
and STALE_ALTERID logged (SYNC-3.2); equal -> nothing (SYNC-3.3); higher -> applied (SYNC-3.4).
The pre-read decides what to log; `ON CONFLICT ... WHERE stored.alter_id < incoming.alter_id`
makes the database enforce the rule even if two writers raced. Each record is written in its
own SAVEPOINT, so one failing record never takes its chunk with it (D-039 #7).
"""

import uuid
from typing import Any

from sqlalchemy import delete, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from app.models.balances import LedgerOpeningBalance, OpeningBillAllocation, StockOpeningBalance
from app.models.company import Company
from app.models.defaults import PREDEFINED_GROUP_NAMES
from app.models.enums import (
    BaseVoucherType,
    CollectionType,
    GroupResolution,
    MasterStatus,
    VoucherTypeResolution,
)
from app.models.masters import CostCentre, Group, Ledger, StockItem, VoucherType
from app.sync import lifecycle
from app.sync.context import ChunkOutcome, IngestContext, RecordFailure
from tally_contract.errors import ErrorCode
from tally_contract.records import (
    CompanyRecord,
    CostCentreRecord,
    GroupRecord,
    LedgerRecord,
    StockItemRecord,
    VoucherTypeRecord,
)

MODELS: dict[CollectionType, Any] = {
    CollectionType.GROUP: Group,
    CollectionType.LEDGER: Ledger,
    CollectionType.VOUCHER_TYPE: VoucherType,
    CollectionType.STOCK_ITEM: StockItem,
    CollectionType.COST_CENTRE: CostCentre,
}
PK = {
    Group: Group.group_id,
    Ledger: Ledger.ledger_id,
    VoucherType: VoucherType.voucher_type_id,
    StockItem: StockItem.stock_item_id,
    CostCentre: CostCentre.cost_centre_id,
}


async def stored_alter_ids(
    session: AsyncSession, model: Any, company_id: uuid.UUID, guids: list[str]
) -> dict[str, int]:
    rows = await session.execute(
        select(model.tally_guid, model.alter_id).where(
            model.company_id == company_id, model.tally_guid.in_(guids)
        )
    )
    return {guid: int(alter_id) for guid, alter_id in rows.tuples()}


async def _upsert(
    session: AsyncSession, model: Any, values: dict[str, Any], insert_only: dict[str, Any]
) -> uuid.UUID | None:
    """Insert, or update only when the incoming ALTERID is higher. Returns the primary key if
    the row was written."""
    stmt = insert(model).values(**values, **insert_only)
    updates = {k: stmt.excluded[k] for k in values if k not in ("company_id", "tally_guid")}
    upsert = stmt.on_conflict_do_update(
        index_elements=[model.company_id, model.tally_guid],
        set_=updates,
        where=model.alter_id < stmt.excluded.alter_id,
    ).returning(PK[model])
    written: uuid.UUID | None = (await session.execute(upsert)).scalar_one_or_none()
    return written


async def _guid_by_name(
    session: AsyncSession, model: Any, company_id: uuid.UUID, name: str | None
) -> str | None:
    """D-002 fallback: when the TDL gave no parent GUID, the exact name among stored masters."""
    if not name:
        return None
    guid: str | None = await session.scalar(
        select(model.tally_guid).where(model.company_id == company_id, model.name == name)
    )
    return guid


def _common(ctx: IngestContext, record: Any) -> dict[str, Any]:
    return {
        "company_id": ctx.company_id,
        "tally_guid": record.guid,
        "alter_id": record.alter_id,
        "name": record.name,
        "last_synced_at": ctx.now,
    }


async def _group(session: AsyncSession, ctx: IngestContext, r: GroupRecord) -> None:
    parent = r.parent_guid or await _guid_by_name(session, Group, ctx.company_id, r.parent_name)
    # GATE-G32: the reserved name identifies a predefined group; until G32 passes the 28
    # default names stand in for it (D-001).
    reserved = r.reserved_name or (r.name if r.name in PREDEFINED_GROUP_NAMES else None)
    await _upsert(
        session,
        Group,
        _common(ctx, r)
        | {
            "parent_tally_guid": parent,
            "reserved_name": reserved,
            "is_predefined": reserved is not None,
        },
        # D-039 #4: P6's resolver sets the anchor, nature and status after the sync.
        {"status": MasterStatus.ACTIVE, "resolution_status": GroupResolution.UNRESOLVED_GROUP},
    )


async def _ledger(session: AsyncSession, ctx: IngestContext, r: LedgerRecord) -> None:
    assert ctx.books_from is not None  # the batch guard refuses ledgers until it is known
    parent = r.parent_group_guid or await _guid_by_name(
        session, Group, ctx.company_id, r.parent_group_name
    )
    ledger_id = await _upsert(
        session,
        Ledger,
        _common(ctx, r)
        | {
            "parent_group_tally_guid": parent,
            "is_bill_wise": r.is_bill_wise,
            "custom_fields": r.custom_fields or None,
        },
        {"status": MasterStatus.ACTIVE},
    )
    if ledger_id is None:
        return
    # Openings are as at books-beginning (D-039 #5, GATE-G16); replaced with the master.
    key = {"company_id": ctx.company_id, "ledger_id": ledger_id}
    await session.execute(
        delete(LedgerOpeningBalance).where(
            LedgerOpeningBalance.company_id == ctx.company_id,
            LedgerOpeningBalance.ledger_id == ledger_id,
            LedgerOpeningBalance.financial_year_start == ctx.books_from,
        )
    )
    if r.opening_balance is not None:
        session.add(
            LedgerOpeningBalance(
                **key,
                financial_year_start=ctx.books_from,
                amount_absolute=r.opening_balance.amount_absolute,
                accounting_direction=r.opening_balance.accounting_direction,
            )
        )
    await session.execute(
        delete(OpeningBillAllocation).where(
            OpeningBillAllocation.company_id == ctx.company_id,
            OpeningBillAllocation.ledger_id == ledger_id,
            OpeningBillAllocation.financial_year_start == ctx.books_from,
        )
    )
    for bill in r.opening_bills:
        session.add(
            OpeningBillAllocation(
                **key,
                reference_name=bill.reference_name,
                bill_date=bill.bill_date,
                due_date=bill.due_date,
                amount_absolute=bill.amount.amount_absolute,
                accounting_direction=bill.amount.accounting_direction,
                financial_year_start=ctx.books_from,
            )
        )
    await session.flush()


async def _voucher_type(session: AsyncSession, ctx: IngestContext, r: VoucherTypeRecord) -> None:
    parent = r.parent_guid or await _guid_by_name(
        session, VoucherType, ctx.company_id, r.parent_name
    )
    await _upsert(
        session,
        VoucherType,
        _common(ctx, r) | {"parent_tally_guid": parent, "reserved_name": r.reserved_name},
        {  # D-039 #4: P6 resolves the base type.
            "status": MasterStatus.ACTIVE,
            "base_voucher_type": BaseVoucherType.OTHER,
            "resolution_status": VoucherTypeResolution.UNRESOLVED,
        },
    )


async def _stock_item(session: AsyncSession, ctx: IngestContext, r: StockItemRecord) -> None:
    assert ctx.books_from is not None
    item_id = await _upsert(
        session,
        StockItem,
        _common(ctx, r) | {"base_unit": r.base_unit, "custom_fields": r.custom_fields or None},
        {"status": MasterStatus.ACTIVE},
    )
    if item_id is None:
        return
    await session.execute(
        delete(StockOpeningBalance).where(
            StockOpeningBalance.company_id == ctx.company_id,
            StockOpeningBalance.stock_item_id == item_id,
            StockOpeningBalance.financial_year_start == ctx.books_from,
        )
    )
    if r.opening_quantity is not None:
        session.add(
            StockOpeningBalance(
                company_id=ctx.company_id,
                stock_item_id=item_id,
                financial_year_start=ctx.books_from,
                quantity=r.opening_quantity,
                unit=r.base_unit,
                value=r.opening_value,
            )
        )
    await session.flush()


async def _cost_centre(session: AsyncSession, ctx: IngestContext, r: CostCentreRecord) -> None:
    await _upsert(session, CostCentre, _common(ctx, r), {"status": MasterStatus.ACTIVE})


WRITERS: dict[CollectionType, Any] = {
    CollectionType.GROUP: _group,
    CollectionType.LEDGER: _ledger,
    CollectionType.VOUCHER_TYPE: _voucher_type,
    CollectionType.STOCK_ITEM: _stock_item,
    CollectionType.COST_CENTRE: _cost_centre,
}


async def write_masters(
    session: AsyncSession, ctx: IngestContext, records: list[Any]
) -> ChunkOutcome:
    model = MODELS[ctx.collection]
    outcome = ChunkOutcome()
    guids = [r.guid for r in records]
    await lifecycle.restore(session, ctx.company_id, ctx.collection, guids, "pull")  # D-041 #4
    stored = await stored_alter_ids(session, model, ctx.company_id, guids)
    for record in records:
        before = stored.get(record.guid)
        if before is not None and record.alter_id < before:
            outcome.stale.append((record.guid, before, record.alter_id))
            continue
        if before is not None and record.alter_id == before:
            outcome.unchanged += 1
            continue
        try:
            async with session.begin_nested():
                await WRITERS[ctx.collection](session, ctx, record)
        except (DBAPIError, ValueError) as exc:
            outcome.failures.append(
                RecordFailure(record.guid, record.alter_id, ErrorCode.PARSE_ERROR, str(exc)[:1000])
            )
            continue
        outcome.written += 1
    await link_parents(session, ctx.company_id)
    return outcome


async def link_parents(session: AsyncSession, company_id: uuid.UUID) -> None:
    """Fill parent IDs whose parent has now arrived (in this chunk or an earlier one)."""
    parent = aliased(Group)
    await session.execute(
        update(Group)
        .where(
            Group.company_id == company_id,
            Group.parent_group_id.is_(None),
            Group.parent_tally_guid.is_not(None),
            parent.company_id == company_id,
            parent.tally_guid == Group.parent_tally_guid,
        )
        .values(parent_group_id=parent.group_id)
        .execution_options(synchronize_session=False)
    )
    await session.execute(
        update(Ledger)
        .where(
            Ledger.company_id == company_id,
            Ledger.group_id.is_(None),
            Ledger.parent_group_tally_guid.is_not(None),
            Group.company_id == company_id,
            Group.tally_guid == Ledger.parent_group_tally_guid,
        )
        .values(group_id=Group.group_id)
        .execution_options(synchronize_session=False)
    )
    vt_parent = aliased(VoucherType)
    await session.execute(
        update(VoucherType)
        .where(
            VoucherType.company_id == company_id,
            VoucherType.parent_voucher_type_id.is_(None),
            VoucherType.parent_tally_guid.is_not(None),
            vt_parent.company_id == company_id,
            vt_parent.tally_guid == VoucherType.parent_tally_guid,
        )
        .values(parent_voucher_type_id=vt_parent.voucher_type_id)
        .execution_options(synchronize_session=False)
    )


async def write_company(
    session: AsyncSession, ctx: IngestContext, records: list[Any]
) -> ChunkOutcome:
    """The COMPANY collection: the GUID must be this company's (D-039 #6); books-beginning is
    stored for the openings (D-039 #5)."""
    outcome = ChunkOutcome()
    for record in records:
        assert isinstance(record, CompanyRecord)
        if ctx.company_guid is not None and record.guid != ctx.company_guid:
            outcome.failures.append(
                RecordFailure(
                    record.guid,
                    record.alter_id,
                    ErrorCode.COMPANY_MISMATCH,
                    "This Tally company is not the one the Agent is registered for",
                )
            )
            continue
        if record.books_from is not None:
            await session.execute(
                update(Company)
                .where(Company.company_id == ctx.company_id)
                .values(books_from=record.books_from)
                .execution_options(synchronize_session=False)
            )
        outcome.written += 1
    return outcome
