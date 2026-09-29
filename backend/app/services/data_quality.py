"""The Data Quality view (FR-4.5, D-041 #9): a registry of checks, each one SQL query whose
rows are its items. Later phases add theirs with `register(Check(...))`.

Checks read the synced tables only; nothing here changes data.
"""

import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from typing import Any, Literal

from sqlalchemy import (
    Select,
    String,
    and_,
    case,
    column,
    exists,
    false,
    func,
    literal,
    null,
    or_,
    select,
    union_all,
    values,
)
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from app.analytics import aging, blocks
from app.analytics.context import AnalyticsFilter, MetricContext, load
from app.analytics.returns import CREDIT_NOTE, DEBIT_NOTE, UNLINKED, linked_notes
from app.core import periods
from app.core.errors import AppError
from app.core.gates import gate_passed
from app.core.permissions import CompanyContext
from app.models.balances import LedgerOpeningBalance
from app.models.company import Company
from app.models.defaults import PREDEFINED_GROUPS
from app.models.enums import (
    GroupResolution,
    KeyListStatus,
    MasterStatus,
    Nature,
    VoucherStatus,
    VoucherTypeResolution,
)
from app.models.masters import CostCentre, Group, Ledger, StockItem, VoucherType
from app.models.sync import SyncError, SyncKeyList
from app.models.vouchers import Voucher
from app.schemas.data_quality import CheckItems, CheckSummary
from app.services.settings import allow_list_entries
from app.sync.hierarchy import BASE_TYPES
from app.sync.holds import held_back_errors
from tally_contract.errors import ErrorCode

Severity = Literal["ERROR", "WARNING", "INFO"]
Query = Callable[[AsyncSession, CompanyContext], Awaitable[Select[Any]]]


@dataclass(frozen=True)
class Check:
    check_id: str
    title: str
    severity: Severity
    how_to_fix: str
    query: Query
    active: Callable[[], bool] = lambda: True  # e.g. retired once a gate passes


CHECKS: dict[str, Check] = {}


def register(check: Check) -> Check:
    CHECKS[check.check_id] = check
    return check


def _nothing(*labels: str) -> Select[Any]:
    """An empty result with these columns."""
    return select(*(null().label(label) for label in labels)).where(false())


# --- groups -------------------------------------------------------------------------------


async def _unresolved_groups(session: AsyncSession, ctx: CompanyContext) -> Select[Any]:
    ledgers = (
        select(func.count())
        .where(Ledger.company_id == ctx.company_id, Ledger.group_id == Group.group_id)
        .scalar_subquery()
    )
    return (
        select(
            Group.group_id,
            Group.name,
            Group.tally_guid,
            Group.parent_tally_guid,
            ledgers.label("ledgers"),
        )
        .where(
            Group.company_id == ctx.company_id,
            Group.resolution_status == GroupResolution.UNRESOLVED_GROUP,
            Group.status == MasterStatus.ACTIVE,
        )
        .order_by(Group.name)
    )


async def _groups_not_classified(session: AsyncSession, ctx: CompanyContext) -> Select[Any]:
    """D-001 case 3: a user top-level group anchors to itself and is in no allow-list."""
    listed = {
        e["tally_guid"]
        for entries in (await allow_list_entries(session, ctx)).values()
        for e in entries
        if e["type"] == "COMPANY_GROUP"
    }
    ledgers = (
        select(func.count())
        .where(
            Ledger.company_id == ctx.company_id,
            Ledger.classification_group_id == Group.group_id,
            Ledger.status == MasterStatus.ACTIVE,
        )
        .scalar_subquery()
    )
    return (
        select(Group.group_id, Group.name, Group.tally_guid, Group.nature, ledgers.label("ledgers"))
        .where(
            Group.company_id == ctx.company_id,
            Group.resolution_status == GroupResolution.RESOLVED,
            Group.is_predefined.is_(False),
            Group.classification_group_id == Group.group_id,
            Group.tally_guid.not_in(listed),  # an empty list excludes nothing
            ledgers > 0,
        )
        .order_by(Group.name)
    )


