"""Builds a `Report` from the services the screen calls (EXP-1.3).

Every figure here is returned by `app.services.analytics` / `aging` / `stock` - the same
functions `app/api/analytics.py` calls - so a file can never disagree with the page it came
from (AC-39). This module only chooses titles, columns and headings.
"""

import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError
from app.core.periods import Granularity, now_local
from app.core.permissions import CompanyContext
from app.exports.report import Bar, Chart, Column, Report, SummaryLine, humanize
from app.models.company import Company
from app.schemas.analytics import DrilldownOut, DrillRow, MetricOut
from app.services import analytics, custom_fields, masters
from app.services.analytics import NO_NARROWING, MetricName, Narrowing, RankBy
from tally_contract.enums import CollectionType
from tally_contract.errors import ErrorCode

PAGE = 500  # rows per drill-down call while streaming

# The metrics whose page draws the by-month chart (`chart` on MetricSection in
# frontend/src/pages/AnalyticsPages.tsx). EXP-1.2 is "the charts shown on screen": a PDF of
# another metric shows no chart, because its page shows none.
CHARTED = frozenset({"sales", "purchases", "cash-flow", "expenses"})

# Dimension columns the screen does not show either: the owner reads names, not keys.
_HIDDEN_SUFFIX = "_id"

FILTER_LABELS = {"customer": "Customer", "product": "Product", "cost_centre": "Cost centre"}

# Balance metrics: their rows are `amount_signed` (debit positive), so the CSV gets a signed
# "Amount (Dr +)" column plus a Dr/Cr column read off that sign (D-053 #6).
_BALANCES = frozenset({"cash-bank-position", "receivables", "payables", "ledger-balances"})


@dataclass(frozen=True)
class ExportParams:
    """Everything the four report families take, parsed once by the endpoint."""

    date_from: date | None = None
    date_to: date | None = None
    granularity: Granularity = "month"
    group_by: str | None = None
    include_cancelled: bool = False
    include_missing: bool = False
    narrow: Narrowing = NO_NARROWING
    rank_by: RankBy = "revenue"
    top_n: int | None = None
    view_all: bool = False
    period_days: int | None = None
    movement_class: str | None = None


async def _company(session: AsyncSession, ctx: CompanyContext) -> Company:
    company = await session.get(Company, ctx.company_id)
    if company is None:
        raise AppError(ErrorCode.NOT_FOUND, "Company not found", 404)
    return company


async def _meta(
    session: AsyncSession,
    ctx: CompanyContext,
    tz: str,
    *,
    date_from: date | None = None,
    date_to: date | None = None,
    as_of: date | None = None,
    extra: list[tuple[str, str]] | None = None,
    narrow: Narrowing = NO_NARROWING,
    not_applicable: list[str] | None = None,
) -> list[tuple[str, str]]:
    """EXP-1.1's header block: the date range, every active filter and the generation time in
    the company's own time zone (TZ-1.1)."""
    meta: list[tuple[str, str]] = []
    if date_from is not None and date_to is not None:
        meta.append(("Date range", f"{date_from.isoformat()} to {date_to.isoformat()}"))
    if as_of is not None:
        meta.append(("As of", as_of.isoformat()))
    meta += extra or []
    for name, label in FILTER_LABELS.items():
        chosen: uuid.UUID | None = getattr(narrow, name)
        if chosen is None:
            continue
        found = await masters.options(session, ctx, name, None, chosen)  # type: ignore[arg-type]
        shown = found[0].name if found else str(chosen)
        if name in (not_applicable or []):
            shown += " (does not apply to this figure)"
        meta.append((f"Filter: {label}", shown))
    for text in narrow.by:
        option, _, key = text.partition(":")
        meta.append((f"Narrowed by {humanize(option).lower()}", key))
    stamp = now_local(tz)
    meta.append(("Generated", f"{stamp.strftime('%d %b %Y, %H:%M')} ({tz})"))
    return meta


# --- the metric family -------------------------------------------------------------------


def _udf_columns(mappings: list[Any]) -> list[Column]:
    """One column per active voucher mapping, in the mapping's own order (EXP-1.5, DR-UDF-2)."""
    return [
        Column(f"udf:{m.field_key}", humanize(m.field_key))
        for m in mappings
        if m.collection_type == CollectionType.VOUCHER
    ]


def _metric_columns(metric: str, rows: list[DrillRow], udf: list[Column]) -> list[Column]:
    dimensions = [
        key
        for key in (rows[0].dimensions if rows else {})
        if not key.endswith(_HIDDEN_SUFFIX) and key not in ("quantity", "unit")
    ]
    columns = [
        Column("voucher_date", "Date", "date"),
        Column("voucher_number", "Voucher no."),
        Column("voucher_type_name", "Voucher type"),
        Column("ledger_name", "Ledger"),
        *(Column(key, humanize(key)) for key in dimensions),
    ]
    if rows and "quantity" in rows[0].dimensions:
        columns += [Column("quantity", "Quantity", "quantity"), Column("unit", "Unit")]
    if metric in _BALANCES:
        columns += [
            Column("amount", "Amount (Dr +)", "signed_amount"),
            Column("direction", "Dr/Cr"),
        ]
    else:
        columns.append(Column("amount", "Amount", "amount"))
    return columns + udf


def _dr_cr(amount: Decimal | None) -> str:
    """The side of a balance row, read off the sign of the same number - not a second figure."""
    if amount is None or not amount:
        return ""
    return "Dr" if amount > 0 else "Cr"


