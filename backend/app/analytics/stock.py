"""Stock movement classification (SRS 11, FR-STK-1-20, D-050).

Sales come only from the `product_revenue` detail query (P9: sales lines +, linked credit
notes' lines -), through `query.detail`; current stock is Tally's own closing quantity in
`stock_snapshots` (FR-STK-15). "Today" is the company's local date (TZ-1.1); the period is
the N days ending today. First match wins (D-050 #4):

    1 FAST            sold in the period, value >= the fast threshold
    2 NORMAL          sold in the period, below it
    3 STOCK_UNKNOWN   not sold in the period, no snapshot (never treated as zero)
    4 NOT_CLASSIFIED  not sold in the period, stock <= 0 (FR-STK-19)
    5 NEVER_SOLD      stock > 0, no sale since the books began (FR-STK-12/13)
    6 DEAD            stock > 0, days since last sale >= dead days (FR-STK-5)
    7 SLOW            stock > 0, slow days < days since last sale < dead days (FR-STK-4)
    8 NORMAL + note   stock > 0, last sale within slow days but outside the period (D-009)
"""

from dataclasses import dataclass, replace
from datetime import date, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    Date,
    Integer,
    Numeric,
    Select,
    and_,
    case,
    cast,
    func,
    literal,
    select,
    type_coerce,
)

from app.analytics import query
from app.analytics.context import AnalyticsFilter, MetricContext
from app.core.gates import gate_passed
from app.models.balances import StockSnapshot
from app.models.enums import BaseVoucherType, MasterStatus
from app.models.masters import StockItem

FAST, NORMAL, SLOW, DEAD = "FAST", "NORMAL", "SLOW", "DEAD"
NEVER_SOLD, NOT_CLASSIFIED, STOCK_UNKNOWN = "NEVER_SOLD", "NOT_CLASSIFIED", "STOCK_UNKNOWN"
CLASSES = [FAST, NORMAL, SLOW, DEAD, NEVER_SOLD, STOCK_UNKNOWN, NOT_CLASSIFIED]
GAP_NOTE = "no sale in selected period"
GATES = ("G18", "G27")  # snapshot quantity; units
SALE = BaseVoucherType.SALES.value


@dataclass(frozen=True)
class Thresholds:
    period_days: int  # N: 30, 60, 90 or 180 (FR-STK-1)
    fast_percentile: int  # P, 1-99 (FR-STK-2)
    slow_days: int  # S (FR-STK-4)
    dead_days: int  # K > S (FR-STK-5)


def unverified_gates() -> list[str]:
    return [g for g in GATES if not gate_passed(g)]


def period_context(ctx: MetricContext, today: date, t: Thresholds) -> MetricContext:
    """The N days ending today (D-050 #2)."""
    return _with(ctx, today - timedelta(days=t.period_days - 1), today)


def history_context(ctx: MetricContext, today: date) -> MetricContext:
    """Everything synced up to today: from the books' beginning (D-050 #6)."""
    return _with(ctx, min(ctx.books_from or today, today), today)


def _with(ctx: MetricContext, start: date, end: date) -> MetricContext:
    return replace(ctx, filter=AnalyticsFilter(start, end))


def _period(ctx: MetricContext, today: date, t: Thresholds) -> Any:
    r = query.detail("product_revenue", period_context(ctx, today, t)).subquery()
    return (
        select(
            r.c.stock_item_id,
            func.bool_or(r.c.base_voucher_type == SALE).label("sold"),
            func.sum(r.c.amount).label("value"),
        ).group_by(r.c.stock_item_id)
    ).subquery()


def _last_sale(ctx: MetricContext, today: date) -> Any:
    r = query.detail("product_revenue", history_context(ctx, today)).subquery()
    return (
        select(
            r.c.stock_item_id,
            func.max(r.c.voucher_date).filter(r.c.base_voucher_type == SALE).label("last_sale"),
        ).group_by(r.c.stock_item_id)
    ).subquery()


def snapshots(ctx: MetricContext, today: date) -> Any:
    """Each item's latest snapshot dated on or before today (FR-STK-15)."""
    s = StockSnapshot
    return (
        select(s.stock_item_id, s.as_of_date, s.closing_quantity, s.unit)
        .where(s.company_id == ctx.company_id, s.as_of_date <= today)
        .distinct(s.stock_item_id)
        .order_by(s.stock_item_id, s.as_of_date.desc())
    ).subquery()