async def _groups_possibly_renamed(session: AsyncSession, ctx: CompanyContext) -> Select[Any]:
    """D-001 case 5 before G32: one of the 28 names is absent while an unrecognised group
    sits where it belongs (under its primary group, or under Primary for a primary)."""
    expected = values(column("expected", String), column("parent", String), name="expected").data(
        [(primary, None) for primary in PREDEFINED_GROUPS]
        + [(sub, primary) for primary, (_, subs) in PREDEFINED_GROUPS.items() for sub in subs]
    )
    parent = aliased(Group)
    present = aliased(Group)
    return (
        select(expected.c.expected, Group.group_id, Group.name.label("candidate"))
        .select_from(expected)
        .join(
            Group,
            and_(
                Group.company_id == ctx.company_id,
                Group.is_predefined.is_(False),
                or_(
                    and_(expected.c.parent.is_(None), Group.parent_tally_guid.is_(None)),
                    exists().where(
                        parent.company_id == ctx.company_id,
                        parent.reserved_name == expected.c.parent,
                        parent.tally_guid == Group.parent_tally_guid,
                    ),
                ),
            ),
        )
        .where(
            ~exists().where(
                present.company_id == ctx.company_id, present.reserved_name == expected.c.expected
            )
        )
        .order_by(expected.c.expected, Group.name)
    )


async def _stale_allow_list_entries(session: AsyncSession, ctx: CompanyContext) -> Select[Any]:
    """D-001: an entry whose group is no longer live is reported, never silently dropped.
    Before the first group sync every default entry would look stale, so nothing is reported."""
    synced = await session.scalar(select(exists().where(Group.company_id == ctx.company_id)))
    if not synced:
        return _nothing("setting_key", "entry_type", "identifier")
    stale = [
        (key, e["type"], e.get("reserved_name") or e.get("tally_guid"))
        for key, entries in (await allow_list_entries(session, ctx)).items()
        for e in entries
        if e["is_missing"]
    ]
    if not stale:
        return _nothing("setting_key", "entry_type", "identifier")
    table = values(
        column("setting_key", String),
        column("entry_type", String),
        column("identifier", String),
        name="stale",
    ).data(stale)
    return select(table.c.setting_key, table.c.entry_type, table.c.identifier)


# --- voucher types -------------------------------------------------------------------------


def _used_by_vouchers(company_id: uuid.UUID) -> Any:
    return (
        select(func.count())
        .where(
            Voucher.company_id == company_id,
            Voucher.voucher_type_id == VoucherType.voucher_type_id,
            Voucher.status == VoucherStatus.ACTIVE,
        )
        .scalar_subquery()
    )


async def _unresolved_voucher_types(session: AsyncSession, ctx: CompanyContext) -> Select[Any]:
    """ACC-8.3: only types that ACTIVE vouchers use; an unused one changes no figure."""
    used = _used_by_vouchers(ctx.company_id)
    return (
        select(VoucherType.voucher_type_id, VoucherType.name, used.label("vouchers"))
        .where(
            VoucherType.company_id == ctx.company_id,
            VoucherType.resolution_status == VoucherTypeResolution.UNRESOLVED,
            used > 0,
        )
        .order_by(VoucherType.name)
    )


async def _voucher_types_possibly_renamed(
    session: AsyncSession, ctx: CompanyContext
) -> Select[Any]:
    """Owner (D-041 #9), before G32: an accounting type's name is absent while ACTIVE vouchers
    use an unrecognised type. A renamed "Sales" would otherwise make sales read zero."""
    expected = values(column("expected", String), name="expected").data([(n,) for n in BASE_TYPES])
    present = aliased(VoucherType)
    used = _used_by_vouchers(ctx.company_id)
    return (
        select(
            expected.c.expected,
            VoucherType.voucher_type_id,
            VoucherType.name.label("candidate"),
            used.label("vouchers"),
        )
        .select_from(expected)
        .join(
            VoucherType,
            and_(
                VoucherType.company_id == ctx.company_id,
                VoucherType.resolution_status == VoucherTypeResolution.UNRESOLVED,
            ),
        )
        .where(
            used > 0,
            ~exists().where(
                present.company_id == ctx.company_id, present.reserved_name == expected.c.expected
            ),
        )
        .order_by(expected.c.expected, VoucherType.name)
    )


