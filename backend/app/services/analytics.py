"""The analytics API over `app.analytics.query` (P8.8). Every figure here comes from the
metric's one detail query through query.py (ACC-4.4); nothing is computed on its own."""

from datetime import date
from decimal import Decimal
from enum import StrEnum
from typing import Any, Literal

from sqlalchemy.ext.asyncio import AsyncSession

from app.analytics import query
from app.analytics.context import AnalyticsFilter, MetricContext, load
from app.analytics.metrics import customer_revenue, supplier_purchases
from app.core.errors import AppError
from app.core.periods import Granularity, financial_year_of, today
from app.core.permissions import CompanyContext
from app.models.company import Company
from app.schemas.analytics import (
    BreakdownRow,
    DrilldownOut,
    DrillRow,
    Figure,
    FiltersApplied,
    LabelledAmount,
    MetricOut,
    RankedRow,
    RankingOut,
    SeriesPoint,
)
from app.services.settings import get_setting
from tally_contract.errors import ErrorCode

MetricName = StrEnum(  # type: ignore[misc]
    "MetricName",
    {
        name.upper(): name.replace("_", "-")
        for name in query.METRICS
        if name not in query.NOT_IN_METRIC_API
    },
)
STANDARD = {
    "voucher_id",
    "voucher_date",
    "voucher_number",
    "voucher_type_name",
    "base_voucher_type",
    "ledger_id",
    "ledger_name",
    "amount",
}
RETURNS = {
    "sales",
    "purchases",
    "unclassified_adjustments",
    "customer_revenue",
    "supplier_purchases",
    "product_revenue",
}
MAX_NAMED = 20
NO_OPENING_CHECK = "ledgers_without_opening_balance"


def _key(metric: MetricName) -> str:
    return str(metric.value).replace("-", "_")


def _is_balance(metric: str) -> bool:
    return getattr(query.METRICS[metric], "KIND", "flow") == "balance"


def _figure(amount: Decimal | None, balance: bool) -> Figure:
    if amount is None:
        return Figure(amount=None, available=False)
    if not balance:
        return Figure(amount=amount)
    return Figure(amount=abs(amount), direction="Dr" if amount >= 0 else "Cr")


async def _context(
    session: AsyncSession,
    ctx: CompanyContext,
    date_from: date | None,
    date_to: date | None,
    include_cancelled: bool,
    include_missing: bool,
) -> MetricContext:
    """Dates default to the financial year to date, in the company's time zone (TZ-1.x)."""
    company = await session.get(Company, ctx.company_id)
    if company is None:
        raise AppError(ErrorCode.NOT_FOUND, "Company not found", 404)
    now = today(company.company_timezone)
    date_to = date_to or now
    date_from = date_from or financial_year_of(date_to, company.financial_year_start).start
    flt = AnalyticsFilter(date_from, date_to, include_cancelled, include_missing)
    return await load(session, ctx, flt)


def _applied(mc: MetricContext, granularity: Granularity, group_by: str | None) -> FiltersApplied:
    f = mc.filter
    return FiltersApplied(
        date_from=f.date_from,
        date_to=f.date_to,
        granularity=granularity,
        group_by=group_by,
        include_cancelled=f.include_cancelled,
        include_missing=f.include_missing,
    )


def _dimension(metric: str, group_by: str | None) -> tuple[str | None, tuple[str, str]]:
    options: dict[str, tuple[str, str]] = getattr(query.METRICS[metric], "GROUP_BY", {})
    name = group_by or next(iter(options), None)
    if name is None or name not in options:
        raise AppError(
            ErrorCode.VALIDATION_ERROR,
            f"group_by must be one of {sorted(options)} for this metric",
            422,
        )
    return name, options[name]


def _notes(metric: str, mc: MetricContext, missing: tuple[int, list[str]]) -> list[str]:
    notes = [n for n in [getattr(query.METRICS[metric], "NOTE", None)] if n]
    if metric in RETURNS and not mc.returns_linkable:
        notes.append(
            "Until the return-link gate (G26) passes, no credit or debit note is subtracted "
            "from sales or purchases; every note is listed under Unclassified Adjustments."
        )
    if _is_balance(metric):
        notes.append(
            f"Balances are as at {mc.filter.date_to}: each ledger's opening at the start of "
            f"the books ({mc.books_from}) plus every movement since."
        )
    count, names = missing
    if count:
        more = f" and {count - len(names)} more" if count > len(names) else ""
        notes.append(
            f"Opening balance unavailable for {count} ledger(s): {', '.join(names)}{more}. "
            f"See Data Quality, check '{NO_OPENING_CHECK}'."
        )
    return notes


async def metric(
    session: AsyncSession,
    ctx: CompanyContext,
    name: MetricName,
    *,
    date_from: date | None,
    date_to: date | None,
    granularity: Granularity,
    group_by: str | None,
    include_cancelled: bool,
    include_missing: bool,
) -> MetricOut:
    key = _key(name)
    group, (dim_key, dim_label) = _dimension(key, group_by)
    mc = await _context(session, ctx, date_from, date_to, include_cancelled, include_missing)
    balance = _is_balance(key)
    missing = await query.unavailable(session, mc, key, MAX_NAMED) if balance else (0, [])
    summary = _figure(await query.total(session, mc, key), balance)
    summary.unavailable_count, summary.unavailable_ledgers = missing
    series = (
        []
        if balance
        else [
            SeriesPoint(period=p.period, start=p.start, amount=p.amount)
            for p in await query.series(session, mc, key, granularity)
        ]
    )
    rows = await query.breakdown(session, mc, key, dim_key, dim_label)
    return MetricOut(
        metric=str(name.value),
        filters_applied=_applied(mc, granularity, group),
        company_timezone=mc.company_timezone,
        summary=summary,
        series=series,
        breakdown=[
            BreakdownRow(
                key=None if k is None else str(k),
                label=None if label is None else str(label),
                figure=_figure(amount, balance),
            )
            for k, label, amount in rows
        ],
        notes=_notes(key, mc, missing),
    )


