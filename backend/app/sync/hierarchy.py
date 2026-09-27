"""Group and voucher-type resolution (SRS 8.2, 8.3, D-001, D-041 #8).

Recomputed in the transaction of every GROUP, LEDGER and VOUCHER_TYPE chunk, under a
per-company advisory lock, so no committed chunk leaves a stale parent or anchor. Groups and
voucher types are few; the forest is resolved in memory and only changes are written.

A walk up the parents stops at a predefined primary group (groups) or the first predefined
type (voucher types): their own parent is never read, whatever Tally reports for it (G12, G15).
A parent that is not among the company's records, or a loop, is a broken chain.
"""

import uuid
from dataclasses import dataclass
from typing import Any

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import audit
from app.models.defaults import PREDEFINED_GROUPS
from app.models.enums import (
    BaseVoucherType,
    CollectionType,
    GroupResolution,
    Nature,
    VoucherTypeResolution,
)
from app.models.masters import Group, VoucherType

# Every predefined group's nature, through its primary group (D-001).
PREDEFINED_NATURE: dict[str, Nature] = {
    name: nature
    for primary, (nature, subs) in PREDEFINED_GROUPS.items()
    for name in (primary, *subs)
}
# The accounting voucher types by reserved name (ACC-8.1); other predefined types are OTHER.
BASE_TYPES: dict[str, BaseVoucherType] = {
    "Sales": BaseVoucherType.SALES,
    "Purchase": BaseVoucherType.PURCHASE,
    "Receipt": BaseVoucherType.RECEIPT,
    "Payment": BaseVoucherType.PAYMENT,
    "Contra": BaseVoucherType.CONTRA,
    "Journal": BaseVoucherType.JOURNAL,
    "Credit Note": BaseVoucherType.CREDIT_NOTE,
    "Debit Note": BaseVoucherType.DEBIT_NOTE,
}


def own_nature(is_revenue: bool | None, is_deemed_positive: bool | None) -> Nature | None:
    """A group's nature from Tally's own flags (GATE-G14, D-041 #7): None when either is missing."""
    if is_revenue is None or is_deemed_positive is None:
        return None
    if is_revenue:
        return Nature.EXPENSE if is_deemed_positive else Nature.INCOME
    return Nature.ASSET if is_deemed_positive else Nature.LIABILITY


async def _lock(session: AsyncSession, company_id: uuid.UUID) -> None:
    await session.execute(
        text("SELECT pg_advisory_xact_lock(hashtext('hierarchy'), hashtext(:company))"),
        {"company": str(company_id)},
    )


_BROKEN: Any = object()


@dataclass(frozen=True)
class _Chain:
    top: Any  # the top-level record of the chain
    predefined: Any  # the nearest predefined record, including itself, or None


def _resolve(
    records: list[Any], parent_guid: Any, is_root: Any, is_predefined: Any
) -> dict[str, Any]:
    """Each record's chain, or _BROKEN. Iterative, memoised, with cycle detection."""
    by_guid = {r.tally_guid: r for r in records}
    done: dict[str, Any] = {}
    for record in records:
        path: list[Any] = []
        on_path: set[str] = set()
        cur = record
        while True:
            if cur.tally_guid in done:
                base = done[cur.tally_guid]
                break
            if cur.tally_guid in on_path:  # a loop
                base = _BROKEN
                break
            path.append(cur)
            on_path.add(cur.tally_guid)
            parent = parent_guid(cur)
            if is_root(cur) or parent is None:
                base = None  # cur is the top
                break
            if parent not in by_guid:  # a parent the company does not have
                base = _BROKEN
                break
            cur = by_guid[parent]
        for node in reversed(path):
            if base is _BROKEN:
                done[node.tally_guid] = _BROKEN
                continue
            if base is None:
                chain = _Chain(top=node, predefined=node if is_predefined(node) else None)
            else:
                chain = _Chain(
                    top=base.top, predefined=node if is_predefined(node) else base.predefined
                )
            done[node.tally_guid] = base = chain
    return done


def _state(record: Any, fields: tuple[str, ...]) -> dict[str, Any]:
    return {f: getattr(record, f) for f in fields}


async def _audit_change(
    session: AsyncSession, record: Any, action: str, before: dict[str, Any], after: dict[str, Any]
) -> None:
    await audit.record(
        session,
        company_id=record.company_id,
        user_id=None,
        action=action,
        entity_type=record.__tablename__,
        entity_id=str(getattr(record, record.__mapper__.primary_key[0].key)),
        before={k: None if v is None else str(v) for k, v in before.items()},
        after={k: None if v is None else str(v) for k, v in after.items()} | {"name": record.name},
    )


GROUP_FIELDS = (
    "parent_group_id",
    "predefined_group_id",
    "classification_group_id",
    "primary_group_id",
    "nature",
    "resolution_status",
)


