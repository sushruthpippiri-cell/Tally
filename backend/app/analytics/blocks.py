"""Building blocks every metric's detail query starts from (P8.2, D-044 #1).

Only the normalized amount columns are read: `accounting_direction`, `amount_absolute`,
`amount_signed` (ACC-DATA-1).
"""

import uuid
from collections.abc import Iterable
from datetime import date
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    ColumnElement,
    Date,
    Select,
    String,
    and_,
    case,
    cast,
    false,
    func,
    literal,
    null,
    select,
    union_all,
)
from sqlalchemy.dialects.postgresql import ARRAY, UUID
from sqlalchemy.orm import InstrumentedAttribute

from app.analytics.context import MetricContext
from app.models.balances import LedgerOpeningBalance
from app.models.enums import AccountingDirection, Nature
from app.models.masters import Group, Ledger, StockItem, VoucherType
from app.models.vouchers import Voucher, VoucherEntry, VoucherItem

E, V, VT, L = VoucherEntry, Voucher, VoucherType, Ledger
VI, SI = VoucherItem, StockItem


def entries(
    ctx: MetricContext,
    amount: ColumnElement[Decimal] | InstrumentedAttribute[Decimal],
    since: date | None = None,
) -> Select[Any]:
    """One row per voucher entry dated in the filter's range (from `since` instead, for
    balances) on a voucher with one of its statuses (ACTIVE unless widened, ACC-4.5), with the
    standard detail columns and `amount`, the metric's signed contribution. Metrics add their
    own conditions."""
    return (
        select(
            V.voucher_id,
            V.voucher_date,
            V.voucher_number,
            VT.name.label("voucher_type_name"),
            VT.base_voucher_type,
            E.ledger_id,
            L.name.label("ledger_name"),
            amount.label("amount"),
        )
        .select_from(E)
        .join(V, and_(V.company_id == E.company_id, V.voucher_id == E.voucher_id))
        .join(VT, and_(VT.company_id == V.company_id, VT.voucher_type_id == V.voucher_type_id))
        .join(L, and_(L.company_id == E.company_id, L.ledger_id == E.ledger_id))
        .where(
            E.company_id == ctx.company_id,
            V.company_id == ctx.company_id,
            V.status.in_(ctx.filter.statuses),
            V.voucher_date.between(since or ctx.filter.date_from, ctx.filter.date_to),
        )
    )


def in_class(*classes: Iterable[uuid.UUID]) -> ColumnElement[bool]:
    """The entry's ledger is anchored in one of these classes; a ledger with no anchor
    (unresolved chain, ACC-7.4) never is."""
    ids = {g for c in classes for g in c}
    return L.classification_group_id.in_(ids) if ids else false()


def nature_in(ctx: MetricContext, *natures: Nature) -> ColumnElement[bool]:
    """The ledger's anchor has one of these natures (an unresolved ledger has none)."""
    anchors = select(Group.group_id).where(
        Group.company_id == ctx.company_id, Group.nature.in_(natures)
    )
    return L.classification_group_id.in_(anchors)


def openings(ctx: MetricContext, ledgers: ColumnElement[bool]) -> Select[Any]:
    """One row per ledger matching `ledgers`: its books-beginning opening, signed Dr +
    (D-039 #5). A ledger with no opening row gets a NULL amount, which makes every total it is
    part of "opening balance unavailable" (ACC-9.6, D-045 #3); a zero opening is a figure
    (D-044 #6)."""
    o = LedgerOpeningBalance
    signed = case(
        (o.accounting_direction == AccountingDirection.DEBIT, o.amount_absolute),
        else_=-o.amount_absolute,
    )
    return (
        select(
            cast(null(), UUID(as_uuid=True)).label("voucher_id"),
            cast(literal(ctx.books_from), Date).label("voucher_date"),
            null().label("voucher_number"),
            literal("Opening balance").label("voucher_type_name"),
            null().label("base_voucher_type"),
            L.ledger_id,
            L.name.label("ledger_name"),
            signed.label("amount"),
        )
        .select_from(L)
        .outerjoin(
            o,
            and_(
                o.company_id == L.company_id,
                o.ledger_id == L.ledger_id,
                o.financial_year_start == ctx.books_from,
            ),
        )
        .where(L.company_id == ctx.company_id, ledgers)
    )


def balance_rows(ctx: MetricContext, ledgers: ColumnElement[bool]) -> Select[Any]:
    """The rows of these ledgers' balances on `filter.date_to` (D-039 #5): the books-beginning
    opening plus every entry from `books_from` to that date. Nothing before books-beginning
    exists, so without a known `books_from` every opening is unavailable."""
    moved = entries(ctx, E.amount_signed, since=ctx.books_from or date.min).where(ledgers)
    rows = union_all(openings(ctx, ledgers), moved).subquery()
    return select(rows)


def party_bucket(ctx: MetricContext, party: Iterable[uuid.UUID]) -> Select[Any]:
    """(voucher_id, party_id) for every voucher with an entry on a ledger in `party` (the
    customer or supplier class): the one such ledger, or NULL when there are several
    (ACC-6.3). A voucher with none has no row, which also means Unattributed (ACC-6.2)."""
    found = func.array_agg(E.ledger_id.distinct(), type_=ARRAY(UUID(as_uuid=True)))
    return (
        select(
            E.voucher_id,
            case((func.cardinality(found) == 1, found[1])).label("party_id"),
        )
        .join(L, and_(L.company_id == E.company_id, L.ledger_id == E.ledger_id))
        .where(E.company_id == ctx.company_id, in_class(party))
        .group_by(E.voucher_id)
    )


def items(ctx: MetricContext, sign: ColumnElement[int]) -> Select[Any]:
    """One row per inventory line dated in the filter's range on a voucher with one of its
    statuses: the standard detail columns (no ledger) with `amount` = sign x the line's
    amount, and the item, `quantity` (same sign) and `unit`. Metrics add their own
    conditions."""
    return (
        select(
            V.voucher_id,
            V.voucher_date,
            V.voucher_number,
            VT.name.label("voucher_type_name"),
            VT.base_voucher_type,
            cast(null(), UUID(as_uuid=True)).label("ledger_id"),
            cast(null(), String).label("ledger_name"),
            (sign * VI.amount).label("amount"),
            VI.stock_item_id,
            SI.name.label("stock_item_name"),
            (sign * VI.quantity).label("quantity"),
            VI.unit,
        )
        .select_from(VI)
        .join(V, and_(V.company_id == VI.company_id, V.voucher_id == VI.voucher_id))
        .join(VT, and_(VT.company_id == V.company_id, VT.voucher_type_id == V.voucher_type_id))
        .join(SI, and_(SI.company_id == VI.company_id, SI.stock_item_id == VI.stock_item_id))
        .where(
            VI.company_id == ctx.company_id,
            V.company_id == ctx.company_id,
            V.status.in_(ctx.filter.statuses),
            V.voucher_date.between(ctx.filter.date_from, ctx.filter.date_to),
        )
    )