# --- lifecycle and sync ------------------------------------------------------------------


async def _missing_masters(session: AsyncSession, ctx: CompanyContext) -> Select[Any]:
    """DR-ML-3: MISSING_IN_TALLY masters, for review."""
    parts = [
        select(
            literal(kind).label("master_type"),
            pk.label("id"),
            model.tally_guid,
            model.name,
            model.last_synced_at,
        ).where(model.company_id == ctx.company_id, model.status == MasterStatus.MISSING_IN_TALLY)
        for kind, model, pk in (
            ("GROUP", Group, Group.group_id),
            ("LEDGER", Ledger, Ledger.ledger_id),
            ("VOUCHER_TYPE", VoucherType, VoucherType.voucher_type_id),
            ("STOCK_ITEM", StockItem, StockItem.stock_item_id),
            ("COST_CENTRE", CostCentre, CostCentre.cost_centre_id),
        )
    ]
    everything = union_all(*parts).subquery()
    return select(everything).order_by(everything.c.master_type, everything.c.name)


async def _missing_vouchers(session: AsyncSession, ctx: CompanyContext) -> Select[Any]:
    return (
        select(Voucher.voucher_id, Voucher.tally_guid, Voucher.voucher_number, Voucher.voucher_date)
        .where(
            Voucher.company_id == ctx.company_id, Voucher.status == VoucherStatus.MISSING_IN_TALLY
        )
        .order_by(Voucher.voucher_date, Voucher.voucher_number)
    )


async def _suspicious_key_lists(session: AsyncSession, ctx: CompanyContext) -> Select[Any]:
    """D-007: a key list that would have marked too much missing, not yet followed by one that
    was applied for the same collection."""
    later = aliased(SyncKeyList)
    return (
        select(
            SyncKeyList.list_id,
            SyncKeyList.collection_type,
            SyncKeyList.keys_count,
            SyncKeyList.candidates,
            SyncKeyList.evaluated_at,
        )
        .where(
            SyncKeyList.company_id == ctx.company_id,
            SyncKeyList.status == KeyListStatus.SUSPICIOUS,
            ~exists().where(
                later.company_id == ctx.company_id,
                later.collection_type == SyncKeyList.collection_type,
                later.status == KeyListStatus.APPLIED,
                later.evaluated_at > SyncKeyList.evaluated_at,
            ),
        )
        .order_by(SyncKeyList.evaluated_at.desc())
    )


def _unstored(code: ErrorCode) -> Query:
    """Voucher errors of this code whose voucher has not since been stored at that ALTERID or
    later: the latest error per voucher."""

    async def query(session: AsyncSession, ctx: CompanyContext) -> Select[Any]:
        latest = (
            select(func.max(SyncError.id))
            .where(
                SyncError.company_id == ctx.company_id,
                SyncError.error_code == code.value,
                SyncError.entity_type == "VOUCHER",
            )
            .group_by(SyncError.tally_guid)
        )
        return (
            select(
                SyncError.tally_guid, SyncError.alter_id, SyncError.message, SyncError.created_at
            )
            .where(
                SyncError.id.in_(latest),
                ~exists().where(
                    Voucher.company_id == ctx.company_id,
                    Voucher.tally_guid == SyncError.tally_guid,
                    Voucher.alter_id >= func.coalesce(SyncError.alter_id, 0),
                ),
            )
            .order_by(SyncError.created_at.desc())
        )

    return query


