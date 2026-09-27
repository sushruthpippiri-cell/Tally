"""Voucher writer (P5.4, SRS 6.7, 6.9, SYNC-6.2, DR-VE-*).

Each voucher is written in its own SAVEPOINT: header, entries, bill and cost-centre
allocations and items commit together or not at all (SYNC-6.2, DR-VE-4). A modified voucher's
children are replaced in full in the SRS 6.9 order (DR-VE-3); per-line updates by a stable
line identifier (DR-VE-2) wait for GATE-G24 to show that one exists. Fragile composite keys
(ledger + amount + position) are never used to match lines.
"""

import uuid
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from sqlalchemy import delete, insert, select, update
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import audit
from app.models.enums import CollectionType, VoucherStatus
from app.models.masters import CostCentre, Ledger, StockItem, VoucherType
from app.models.vouchers import (
    BillAllocation,
    CostCentreAllocation,
    Voucher,
    VoucherEntry,
    VoucherItem,
)
from app.sync import lifecycle
from app.sync.context import ChunkOutcome, IngestContext, RecordFailure
from tally_contract import normalize
from tally_contract.errors import ErrorCode, RecordRejected
from tally_contract.records import VoucherRecord


class Unresolved(ValueError):
    """A master the voucher names is not stored (D-039 #7)."""


@dataclass
class Masters:
    """GUID -> id and name -> id for every master the chunk's vouchers name (D-002)."""

    by_guid: dict[str, dict[str, uuid.UUID]]
    by_name: dict[str, dict[str, uuid.UUID]]

    def resolve(self, kind: str, guid: str | None, name: str) -> uuid.UUID:
        found = self.by_guid[kind].get(guid) if guid else self.by_name[kind].get(name)
        if found is None:
            raise Unresolved(f"{kind} {guid or name!r} is not in this company's masters")
        return found


_KINDS: dict[str, Any] = {
    "ledger": (Ledger, Ledger.ledger_id),
    "stock item": (StockItem, StockItem.stock_item_id),
    "cost centre": (CostCentre, CostCentre.cost_centre_id),
    "voucher type": (VoucherType, VoucherType.voucher_type_id),
}


def _references(records: list[VoucherRecord]) -> dict[str, list[tuple[str | None, str]]]:
    refs: dict[str, list[tuple[str | None, str]]] = {k: [] for k in _KINDS}
    for v in records:
        refs["voucher type"].append((v.voucher_type_guid, v.voucher_type_name))
        for e in v.entries:
            refs["ledger"].append((e.ledger_guid, e.ledger_name))
            refs["cost centre"] += [
                (c.cost_centre_guid, c.cost_centre_name) for c in e.cost_centre_allocations
            ]
        refs["stock item"] += [(i.stock_item_guid, i.stock_item_name) for i in v.items]
    return refs


async def load_masters(
    session: AsyncSession, company_id: uuid.UUID, records: list[VoucherRecord]
) -> Masters:
    by_guid: dict[str, dict[str, uuid.UUID]] = {}
    by_name: dict[str, dict[str, uuid.UUID]] = {}
    for kind, pairs in _references(records).items():
        model, pk = _KINDS[kind]
        guids = {g for g, _ in pairs if g}
        names = {n for g, n in pairs if not g}
        by_guid[kind] = (
            dict(
                (
                    await session.execute(
                        select(model.tally_guid, pk).where(
                            model.company_id == company_id, model.tally_guid.in_(guids)
                        )
                    )
                )
                .tuples()
                .all()
            )
            if guids
            else {}
        )
        by_name[kind] = (
            dict(
                (
                    await session.execute(
                        select(model.name, pk).where(
                            model.company_id == company_id, model.name.in_(names)
                        )
                    )
                )
                .tuples()
                .all()
            )
            if names
            else {}
        )
    return Masters(by_guid, by_name)


def _summary(v: Voucher, entries: list[tuple[str, str, Decimal]]) -> dict[str, Any]:
    """What an auditor needs to see a change: header, total and each entry (D-039 #8)."""
    return {
        "voucher_number": v.voucher_number,
        "voucher_date": v.voucher_date.isoformat(),
        "narration": v.narration,
        "status": v.status,
        "total": str(sum((a for _, d, a in entries if d == "DEBIT"), Decimal(0))),
        "entries": [[name, direction, str(amount)] for name, direction, amount in entries],
    }


