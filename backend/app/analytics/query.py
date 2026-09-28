"""The one query path for every metric (ACC-4.4, FR-DD-5, D-044 #1).

Totals, series, breakdowns and drill-downs are all built here from the metric's single
`detail_query`, so every view of a figure sums the same rows. Nothing else calls
`detail_query` (tests/analytics/test_architecture.py).
"""

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from types import ModuleType
from typing import Any

from sqlalchemy import (
    ColumnElement,
    Date,
    DateTime,
    Integer,
    Select,
    case,
    cast,
    extract,
    func,
    select,
)
from sqlalchemy.ext.asyncio import AsyncSession

from app.analytics.context import MetricContext
from app.analytics.metrics import (
    cash_bank_position,
    cash_flow,
    customer_revenue,
    expenses,
    ledger_balances,
    payables,
    product_revenue,
    purchases,
    receivables,
    sales,
    supplier_purchases,
    unclassified_adjustments,
)
from app.core.periods import Granularity, period_key

METRICS: dict[str, ModuleType] = {
    "sales": sales,
    "customer_revenue": customer_revenue,
    "product_revenue": product_revenue,
    "purchases": purchases,
    "supplier_purchases": supplier_purchases,
    "expenses": expenses,
    "cash_flow": cash_flow,
    "cash_bank_position": cash_bank_position,
    "receivables": receivables,
    "payables": payables,
    "ledger_balances": ledger_balances,
    "unclassified_adjustments": unclassified_adjustments,
}


def detail(metric: str, ctx: MetricContext) -> Select[Any]:
    return METRICS[metric].detail_query(ctx)  # type: ignore[no-any-return]