async def _sync_held_back(session: AsyncSession, ctx: CompanyContext) -> Select[Any]:
    held = held_back_errors(ctx.company_id).subquery()
    return select(held).order_by(held.c.entity_type, held.c.alter_id)


async def _ledgers_without_opening(session: AsyncSession, ctx: CompanyContext) -> Select[Any]:
    """Balance-sheet ledgers with no books-beginning opening row (D-039 #5): the export had no
    opening field at all. GATE-G16: a blank one is stored as zero (D-044 #6)."""
    books_from = select(Company.books_from).where(Company.company_id == ctx.company_id)
    anchor = aliased(Group)
    return (
        select(Ledger.ledger_id, Ledger.name, anchor.nature)
        .join(anchor, anchor.group_id == Ledger.classification_group_id)
        .where(
            Ledger.company_id == ctx.company_id,
            Ledger.status == MasterStatus.ACTIVE,
            anchor.nature.in_([Nature.ASSET, Nature.LIABILITY]),
            ~exists().where(
                LedgerOpeningBalance.company_id == ctx.company_id,
                LedgerOpeningBalance.ledger_id == Ledger.ledger_id,
                LedgerOpeningBalance.financial_year_start == books_from.scalar_subquery(),
            ),
        )
        .order_by(Ledger.name)
    )


async def _unlinked_notes(session: AsyncSession, ctx: CompanyContext) -> Select[Any]:
    """ACC-5.3/5.4: ACTIVE credit and debit notes not linked to an original bill; GATE-G26:
    until it passes, that is every note (ACC-5.5)."""
    linkable = gate_passed("G26")
    kind = case(
        (VoucherType.base_voucher_type == CREDIT_NOTE, UNLINKED[CREDIT_NOTE]),
        else_=UNLINKED[DEBIT_NOTE],
    )
    return (
        select(
            Voucher.voucher_id,
            Voucher.voucher_date,
            Voucher.voucher_number,
            VoucherType.name.label("voucher_type_name"),
            kind.label("adjustment_type"),
        )
        .join(
            VoucherType,
            and_(
                VoucherType.company_id == Voucher.company_id,
                VoucherType.voucher_type_id == Voucher.voucher_type_id,
            ),
        )
        .where(
            Voucher.company_id == ctx.company_id,
            Voucher.status == VoucherStatus.ACTIVE,
            or_(
                *(
                    and_(
                        VoucherType.base_voucher_type == note,
                        Voucher.voucher_id.not_in(linked_notes(ctx.company_id, linkable, note)),
                    )
                    for note in (CREDIT_NOTE, DEBIT_NOTE)
                )
            ),
        )
        .order_by(Voucher.voucher_date, Voucher.voucher_number, Voucher.voucher_id)
    )


async def _unsupported_allocations(session: AsyncSession, ctx: CompanyContext) -> Select[Any]:
    return blocks.unsupported_allocations(ctx.company_id)


async def _aging_context(session: AsyncSession, ctx: CompanyContext) -> MetricContext:
    """Aging as of today in the company's time zone (D-049 #4)."""
    company = await session.get(Company, ctx.company_id)
    assert company is not None
    today = periods.today(company.company_timezone)
    return await load(session, ctx, AnalyticsFilter(today, today))


def _both_sides(build: Callable[[str], Select[Any]]) -> Select[Any]:
    parts = [
        select(literal(side).label("side"), q.subquery())
        for side, q in ((s, build(s)) for s in ("receivable", "payable"))
    ]
    return select(union_all(*parts).subquery())


async def _over_settled_bills(session: AsyncSession, ctx: CompanyContext) -> Select[Any]:
    mctx = await _aging_context(session, ctx)

    def build(side: str) -> Select[Any]:
        b = aging.bills(mctx, side, [30, 60, 90]).subquery()
        return select(
            b.c.ledger_name, b.c.reference_name, b.c.bill_date, (-b.c.outstanding).label("credit")
        ).where(b.c.bucket == aging.CREDIT)

    return _both_sides(build)


