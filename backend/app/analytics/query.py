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
from app.core.periods import Granularity, period_key

METRICS: dict[str, ModuleType] = {}


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


@dataclass(frozen=True)
class Point:
    period: str  # label, as app.core.periods.period_key
    start: date
    amount: Decimal


async def total(session: AsyncSession, ctx: MetricContext, metric: str) -> Decimal:
    rows = detail(metric, ctx).subquery()
    value = await session.scalar(select(func.coalesce(func.sum(rows.c.amount), 0)))
    return Decimal(value or 0)


async def series(
    session: AsyncSession, ctx: MetricContext, metric: str, granularity: Granularity
) -> list[Point]:
    """Periods with at least one row, in order (FR-2.1)."""
    rows = detail(metric, ctx).subquery()
    start = bucket(rows.c.voucher_date, granularity, ctx).label("start")
    result = await session.execute(
        select(start, func.sum(rows.c.amount)).group_by(start).order_by(start)
    )
    return [
        Point(period_key(s, granularity, ctx.fy_start, ctx.quarter_mode), s, amount)
        for s, amount in result.tuples()
    ]


async def breakdown(
    session: AsyncSession, ctx: MetricContext, metric: str, key: str, label: str
) -> list[tuple[Any, Any, Decimal]]:
    """(key, label, amount) per value of a detail column, largest first."""
    rows = detail(metric, ctx).subquery()
    k, name = rows.c[key], rows.c[label]
    amount = func.sum(rows.c.amount)
    result = await session.execute(
        select(k, name, amount).group_by(k, name).order_by(amount.desc(), name, k)
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