def bucket(
    column: ColumnElement[Any], granularity: Granularity, ctx: MetricContext
) -> ColumnElement[date]:
    """The first day of the period a row falls in, computed in SQL (D-044 #2).

    A `timestamptz` is first converted to the company's local date with
    `timezone(company_timezone, ts)`, which does not depend on the session's TimeZone; a Tally
    voucher date is a DATE and is used as it is (D-020). Quarters count from the financial
    year start (Q-1.1), or from 1 January in calendar mode (Q-1.2).
    """
    day: ColumnElement[Any] = column
    if isinstance(column.type, DateTime) and column.type.timezone:
        day = cast(func.timezone(ctx.company_timezone, column), Date)
    if granularity == "day":
        return day
    if granularity == "month":
        return cast(func.date_trunc("month", day), Date)
    fy = date(2000, 1, 1) if ctx.quarter_mode == "calendar" else ctx.fy_start
    y, m, d = (cast(extract(f, day), Integer) for f in ("year", "month", "day"))
    # whole months since year 0, counting a month from the financial year's start day
    months = y * 12 + m - 1 - case((d < fy.day, 1), else_=0) - (fy.month - 1)
    start = months // 3 * 3 + (fy.month - 1)
    return func.make_date(start // 12, start % 12 + 1, fy.day, type_=Date)


def _sum(amount: ColumnElement[Any]) -> ColumnElement[Any]:
    """Σ amount, or NULL if any row's amount is NULL: a balance with an unknown opening is
    "opening balance unavailable", never a partial sum (ACC-9.6, D-045 #3)."""
    return case(
        (func.count() > func.count(amount), None),
        else_=func.coalesce(func.sum(amount), 0),
    )


@dataclass(frozen=True)
class Point:
    period: str  # label, as app.core.periods.period_key
    start: date
    amount: Decimal | None


async def total(session: AsyncSession, ctx: MetricContext, metric: str) -> Decimal | None:
    """The figure; None when it is unavailable (see `unavailable`)."""
    rows = detail(metric, ctx).subquery()
    return await session.scalar(select(_sum(rows.c.amount)))


async def unavailable(
    session: AsyncSession, ctx: MetricContext, metric: str, limit: int = 20
) -> tuple[int, list[str]]:
    """How many ledgers make the figure unavailable (no opening row), and the first names
    (D-045 #3)."""
    rows = detail(metric, ctx).subquery()
    missing = select(rows.c.ledger_id, rows.c.ledger_name).where(rows.c.amount.is_(None)).distinct()
    found = missing.subquery()
    count = await session.scalar(select(func.count()).select_from(found))
    names = await session.scalars(
        select(found.c.ledger_name).order_by(found.c.ledger_name).limit(limit)
    )
    return int(count or 0), list(names)


async def series(
    session: AsyncSession, ctx: MetricContext, metric: str, granularity: Granularity
) -> list[Point]:
    """Periods with at least one row, in order (FR-2.1)."""
    rows = detail(metric, ctx).subquery()
    start = bucket(rows.c.voucher_date, granularity, ctx).label("start")
    result = await session.execute(
        select(start, _sum(rows.c.amount)).group_by(start).order_by(start)
    )
    return [
        Point(period_key(s, granularity, ctx.fy_start, ctx.quarter_mode), s, amount)
        for s, amount in result.tuples()
    ]


async def breakdown(
    session: AsyncSession, ctx: MetricContext, metric: str, key: str, label: str
) -> list[tuple[Any, Any, Decimal | None]]:
    """(key, label, amount) per value of a detail column, largest first; an unavailable
    amount (None) first of all."""
    rows = detail(metric, ctx).subquery()
    k, name = rows.c[key], rows.c[label]
    amount = _sum(rows.c.amount)
    result = await session.execute(
        select(k, name, amount).group_by(k, name).order_by(amount.desc().nulls_first(), name, k)
    )
    return list(result.tuples())


async def drilldown(
    session: AsyncSession, ctx: MetricContext, metric: str, *, offset: int = 0, limit: int = 100
) -> tuple[list[dict[str, Any]], int]:
    """A page of the contributing rows (by date, voucher), and how many there are in all."""
    rows = detail(metric, ctx).subquery()
    count = await session.scalar(select(func.count()).select_from(rows))
    page = await session.execute(
        select(rows)
        .order_by(rows.c.voucher_date, rows.c.voucher_number, rows.c.voucher_id, rows.c.ledger_name)
        .offset(offset)
        .limit(limit)
    )
    return [dict(r) for r in page.mappings()], int(count or 0)


PRODUCT_ATTRIBUTION_DIFFERENCE = "Product Attribution Difference"
NON_PRODUCT_REVENUE = "Unattributed / Non-product Sales Revenue"


@dataclass(frozen=True)
class Difference:
    """Total Sales Revenue less Product-attributed Revenue, under exactly one label
    (ACC-VAL-1)."""

    label: str
    amount: Decimal | None
    product_attributed: Decimal | None
    total_sales: Decimal | None


async def product_difference(session: AsyncSession, ctx: MetricContext) -> Difference:
    """ACC-1.9/1.10, D-046 #5: "Unattributed / Non-product Sales Revenue" only once product
    revenue is proven to be on Total Sales' basis (G28 passed and taxable-value mode on);
    until then a data-quality figure, "Product Attribution Difference"."""
    sales, product = (
        await total(session, ctx, "sales"),
        await total(session, ctx, "product_revenue"),
    )
    label = NON_PRODUCT_REVENUE if ctx.product_basis_verified else PRODUCT_ATTRIBUTION_DIFFERENCE
    amount = None if sales is None or product is None else sales - product
    return Difference(label, amount, product, sales)


@dataclass(frozen=True)
class Ranking:
    """A ranked list (TOPN-1.x). Deliberately has no total: a Top-N list is never presented as
    adding up to anything (TOPN-1.4)."""

    rows: list[dict[str, Any]]  # rank, the keys, the label, `value`, `siblings`
    total_count: int  # entries in the full list
    n: int | None  # the cut-off; None = View All

    @property
    def is_top_n(self) -> bool:
        return self.n is not None


async def ranking(
    session: AsyncSession,
    ctx: MetricContext,
    metric: str,
    keys: tuple[str, ...],
    label: str,
    *,
    measure: str = "amount",
    n: int | None = None,
) -> Ranking:
    """The full list, ranked by Σ `measure` (largest first, then label and keys, so ties are
    stable), of every group of the metric's rows whose first key is known: Unattributed
    (a NULL key) is never ranked. `n` only adds a LIMIT to that same query (TOPN-1.2).
    `siblings` is how many groups share the first key (an item sold in two units has 2)."""
    rows = detail(metric, ctx).subquery()
    cols = [rows.c[k] for k in keys]
    name = rows.c[label]
    value = _sum(rows.c[measure])
    ranked = (
        select(
            func.row_number()
            .over(order_by=(value.desc().nulls_first(), name, *cols))
            .label("rank"),
            *cols,
            name,
            value.label("value"),
            func.count().over().label("total_count"),
            func.count().over(partition_by=cols[0]).label("siblings"),
        )
        .where(cols[0].is_not(None))
        .group_by(*cols, name)
        .order_by("rank")
    )
    result = await session.execute(ranked if n is None else ranked.limit(n))
    found = [dict(r) for r in result.mappings()]
    count = found[0]["total_count"] if found else 0
    for r in found:
        del r["total_count"]
    return Ranking(found, int(count), n)


async def unattributed(session: AsyncSession, ctx: MetricContext, metric: str, key: str) -> Decimal:
    """Σ of the metric's rows whose `key` is NULL: the bucket a ranking leaves out."""
    rows = detail(metric, ctx).subquery()
    value = await session.scalar(
        select(func.coalesce(func.sum(rows.c.amount), 0)).where(rows.c[key].is_(None))
    )
    return Decimal(value or 0)