def fast_threshold(period: Any, percentile: int) -> Any:
    """FR-STK-2, D-050 #3: the continuous percentile of the sold items' period values, exactly
    as PostgreSQL's percentile_cont defines it (linear interpolation between the values at
    positions floor(f(n-1)) and ceil(f(n-1)) in ascending order), computed in NUMERIC so money
    is never a float (rule 10). NULL when nothing was sold."""
    f = Decimal(percentile) / 100
    ranked = (
        select(
            period.c.value,
            (func.row_number().over(order_by=period.c.value) - 1).label("i"),
            func.count().over().label("n"),
        ).where(period.c.sold)
    ).subquery()
    pos = cast(literal(f), Numeric) * (ranked.c.n - 1)
    lo = func.floor(pos)
    frac = pos - lo
    weight = case((ranked.c.i == lo, 1 - frac), (ranked.c.i == lo + 1, frac), else_=0)
    return select(func.sum(ranked.c.value * weight)).scalar_subquery()


def classified(ctx: MetricContext, today: date, t: Thresholds) -> Select[Any]:
    """One row per ACTIVE stock item: its class, the note, the stock (NULL = unknown) and the
    snapshot date it used, the last sale and days since it, and the period value."""
    period = _period(ctx, today, t)
    last = _last_sale(ctx, today)
    snap = snapshots(ctx, today)
    threshold = fast_threshold(period, t.fast_percentile)
    sold = func.coalesce(period.c.sold, False)
    stock = snap.c.closing_quantity
    days = type_coerce(cast(literal(today), Date) - last.c.last_sale, Integer)
    klass = case(
        (and_(sold, period.c.value >= threshold), FAST),
        (sold, NORMAL),
        (snap.c.stock_item_id.is_(None), STOCK_UNKNOWN),
        (stock <= 0, NOT_CLASSIFIED),
        (last.c.last_sale.is_(None), NEVER_SOLD),
        (days >= t.dead_days, DEAD),
        (days > t.slow_days, SLOW),
        else_=NORMAL,
    )
    gap = and_(~sold, stock > 0, last.c.last_sale.is_not(None), days <= t.slow_days)
    i = StockItem
    return (
        select(
            i.stock_item_id,
            i.name.label("stock_item_name"),
            klass.label("movement_class"),
            case((gap, GAP_NOTE)).label("note"),
            stock.label("stock"),
            snap.c.unit.label("stock_unit"),
            snap.c.as_of_date.label("snapshot_date"),
            last.c.last_sale.label("last_sale_date"),
            days.label("days_since_last_sale"),
            sold.label("sold_in_period"),
            func.coalesce(period.c.value, 0).label("period_sales_value"),
            threshold.label("threshold"),
        )
        .select_from(i)
        .outerjoin(period, period.c.stock_item_id == i.stock_item_id)
        .outerjoin(last, last.c.stock_item_id == i.stock_item_id)
        .outerjoin(snap, snap.c.stock_item_id == i.stock_item_id)
        .where(i.company_id == ctx.company_id, i.status == MasterStatus.ACTIVE)
    )


def quantities(ctx: MetricContext, today: date, t: Thresholds) -> Select[Any]:
    """Period quantity per (item, unit): never added across units (FR-STK-10)."""
    r = query.detail("product_revenue", period_context(ctx, today, t)).subquery()
    return select(r.c.stock_item_id, r.c.unit, func.sum(r.c.quantity).label("quantity")).group_by(
        r.c.stock_item_id, r.c.unit
    )


def multi_unit_items(ctx: MetricContext, today: date) -> Select[Any]:
    """Items seen in more than one transaction unit in the synced history (FR-STK-10)."""
    r = query.detail("product_revenue", history_context(ctx, today)).subquery()
    return (
        select(
            r.c.stock_item_id,
            r.c.stock_item_name,
            func.array_agg(r.c.unit.distinct()).label("units"),
        )
        .group_by(r.c.stock_item_id, r.c.stock_item_name)
        .having(func.count(r.c.unit.distinct()) > 1)
    )