def _flatten(row: DrillRow, udf: list[Column]) -> dict[str, Any]:
    out: dict[str, Any] = {
        "voucher_date": row.voucher_date,
        "voucher_number": row.voucher_number,
        "voucher_type_name": row.voucher_type_name,
        "ledger_name": row.ledger_name,
        "amount": row.amount,
        "direction": _dr_cr(row.amount),
        **row.dimensions,
    }
    for column in udf:
        out[column.key] = (row.custom_fields or {}).get(column.key.removeprefix("udf:"))
    return out


async def _metric_report(
    session: AsyncSession, ctx: CompanyContext, name: str, params: ExportParams
) -> Report:
    metric_name = MetricName(name)
    summary_metrics = _SALES_SUMMARY if name == "sales" else (metric_name,)
    figures = [
        await analytics.metric(
            session,
            ctx,
            MetricName(m),
            date_from=params.date_from,
            date_to=params.date_to,
            granularity=params.granularity,
            group_by=params.group_by if m == name else None,
            include_cancelled=params.include_cancelled,
            include_missing=params.include_missing,
            narrow=params.narrow,
        )
        for m in summary_metrics
    ]
    head = figures[0]
    first = await _page(session, ctx, metric_name, params, 1)
    company = await _company(session, ctx)
    udf = _udf_columns(await custom_fields.list_mappings(session, ctx))
    applied = head.filters_applied
    return Report(
        title=head.label or _TITLES[name],
        company_name=company.name,
        company_timezone=head.company_timezone,
        meta=await _meta(
            session,
            ctx,
            head.company_timezone,
            date_from=applied.date_from,
            date_to=applied.date_to,
            narrow=params.narrow,
            not_applicable=applied.not_applicable,
        ),
        summary=[_summary_line(f) for f in figures],
        columns=_metric_columns(name, first.rows, udf),
        rows=_metric_rows(session, ctx, metric_name, params, first, udf),
        total_rows=first.total_rows,
        notes=head.notes + _not_applicable_notes(applied.not_applicable, _TITLES[name]),
        charts=_metric_charts(head, name),
        slug=name,
    )


_SALES_SUMMARY = ("sales", "product-revenue", "product-difference")
_TITLES = {
    "sales": "Total Sales Revenue",
    "customer-revenue": "Customer-attributed Revenue",
    "product-revenue": "Product-attributed Revenue",
    "product-difference": "Product Attribution Difference",
    "purchases": "Purchase Value",
    "supplier-purchases": "Supplier-attributed Purchases",
    "expenses": "Expenses",
    "cash-flow": "Net cash flow",
    "cash-bank-position": "Cash and bank position",
    "receivables": "Receivables",
    "payables": "Payables",
    "ledger-balances": "Ledger balances",
    "unclassified-adjustments": "Unclassified Adjustments",
}


def _summary_line(figure: MetricOut) -> SummaryLine:
    note = None
    if not figure.summary.available or figure.summary.unavailable_count:
        note = (
            f"opening balance unavailable for {figure.summary.unavailable_count} ledger(s): "
            + ", ".join(figure.summary.unavailable_ledgers)
        )
    return SummaryLine(
        label=figure.label or _TITLES[figure.metric],
        amount=figure.summary.amount,
        direction=figure.summary.direction,
        note=note,
    )


def _not_applicable_notes(not_applicable: list[str], title: str) -> list[str]:
    return [
        f"The {FILTER_LABELS.get(f, f).lower()} filter does not apply to {title}, "
        "so this figure is not narrowed by it."
        for f in not_applicable
    ]


def _metric_charts(figure: MetricOut, name: str) -> list[Chart]:
    if name not in CHARTED or not figure.series:
        return []
    title = f"{figure.label or _TITLES[name]} by {figure.filters_applied.granularity}"
    return [Chart(title, [Bar(p.period, p.amount) for p in figure.series])]


async def _page(
    session: AsyncSession,
    ctx: CompanyContext,
    name: MetricName,
    params: ExportParams,
    page: int,
) -> DrilldownOut:
    return await analytics.drilldown(
        session,
        ctx,
        name,
        date_from=params.date_from,
        date_to=params.date_to,
        include_cancelled=params.include_cancelled,
        include_missing=params.include_missing,
        page=page,
        page_size=PAGE,
        narrow=params.narrow,
    )


async def _metric_rows(
    session: AsyncSession,
    ctx: CompanyContext,
    name: MetricName,
    params: ExportParams,
    first: DrilldownOut,
    udf: list[Column],
) -> AsyncIterator[dict[str, Any]]:
    """The first page is already in hand (its columns shaped the table); the rest are fetched
    as the renderer consumes them, so a large CSV streams."""
    page, seen = first, 0
    while True:
        for row in page.rows:
            yield _flatten(row, udf)
        seen += len(page.rows)
        if seen >= page.total_rows or not page.rows:
            return
        page = await _page(session, ctx, name, params, page.page + 1)


# --- dispatch ----------------------------------------------------------------------------


async def build(
    session: AsyncSession, ctx: CompanyContext, report: str, params: ExportParams
) -> Report:
    if report in _TITLES:
        return await _metric_report(session, ctx, report, params)
    raise AppError(ErrorCode.VALIDATION_ERROR, f"Unknown report: {report}", 422)