async def _unmatched_settlements(session: AsyncSession, ctx: CompanyContext) -> Select[Any]:
    mctx = await _aging_context(session, ctx)
    return _both_sides(lambda side: aging.unmatched_settlements(mctx, side))


async def _bill_reference_reused(session: AsyncSession, ctx: CompanyContext) -> Select[Any]:
    mctx = await _aging_context(session, ctx)

    def build(side: str) -> Select[Any]:
        b = aging.bills(mctx, side, [30, 60, 90]).subquery()
        return select(b.c.ledger_name, b.c.reference_name, b.c.bill_date, b.c.outstanding).where(
            b.c.reused
        )

    return _both_sides(build)


def _before_g32() -> bool:
    return not gate_passed("G32")


for _check in (
    Check(
        "unresolved_groups",
        "Unresolved groups",
        "ERROR",
        "A group's parent is missing or its chain loops. Its ledgers are left out of every "
        "classified figure until the chain is fixed in Tally and synced again.",
        _unresolved_groups,
    ),
    Check(
        "groups_not_in_classification_list",
        "Groups not in any classification list",
        "WARNING",
        "A group created directly under Primary is in no sales, purchase, expense, cash/bank "
        "or tax list. Add it to the right list in Settings if its ledgers belong there.",
        _groups_not_classified,
    ),
    Check(
        "predefined_group_possibly_renamed",
        "Predefined group possibly renamed",
        "ERROR",
        "One of Tally's predefined groups is missing by name while an unrecognised group sits "
        "in its place. If it was renamed, its ledgers are classified one level up until the "
        "reserved-name gate (G32) passes.",
        _groups_possibly_renamed,
        _before_g32,
    ),
    Check(
        "stale_allow_list_entries",
        "Classification list entries for missing groups",
        "WARNING",
        "An allow-list names a group that is no longer in Tally. Remove or replace it in Settings.",
        _stale_allow_list_entries,
    ),
    Check(
        "unresolved_voucher_types",
        "Unresolved voucher types",
        "ERROR",
        "Vouchers use a type whose chain does not reach one of Tally's predefined types; they "
        "count as OTHER and are left out of type-filtered figures.",
        _unresolved_voucher_types,
    ),
    Check(
        "predefined_voucher_type_possibly_renamed",
        "Predefined voucher type possibly renamed",
        "ERROR",
        "An accounting voucher type (such as Sales) is missing by name while vouchers use an "
        "unrecognised type. If it was renamed, those vouchers count as OTHER, and that figure "
        "reads zero, until the reserved-name gate (G32) passes.",
        _voucher_types_possibly_renamed,
        _before_g32,
    ),
    Check(
        "missing_masters",
        "Missing masters",
        "WARNING",
        "These masters are no longer in Tally. Past vouchers still refer to them; if one was "
        "deleted by mistake, restore it in Tally and it returns on the next sync.",
        _missing_masters,
    ),
    Check(
        "missing_vouchers",
        "Vouchers missing in Tally",
        "WARNING",
        "These vouchers are no longer in Tally and are left out of standard figures. If one "
        "was deleted by mistake, restore it in Tally and it returns on the next sync.",
        _missing_vouchers,
    ),
    Check(
        "suspicious_key_lists",
        "Suspicious key lists",
        "WARNING",
        "A key list would have marked too many records missing at once, so nothing was "
        "changed. If the records really were deleted, confirm the list in Sync.",
        _suspicious_key_lists,
    ),
    Check(
        "imbalanced_vouchers",
        "Vouchers whose debits and credits differ",
        "ERROR",
        "These vouchers were not stored because their entries do not balance. Correct them "
        "in Tally; they are retried on every sync.",
        _unstored(ErrorCode.DEBIT_CREDIT_IMBALANCE),
    ),
    Check(
        "unknown_master_references",
        "Vouchers naming unknown masters",
        "ERROR",
        "These vouchers were not stored because they name a ledger, stock item, cost centre "
        "or voucher type that has not been synced. They are retried on every sync.",
        _unstored(ErrorCode.UNKNOWN_MASTER_REFERENCE),
    ),
    Check(
        "sync_held_back",
        "Sync held back by failing records",
        "WARNING",
        "These records keep failing, so their collection's sync position cannot move past "
        "them and they are retried on every run. Fix them in Tally.",
        _sync_held_back,
    ),
    Check(
        "ledgers_without_opening_balance",
        "Balance-sheet ledgers with no opening balance",
        "INFO",
        "No opening balance was received for these ledgers, so their balances show "
        '"opening balance unavailable". Sync them again; if it persists, check that the '
        "TDL loaded in TallyPrime is this version.",
        _ledgers_without_opening,
    ),
    Check(
        "unlinked_notes",
        "Credit and debit notes not linked to a bill",
        "INFO",
        "These notes are not linked to an original sales or purchase bill, so they are not "
        "subtracted from sales or purchases and are listed under Unclassified Adjustments. "
        "Until the return-link gate (G26) passes, every note is listed here.",
        _unlinked_notes,
    ),
    Check(
        "unsupported_bill_allocations",
        "Bill allocations of an unknown type",
        "WARNING",
        "Tally exported these bill allocations with a type that is not New Ref, Agst Ref, "
        "Advance or On Account, so they are left out of aging (AGE-BILL-2). Until the "
        "allocation-type gate (G25) passes, the expected names are a draft.",
        _unsupported_allocations,
    ),
    Check(
        "over_settled_bills",
        "Bills settled for more than they were raised",
        "WARNING",
        "More was received (or paid) against these bills than they were raised for. They are "
        "shown as a credit in aging, never in a bucket. Check the settlements in Tally.",
        _over_settled_bills,
    ),
    Check(
        "unmatched_settlements",
        "Settlements against no known bill",
        "WARNING",
        "These Against References name a bill that is not among the synced active bills (for "
        "example its voucher is cancelled). They count in the party's net exposure, never in "
        "a bucket.",
        _unmatched_settlements,
    ),
    Check(
        "bill_reference_reused",
        "Bill reference reused",
        "WARNING",
        "More than one voucher raised a bill with this name for the same party (for example "
        "invoice numbers restarting each year). Aging treats them as one bill, aged from the "
        "earliest, and marks it unverified until the bill-details gate (G31) shows how Tally "
        "keeps them apart.",
        _bill_reference_reused,
    ),
):
    register(_check)