def _row(r: dict[str, Any]) -> DrillRow:
    return DrillRow(
        **{k: r[k] for k in STANDARD},
        dimensions={k: None if v is None else str(v) for k, v in r.items() if k not in STANDARD},
    )


async def drilldown(
    session: AsyncSession,
    ctx: CompanyContext,
    name: MetricName,
    *,
    date_from: date | None,
    date_to: date | None,
    include_cancelled: bool,
    include_missing: bool,
    page: int,
    page_size: int,
) -> DrilldownOut:
    key = _key(name)
    mc = await _context(session, ctx, date_from, date_to, include_cancelled, include_missing)
    rows, count = await query.drilldown(
        session, mc, key, offset=(page - 1) * page_size, limit=page_size
    )
    return DrilldownOut(
        metric=str(name.value),
        filters_applied=_applied(mc, "day", None),
        total=await query.total(session, mc, key),
        total_rows=count,
        page=page,
        page_size=page_size,
        rows=[_row(r) for r in rows],
    )


# --- rankings (P9.5, TOPN-1.x, FR-2.4) ------------------------------------------------------

RankingKind = Literal["customers", "suppliers", "products"]
RankBy = Literal["revenue", "quantity"]
_RANKED: dict[str, tuple[str, str]] = {  # kind -> (metric, reference metric)
    "customers": ("customer_revenue", "sales"),
    "suppliers": ("supplier_purchases", "purchases"),
    "products": ("product_revenue", "sales"),
}
_REFERENCE = {"sales": "Total Sales Revenue", "purchases": "Purchase Value"}
_UNATTRIBUTED = {
    "customers": customer_revenue.UNATTRIBUTED,
    "suppliers": supplier_purchases.UNATTRIBUTED,
}
UNITS_NOTE = (
    "Quantities are in each item's own unit and are never added across units. An item marked "
    "multiple_units was sold in more than one unit and appears once per unit; converting to "
    "base units waits for the unit-data gate (G27)."
)


async def ranking(
    session: AsyncSession,
    ctx: CompanyContext,
    kind: RankingKind,
    *,
    date_from: date | None,
    date_to: date | None,
    top_n: int | None,
    view_all: bool,
    rank_by: RankBy,
) -> RankingOut:
    metric, reference = _RANKED[kind]
    if rank_by == "quantity" and kind != "products":
        raise AppError(ErrorCode.VALIDATION_ERROR, "only products can be ranked by quantity", 422)
    mc = await _context(session, ctx, date_from, date_to, False, False)
    n = (
        None
        if view_all
        else top_n or await get_setting(session, mc.company_id, "analytics.top_n_default")
    )
    if kind == "products":
        keys = ("stock_item_id", "unit") if rank_by == "quantity" else ("stock_item_id",)
        label = "stock_item_name"
    else:
        keys, label = ("party_id",), "party_name"
    measure = "quantity" if rank_by == "quantity" else "amount"
    ranked = await query.ranking(session, mc, metric, keys, label, measure=measure, n=n)
    rows = [
        RankedRow(
            rank=r["rank"],
            id=r[keys[0]],
            name=r[label],
            **(
                {"quantity": r["value"], "unit": r["unit"], "multiple_units": r["siblings"] > 1}
                if rank_by == "quantity"
                else {"amount": r["value"]}
            ),
        )
        for r in ranked.rows
    ]
    notes = [
        f"{'Top ' + str(n) if n else 'The list'} is not meant to add up to "
        f"{_REFERENCE[reference]}; it is shown for comparison only."
    ]
    unattributed = product_attributed = difference = None
    if kind == "products":
        diff = await query.product_difference(session, mc)
        product_attributed = LabelledAmount(
            label="Product-attributed Revenue", amount=diff.product_attributed
        )
        difference = LabelledAmount(label=diff.label, amount=diff.amount)
        reference_amount = diff.total_sales
        if rank_by == "quantity":
            notes.append(UNITS_NOTE)
    else:
        unattributed = LabelledAmount(
            label=_UNATTRIBUTED[kind],
            amount=await query.unattributed(session, mc, metric, "party_id"),
        )
        reference_amount = await query.total(session, mc, reference)
    return RankingOut(
        ranking=kind,
        rank_by=rank_by,
        label=f"Top {n}" if n else "All",
        is_top_n=ranked.is_top_n,
        n=n,
        total_count=ranked.total_count,
        filters_applied=_applied(mc, "month", None),
        company_timezone=mc.company_timezone,
        rows=rows,
        unattributed=unattributed,
        product_attributed=product_attributed,
        difference=difference,
        reference_total=LabelledAmount(label=_REFERENCE[reference], amount=reference_amount),
        notes=notes,
    )