async def resolve_groups(session: AsyncSession, company_id: uuid.UUID) -> None:
    """D-001: the anchor is the nearest predefined group, else the chain's top-level group;
    only a broken chain is UNRESOLVED_GROUP (ACC-7.2, 7.4, 7.5)."""
    groups = list(
        (await session.execute(select(Group).where(Group.company_id == company_id))).scalars()
    )
    by_guid = {g.tally_guid: g for g in groups}
    chains = _resolve(
        groups,
        parent_guid=lambda g: g.parent_tally_guid,
        is_root=lambda g: g.is_predefined and g.reserved_name in PREDEFINED_GROUPS,
        is_predefined=lambda g: g.is_predefined,
    )
    for g in groups:
        parent = by_guid.get(g.parent_tally_guid) if g.parent_tally_guid else None
        chain = chains[g.tally_guid]
        new: dict[str, Any] = dict.fromkeys(GROUP_FIELDS)
        new["parent_group_id"] = parent.group_id if parent else None
        new["resolution_status"] = GroupResolution.UNRESOLVED_GROUP.value
        if chain is not _BROKEN:
            top = chain.top
            nature = (
                PREDEFINED_NATURE.get(top.reserved_name) if top.is_predefined else top.own_nature
            )
            if nature is not None:  # a RESOLVED group always has a nature (D-041 #7)
                new |= {
                    "predefined_group_id": chain.predefined.group_id if chain.predefined else None,
                    "classification_group_id": (chain.predefined or top).group_id,
                    "primary_group_id": top.group_id
                    if top.reserved_name in PREDEFINED_GROUPS
                    else None,
                    "nature": Nature(nature).value,
                    "resolution_status": GroupResolution.RESOLVED.value,
                }
        before = _state(g, GROUP_FIELDS)
        if before == new:
            continue
        for field, value in new.items():
            setattr(g, field, value)
        resolved_before = before["resolution_status"] == GroupResolution.RESOLVED
        meaningful = {k for k in GROUP_FIELDS if k != "parent_group_id" and before[k] != new[k]}
        if resolved_before and meaningful:  # ACC-7.5; a new group's first resolution is not
            await _audit_change(session, g, "GROUP_RESOLUTION_CHANGED", before, new)
    await session.flush()


async def refresh_ledgers(session: AsyncSession, company_id: uuid.UUID) -> None:
    """Each ledger's group and the anchor cached from it, in one statement; also after a
    reparent (the parent GUID decides, not a previously linked ID)."""
    await session.execute(
        text(
            """
            WITH target AS (
                SELECT l.ledger_id, g.group_id, g.classification_group_id AS anchor,
                       g.predefined_group_id AS predefined, g.primary_group_id AS primary_group
                  FROM ledgers l
                  LEFT JOIN groups g
                    ON g.company_id = l.company_id AND g.tally_guid = l.parent_group_tally_guid
                 WHERE l.company_id = :company
            )
            UPDATE ledgers
               SET group_id = t.group_id, classification_group_id = t.anchor,
                   predefined_group_id = t.predefined, primary_group_id = t.primary_group
              FROM target t
             WHERE ledgers.ledger_id = t.ledger_id
               AND (ledgers.group_id, ledgers.classification_group_id,
                    ledgers.predefined_group_id, ledgers.primary_group_id)
                   IS DISTINCT FROM (t.group_id, t.anchor, t.predefined, t.primary_group)
            """
        ),
        {"company": company_id},
    )


VOUCHER_TYPE_FIELDS = ("parent_voucher_type_id", "base_voucher_type", "resolution_status")


async def resolve_voucher_types(session: AsyncSession, company_id: uuid.UUID) -> None:
    """ACC-8.x: walk to the first predefined type; the 8 accounting types give their base
    type, any other predefined type OTHER (RESOLVED); a broken chain, or none, OTHER
    (UNRESOLVED)."""
    types = list(
        (
            await session.execute(select(VoucherType).where(VoucherType.company_id == company_id))
        ).scalars()
    )
    by_guid = {t.tally_guid: t for t in types}
    chains = _resolve(
        types,
        parent_guid=lambda t: t.parent_tally_guid,
        is_root=lambda t: t.reserved_name is not None,
        is_predefined=lambda t: t.reserved_name is not None,
    )
    for t in types:
        parent = by_guid.get(t.parent_tally_guid) if t.parent_tally_guid else None
        chain = chains[t.tally_guid]
        predefined = None if chain is _BROKEN else chain.predefined
        new = {
            "parent_voucher_type_id": parent.voucher_type_id if parent else None,
            "base_voucher_type": (
                BASE_TYPES.get(predefined.reserved_name, BaseVoucherType.OTHER).value
                if predefined
                else BaseVoucherType.OTHER.value
            ),
            "resolution_status": (
                VoucherTypeResolution.RESOLVED.value
                if predefined
                else VoucherTypeResolution.UNRESOLVED.value
            ),
        }
        before = _state(t, VOUCHER_TYPE_FIELDS)
        if before == new:
            continue
        for field, value in new.items():
            setattr(t, field, value)
        meaningful = before["base_voucher_type"] != new["base_voucher_type"] or (
            before["resolution_status"] != new["resolution_status"]
        )
        if before["resolution_status"] == VoucherTypeResolution.RESOLVED and meaningful:
            await _audit_change(session, t, "VOUCHER_TYPE_RESOLUTION_CHANGED", before, new)
    await session.flush()


async def after_chunk(
    session: AsyncSession, company_id: uuid.UUID, collection: CollectionType
) -> None:
    """Called by ingest in the chunk's own transaction (D-041 #8)."""
    if collection not in (CollectionType.GROUP, CollectionType.LEDGER, CollectionType.VOUCHER_TYPE):
        return
    await _lock(session, company_id)
    if collection == CollectionType.GROUP:
        await resolve_groups(session, company_id)
    if collection in (CollectionType.GROUP, CollectionType.LEDGER):
        await refresh_ledgers(session, company_id)
    if collection == CollectionType.VOUCHER_TYPE:
        await resolve_voucher_types(session, company_id)