# --- the view -------------------------------------------------------------------------------


def _summary(check: Check, count: int) -> CheckSummary:
    return CheckSummary(
        check_id=check.check_id,
        title=check.title,
        severity=check.severity,
        how_to_fix=check.how_to_fix,
        count=count,
    )


def _json(value: Any) -> Any:
    """Items carry identifiers and dates only; money would stay a string (CLAUDE.md #10)."""
    if isinstance(value, (uuid.UUID, Decimal)):
        return str(value)
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    return value


async def _count(session: AsyncSession, stmt: Select[Any]) -> int:
    return int(
        await session.scalar(select(func.count()).select_from(stmt.order_by(None).subquery())) or 0
    )


async def summary(session: AsyncSession, ctx: CompanyContext) -> list[CheckSummary]:
    return [
        _summary(check, await _count(session, await check.query(session, ctx)))
        for check in CHECKS.values()
        if check.active()
    ]


async def items(
    session: AsyncSession, ctx: CompanyContext, check_id: str, limit: int, offset: int
) -> CheckItems:
    check = CHECKS.get(check_id)
    if check is None or not check.active():
        raise AppError(ErrorCode.NOT_FOUND, "Data Quality check not found", 404)
    stmt = await check.query(session, ctx)
    rows = await session.execute(stmt.limit(limit).offset(offset))
    return CheckItems(
        **_summary(check, await _count(session, stmt)).model_dump(),
        items=[{k: _json(v) for k, v in row.items()} for row in rows.mappings()],
        limit=limit,
        offset=offset,
    )
