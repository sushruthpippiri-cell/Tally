"""Stock movement for the API (SRS 11, D-050). "Today" is the company's local date (TZ-1.1);
the classification itself is `app.analytics.stock`."""

from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.analytics import stock
from app.analytics.context import AnalyticsFilter, load
from app.core.errors import AppError
from app.core.periods import today as local_today
from app.core.permissions import CompanyContext
from app.models.balances import StockSnapshot
from app.models.company import Company
from app.schemas.stock import (
    ClassCount,
    SnapshotDates,
    StockItemOut,
    StockOut,
    UnitQuantity,
)
from app.services.settings import get_setting
from tally_contract.errors import ErrorCode

PERIODS = (30, 60, 90, 180)  # FR-STK-1
LIMITATION = (
    "Items sold in more than one unit are not converted to a base unit (gate G27): their "
    "quantities are shown per unit and are not comparable. Movement classes use sales value "
    "and are not affected."
)


def _labels(books_from: object) -> dict[str, str]:
    since = f"No sale since {books_from}" if books_from else "No sale in the synced history"
    return {
        stock.FAST: "Fast-moving",
        stock.NORMAL: "Normal",
        stock.SLOW: "Slow-moving",
        stock.DEAD: "Dead stock",
        stock.NEVER_SOLD: since,  # D-050 #6: the SRS's "Never sold"
        stock.STOCK_UNKNOWN: "Stock unknown",
        stock.NOT_CLASSIFIED: "Not classified",
    }


async def view(
    session: AsyncSession,
    ctx: CompanyContext,
    period_days: int | None,
    movement_class: str | None,
    page: int,
    page_size: int,
) -> StockOut:
    if period_days is not None and period_days not in PERIODS:
        raise AppError(ErrorCode.VALIDATION_ERROR, "period_days must be 30, 60, 90 or 180", 422)
    company = await session.get(Company, ctx.company_id)
    if company is None:
        raise AppError(ErrorCode.NOT_FOUND, "Company not found", 404)
    today = local_today(company.company_timezone)

    async def setting(key: str) -> int:
        return int(await get_setting(session, ctx.company_id, key))

    t = stock.Thresholds(
        period_days=period_days or await setting("stock.measurement_period_days"),
        fast_percentile=await setting("stock.fast_percentile"),
        slow_days=await setting("stock.slow_threshold_days"),
        dead_days=await setting("stock.dead_stock_days"),
    )
    mctx = await load(session, ctx, AnalyticsFilter(today, today))
    rows = stock.classified(mctx, today, t).subquery()
    counted = dict(
        (
            await session.execute(
                select(rows.c.movement_class, func.count()).group_by(rows.c.movement_class)
            )
        )
        .tuples()
        .all()
    )
    summary = (
        await session.execute(
            select(
                func.min(rows.c.snapshot_date),
                func.max(rows.c.snapshot_date),
                func.max(rows.c.threshold),
            )
        )
    ).one()
    wanted = (
        rows.c.movement_class == movement_class
        if movement_class
        else rows.c.movement_class != stock.NOT_CLASSIFIED  # FR-STK-19: out of movement views
    )
    order = case({c: n for n, c in enumerate(stock.CLASSES)}, value=rows.c.movement_class)
    page_rows = (
        await session.execute(
            select(rows)
            .where(wanted)
            .order_by(order, rows.c.stock_item_name, rows.c.stock_item_id)
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
    ).all()
    ids = [r.stock_item_id for r in page_rows]
    quantities: dict[object, list[UnitQuantity]] = {}
    q = stock.quantities(mctx, today, t).subquery()
    for item_id, unit, quantity in (
        await session.execute(select(q).where(q.c.stock_item_id.in_(ids)).order_by(q.c.unit))
    ).tuples():
        quantities.setdefault(item_id, []).append(UnitQuantity(unit=unit, quantity=quantity))
    multi = {r.stock_item_id for r in await session.execute(stock.multi_unit_items(mctx, today))}
    labels = _labels(company.books_from)
    newest = await session.scalar(
        select(func.max(StockSnapshot.as_of_date)).where(
            StockSnapshot.company_id == ctx.company_id, StockSnapshot.as_of_date <= today
        )
    )
    stale = await setting("stock.snapshot_stale_days")
    warnings = []
    if newest is None:
        warnings.append("No closing-stock snapshot has been received from Tally yet.")
    elif (today - newest).days > stale:
        warnings.append(
            f"The newest stock snapshot is from {newest}, {(today - newest).days} days ago: "
            "stock and its classes may be out of date. Check that the Agent is syncing."
        )
    listed = (
        counted.get(movement_class, 0)
        if movement_class
        else sum(n for c, n in counted.items() if c != stock.NOT_CLASSIFIED)
    )
    notes = [
        f"{labels[stock.NEVER_SOLD]}: the synced history starts at the books-beginning date, "
        "so an item sold only before it (for example in an earlier Tally company) is here too."
    ]
    return StockOut(
        today=today,
        books_from=company.books_from,
        period_days=t.period_days,
        period_from=stock.period_context(mctx, today, t).filter.date_from,
        period_to=today,
        fast_percentile=t.fast_percentile,
        fast_threshold=summary[2],
        classes=[
            ClassCount(key=c, label=labels[c], count=counted.get(c, 0)) for c in stock.CLASSES
        ],
        total_items=listed,
        items=[
            StockItemOut(
                stock_item_id=r.stock_item_id,
                name=r.stock_item_name,
                movement_class=r.movement_class,
                label=labels[r.movement_class],
                note=r.note,
                stock=r.stock,
                stock_unit=r.stock_unit,
                snapshot_date=r.snapshot_date,
                last_sale_date=r.last_sale_date,
                days_since_last_sale=r.days_since_last_sale,
                period_sales_value=r.period_sales_value,
                period_quantities=quantities.get(r.stock_item_id, []),
                multi_unit=r.stock_item_id in multi,
            )
            for r in page_rows
        ],
        snapshot_dates=SnapshotDates(oldest=summary[0], newest=summary[1]),
        warnings=warnings,
        notes=notes,
        limitations=[LIMITATION] if "G27" in stock.unverified_gates() else [],
        unverified_gates=stock.unverified_gates(),
    )