async def _stored_entries(
    session: AsyncSession, voucher_id: uuid.UUID
) -> list[tuple[str, str, Decimal]]:
    rows = await session.execute(
        select(Ledger.name, VoucherEntry.accounting_direction, VoucherEntry.amount_absolute)
        .join(Ledger, Ledger.ledger_id == VoucherEntry.ledger_id)
        .where(VoucherEntry.voucher_id == voucher_id)
        .order_by(VoucherEntry.line_sequence)
    )
    return [(n, d, Decimal(a)) for n, d, a in rows.tuples()]


async def _delete_children(session: AsyncSession, voucher_id: uuid.UUID) -> None:
    """SRS 6.9 steps 2-4, in order."""
    entry_ids = select(VoucherEntry.voucher_entry_id).where(VoucherEntry.voucher_id == voucher_id)
    await session.execute(
        delete(BillAllocation).where(BillAllocation.voucher_entry_id.in_(entry_ids))
    )
    await session.execute(
        delete(CostCentreAllocation).where(CostCentreAllocation.voucher_entry_id.in_(entry_ids))
    )
    await session.execute(delete(VoucherEntry).where(VoucherEntry.voucher_id == voucher_id))
    await session.execute(delete(VoucherItem).where(VoucherItem.voucher_id == voucher_id))


async def _insert_entries(
    session: AsyncSession, ctx: IngestContext, voucher_id: uuid.UUID, v: VoucherRecord, m: Masters
) -> dict[int, tuple[int, uuid.UUID]]:
    """Returns line_sequence -> (voucher_entry_id, ledger_id)."""
    if not v.entries:
        return {}
    rows = [
        {
            "company_id": ctx.company_id,
            "voucher_id": voucher_id,
            "ledger_id": m.resolve("ledger", e.ledger_guid, e.ledger_name),
            "line_sequence": e.line_sequence,
            "stable_line_id": e.stable_line_id,
            "amount_raw": e.amount.amount_raw,
            "is_debit": e.amount.is_debit,
            "amount_absolute": e.amount.amount_absolute,
            "amount_signed": e.amount.amount_signed,
            "accounting_direction": e.amount.accounting_direction,
        }
        for e in v.entries
    ]
    result = await session.execute(
        insert(VoucherEntry).returning(
            VoucherEntry.voucher_entry_id, VoucherEntry.line_sequence, VoucherEntry.ledger_id
        ),
        rows,
    )
    return {seq: (entry_id, ledger_id) for entry_id, seq, ledger_id in result.tuples()}


async def _insert_allocations(
    session: AsyncSession,
    ctx: IngestContext,
    v: VoucherRecord,
    entries: dict[int, tuple[int, uuid.UUID]],
    m: Masters,
) -> None:
    bills, centres = [], []
    for e in v.entries:
        entry_id, ledger_id = entries[e.line_sequence]
        bills += [
            {
                "company_id": ctx.company_id,
                "voucher_entry_id": entry_id,
                "ledger_id": ledger_id,  # D-004: denormalized from the entry
                "allocation_type_raw": b.allocation_type_raw,
                "allocation_type": b.allocation_type,
                "reference_name": b.reference_name or None,  # On Account has none (G25)
                "due_date": b.due_date,
                "amount_absolute": b.amount.amount_absolute,
                "accounting_direction": b.amount.accounting_direction,
            }
            for b in e.bill_allocations
        ]
        centres += [
            {
                "company_id": ctx.company_id,
                "voucher_entry_id": entry_id,
                "cost_centre_id": m.resolve("cost centre", c.cost_centre_guid, c.cost_centre_name),
                "amount_absolute": c.amount_absolute,
            }
            for c in e.cost_centre_allocations
        ]
    if bills:
        await session.execute(insert(BillAllocation), bills)
    if centres:
        await session.execute(insert(CostCentreAllocation), centres)


async def _insert_items(
    session: AsyncSession, ctx: IngestContext, voucher_id: uuid.UUID, v: VoucherRecord, m: Masters
) -> None:
    items = [
        {
            "company_id": ctx.company_id,
            "voucher_id": voucher_id,
            "stock_item_id": m.resolve("stock item", i.stock_item_guid, i.stock_item_name),
            # GATE-G27: a line exported without a quantity is stored as zero quantity.
            "quantity": i.quantity if i.quantity is not None else Decimal(0),
            "unit": i.unit,
            "rate": i.rate,
            "amount": i.amount.amount_absolute,
            "custom_fields": i.custom_fields or None,
        }
        for i in v.items
    ]
    if items:
        await session.execute(insert(VoucherItem), items)


async def _write_children(
    session: AsyncSession, ctx: IngestContext, voucher_id: uuid.UUID, v: VoucherRecord, m: Masters
) -> None:
    """SRS 6.9 step 5."""
    entries = await _insert_entries(session, ctx, voucher_id, v, m)
    await _insert_allocations(session, ctx, v, entries, m)
    await _insert_items(session, ctx, voucher_id, v, m)


def _status(v: VoucherRecord) -> VoucherStatus:
    return VoucherStatus.CANCELLED if v.is_cancelled else VoucherStatus.ACTIVE  # GATE-G9


async def _write_one(
    session: AsyncSession, ctx: IngestContext, v: VoucherRecord, stored: Voucher | None, m: Masters
) -> None:
    normalize.check_balance(v.entries)  # defence in depth (D-005): never trust the Agent
    header = {
        "alter_id": v.alter_id,
        "voucher_number": v.voucher_number,
        "voucher_type_id": m.resolve("voucher type", v.voucher_type_guid, v.voucher_type_name),
        "voucher_date": v.voucher_date,
        "narration": v.narration,
        "status": _status(v),
        "custom_fields": v.custom_fields or None,
        "last_synced_at": ctx.now,
    }
    if stored is None:  # new (SRS 6.7)
        voucher_id = (
            await session.execute(
                insert(Voucher)
                .values(company_id=ctx.company_id, tally_guid=v.guid, **header)
                .returning(Voucher.voucher_id)
            )
        ).scalar_one()
        await _write_children(session, ctx, voucher_id, v, m)
        return
    # Modified (SRS 6.7): header, then children replaced in the SRS 6.9 order.
    before = _summary(stored, await _stored_entries(session, stored.voucher_id))
    await session.execute(
        update(Voucher)
        .where(Voucher.voucher_id == stored.voucher_id, Voucher.alter_id < v.alter_id)
        .values(**header)
        .execution_options(synchronize_session=False)
    )
    await _delete_children(session, stored.voucher_id)
    await _write_children(session, ctx, stored.voucher_id, v, m)
    after_row = await session.get(Voucher, stored.voucher_id, populate_existing=True)
    assert after_row is not None
    after = _summary(after_row, await _stored_entries(session, stored.voucher_id))
    changed_before, changed_after = audit.diff(before, after)
    action = (
        "VOUCHER_CANCELLED"
        if header["status"] == VoucherStatus.CANCELLED
        and before["status"] != VoucherStatus.CANCELLED
        else "VOUCHER_MODIFIED"
    )
    await audit.record(
        session,
        company_id=ctx.company_id,
        user_id=None,  # system change (LOG-1.1)
        action=action,
        entity_type="voucher",
        entity_id=str(stored.voucher_id),
        before=changed_before | {"tally_guid": v.guid},
        after=changed_after | {"alter_id": v.alter_id},
    )


async def write_vouchers(
    session: AsyncSession, ctx: IngestContext, records: list[Any]
) -> ChunkOutcome:
    outcome = ChunkOutcome()
    vouchers: list[VoucherRecord] = records
    guids = [r.guid for r in vouchers]
    await lifecycle.restore(session, ctx.company_id, CollectionType.VOUCHER, guids, "pull")
    stored = {
        v.tally_guid: v
        for v in (
            await session.execute(
                select(Voucher)
                .where(
                    Voucher.company_id == ctx.company_id,
                    Voucher.tally_guid.in_([r.guid for r in vouchers]),
                )
                .execution_options(populate_existing=True)
            )
        ).scalars()
    }
    masters = await load_masters(session, ctx.company_id, vouchers)
    for v in vouchers:
        current = stored.get(v.guid)
        if current is not None and v.alter_id < current.alter_id:
            outcome.stale.append((v.guid, current.alter_id, v.alter_id))
            continue
        if current is not None and v.alter_id == current.alter_id:
            outcome.unchanged += 1
            continue
        try:
            async with session.begin_nested():
                await _write_one(session, ctx, v, current, masters)
        except Unresolved as exc:
            outcome.failures.append(
                RecordFailure(v.guid, v.alter_id, ErrorCode.UNKNOWN_MASTER_REFERENCE, str(exc))
            )
            continue
        except RecordRejected as exc:
            outcome.failures.append(RecordFailure(v.guid, v.alter_id, exc.code, str(exc)))
            continue
        except (DBAPIError, ValueError) as exc:
            outcome.failures.append(
                RecordFailure(v.guid, v.alter_id, ErrorCode.PARSE_ERROR, str(exc)[:1000])
            )
            continue
        outcome.written += 1
    return outcome
