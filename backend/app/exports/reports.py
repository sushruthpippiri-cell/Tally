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
from app.core.periods import Granularity, financial_year_of, now_local, today
from app.core.permissions import CompanyContext
from app.exports.money import format_quantity
from app.exports.report import Bar, Chart, Column, Report, SummaryLine, humanize
from app.models.company import Company
from app.schemas.analytics import DrilldownOut, DrillRow, MetricOut
from app.services import aging, analytics, custom_fields, masters, stock
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


async def effective_range(
    session: AsyncSession, ctx: CompanyContext, params: ExportParams
) -> tuple[date, date]:
    """The dates the report will actually cover: the financial year to date in the company's own
    time zone when the request named neither (the same rule `services.analytics` applies). The
    endpoint needs them before it streams, for the audit row and the file name; a test holds
    this and the report's own header together."""
    company = await _company(session, ctx)
    date_to = params.date_to or today(company.company_timezone)
    date_from = params.date_from or financial_year_of(date_to, company.financial_year_start).start
    return date_from, date_to


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
    # A companion figure (EXP-1.4's other two sales lines) is a different metric with its own
    # group_by options, so it keeps the chosen FR-4.3 filters but not this section's `by`
    # narrowing - which is exactly how the screen shows them, each section filtering `by` to
    # its own levels (pages/AnalyticsPages.tsx).
    companion = Narrowing(params.narrow.customer, params.narrow.product, params.narrow.cost_centre)
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
            narrow=params.narrow if m == name else companion,
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


# --- rankings (TOPN-1.3, TOPN-1.4) -------------------------------------------------------

_RANKINGS = {"customers": "Customers", "suppliers": "Suppliers", "products": "Products"}


async def _ranking_report(
    session: AsyncSession, ctx: CompanyContext, kind: str, params: ExportParams
) -> Report:
    out = await analytics.ranking(
        session,
        ctx,
        kind,  # type: ignore[arg-type]
        date_from=params.date_from,
        date_to=params.date_to,
        top_n=params.top_n,
        view_all=params.view_all,
        rank_by=params.rank_by,
    )
    company = await _company(session, ctx)
    by_quantity = out.rank_by == "quantity"
    columns = [
        Column("rank", "Rank", "integer"),
        Column("name", _RANKINGS[kind].rstrip("s")),
        *(
            [Column("quantity", "Quantity", "quantity"), Column("unit", "Unit")]
            if by_quantity
            else [Column("amount", "Amount", "amount")]
        ),
    ]
    if by_quantity:
        columns.append(Column("multiple_units", "Sold in more than one unit"))
    # TOPN-1.4: the reference total and the figures shown apart, never a total of the rows.
    summary = [
        SummaryLine(out.reference_total.label, out.reference_total.amount),
        *([SummaryLine(f.label, f.amount)] if (f := out.product_attributed) is not None else []),
        *([SummaryLine(d.label, d.amount)] if (d := out.difference) is not None else []),
        *([SummaryLine(u.label, u.amount)] if (u := out.unattributed) is not None else []),
    ]
    return Report(
        title=f"{out.label} {_RANKINGS[kind]} by {out.rank_by}",
        company_name=company.name,
        company_timezone=out.company_timezone,
        meta=await _meta(
            session,
            ctx,
            out.company_timezone,
            date_from=out.filters_applied.date_from,
            date_to=out.filters_applied.date_to,
            extra=[("Listed", out.label), ("Items in all", str(out.total_count))],
            narrow=params.narrow,
            not_applicable=out.filters_applied.not_applicable,
        ),
        summary=summary,
        columns=columns,
        rows=_listed([r.model_dump() for r in out.rows]),
        total_rows=len(out.rows),
        notes=out.notes,
        slug=f"{kind}-by-{out.rank_by}",
    )


async def _listed(rows: list[dict[str, Any]]) -> AsyncIterator[dict[str, Any]]:
    """A report whose rows the service already returned in full."""
    for row in rows:
        yield row


# --- aging (SRS 10) ----------------------------------------------------------------------


async def _aging_report(
    session: AsyncSession, ctx: CompanyContext, side: str, params: ExportParams
) -> Report:
    out = await aging.summary(session, ctx, side, params.date_to)
    company = await _company(session, ctx)
    total = out.total
    columns = [
        Column("ledger_name", "Party"),
        *(Column(f"bucket:{b.key}", b.label, "amount") for b in out.bucket_order),
        Column("bucket_total", "Total outstanding", "amount"),
        Column("credit", "Credit (over-settled)", "amount"),
        Column("unadjusted_advances", "Unadjusted advances", "amount"),
        Column("on_account", "On-Account / Unallocated", "amount"),
        Column("unmatched_settlements", "Unmatched settlements", "amount"),
        Column("net_exposure", "Net exposure", "amount"),
    ]
    notes = list(out.unverified_gates)
    notes += [
        f"{n.ledger_name}: {n.note} - balance "
        + (
            "unavailable"
            if n.balance.amount is None
            else f"{n.balance.amount} {n.balance.direction}"
        )
        for n in out.no_bill_details
    ]
    return Report(
        title=f"{side.capitalize()}s aging",
        company_name=company.name,
        company_timezone=out.company_timezone,
        meta=await _meta(session, ctx, out.company_timezone, as_of=out.as_of, narrow=params.narrow),
        summary=[
            SummaryLine("Total outstanding", total.bucket_total),
            SummaryLine("Credit (over-settled)", total.credit),
            SummaryLine("Unadjusted advances", total.unadjusted_advances),
            SummaryLine("On-Account / Unallocated", total.on_account),
            SummaryLine("Unmatched settlements", total.unmatched_settlements),
            SummaryLine("Net exposure", total.net_exposure),
        ],
        columns=columns,
        rows=_listed([_aging_row(p) for p in out.parties]),
        total_rows=len(out.parties),
        notes=notes,
        slug=f"aging-{side}",
    )


def _aging_row(party: Any) -> dict[str, Any]:
    row = party.model_dump()
    return {**row, **{f"bucket:{k}": v for k, v in party.buckets.items()}}


# --- payment behaviour (SRS 10.4) --------------------------------------------------------


async def _payment_report(session: AsyncSession, ctx: CompanyContext) -> Report:
    out = await aging.payment_behaviour(session, ctx)
    company = await _company(session, ctx)
    tz = company.company_timezone
    rows = [c.model_dump() for c in out.customers]
    notes = list(out.notes) + list(out.unverified_gates)
    if not out.available:
        notes.insert(0, out.reason or "not available")
    overall = out.overall
    extra = []
    if out.window_from and out.window_to:
        extra.append(
            ("Window", f"after {out.window_from.isoformat()} to {out.window_to.isoformat()}")
        )
    return Report(
        title="Customer payment behaviour",
        company_name=company.name,
        company_timezone=tz,
        meta=await _meta(session, ctx, tz, extra=extra),
        summary=[
            SummaryLine(
                "Settlements counted",
                None if overall is None else Decimal(overall.settlements),
                kind="integer",
            ),
            SummaryLine("Settled amount", None if overall is None else overall.settled_amount),
            SummaryLine(
                "Average days to pay",
                None if overall is None else overall.avg_days_to_pay,
                note="insufficient history" if overall and overall.insufficient_history else None,
                kind="integer",
            ),
            SummaryLine(
                "Average days past due",
                None if overall is None else overall.avg_days_past_due,
                kind="integer",
            ),
        ],
        columns=[
            Column("ledger_name", "Customer"),
            Column("settlements", "Settlements", "integer"),
            Column("settled_amount", "Settled amount", "amount"),
            Column("avg_days_to_pay", "Average days to pay", "integer"),
            Column("avg_days_past_due", "Average days past due", "integer"),
            Column("insufficient_history", "Insufficient history"),
        ],
        rows=_listed(rows),
        total_rows=len(rows),
        notes=notes,
        slug="payment-behaviour",
    )


# --- stock (SRS 11) ----------------------------------------------------------------------


async def _stock_report(session: AsyncSession, ctx: CompanyContext, params: ExportParams) -> Report:
    first = await stock.view(session, ctx, params.period_days, params.movement_class, 1, PAGE)
    company = await _company(session, ctx)
    tz = company.company_timezone
    extra = [
        ("Measurement period", f"{first.period_from.isoformat()} to {first.period_to.isoformat()}"),
        ("Snapshot dates", _snapshots(first)),
    ]
    if params.movement_class:
        extra.append(("Class", params.movement_class))
    notes = (
        list(first.warnings)
        + list(first.notes)
        + list(first.limitations)
        + list(first.unverified_gates)
    )
    return Report(
        title="Stock movement",
        company_name=company.name,
        company_timezone=tz,
        meta=await _meta(session, ctx, tz, as_of=first.today, extra=extra),
        summary=[SummaryLine(c.label, Decimal(c.count), kind="integer") for c in first.classes]
        + [
            SummaryLine(
                f"Fast-moving threshold (top {first.fast_percentile}% by sales value)",
                first.fast_threshold,
            )
        ],
        columns=[
            Column("name", "Item"),
            Column("label", "Movement"),
            Column("note", "Note"),
            Column("stock", "Stock", "quantity"),
            Column("stock_unit", "Stock unit"),
            Column("snapshot_date", "Snapshot date", "date"),
            Column("last_sale_date", "Last sale", "date"),
            Column("days_since_last_sale", "Days since last sale", "integer"),
            Column("period_sales_value", "Sales value in period", "amount"),
            Column("period_quantities", "Quantity sold in period"),
            Column("multi_unit", "Sold in more than one unit"),
        ],
        rows=_stock_rows(session, ctx, params, first),
        total_rows=first.total_items,
        notes=notes,
        slug="stock",
    )


def _snapshots(out: Any) -> str:
    oldest, newest = out.snapshot_dates.oldest, out.snapshot_dates.newest
    if oldest is None:
        return "no snapshot"
    return (
        oldest.isoformat() if oldest == newest else f"{oldest.isoformat()} to {newest.isoformat()}"
    )


async def _stock_rows(
    session: AsyncSession, ctx: CompanyContext, params: ExportParams, first: Any
) -> AsyncIterator[dict[str, Any]]:
    page, seen, number = first, 0, 1
    while True:
        for item in page.items:
            row = item.model_dump()
            # FR-STK-10: quantities per unit, written side by side, never added together.
            row["period_quantities"] = "; ".join(
                f"{format_quantity(q.quantity)} {q.unit or ''}".strip()
                for q in item.period_quantities
            )
            yield row
        seen += len(page.items)
        if seen >= page.total_items or not page.items:
            return
        number += 1
        page = await stock.view(
            session, ctx, params.period_days, params.movement_class, number, PAGE
        )


# --- dispatch ----------------------------------------------------------------------------


async def build(
    session: AsyncSession, ctx: CompanyContext, report: str, params: ExportParams
) -> Report:
    if report in _TITLES:
        return await _metric_report(session, ctx, report, params)
    if report in _RANKINGS:
        return await _ranking_report(session, ctx, report, params)
    if report in ("aging-receivable", "aging-payable"):
        return await _aging_report(session, ctx, report.removeprefix("aging-"), params)
    if report == "payment-behaviour":
        return await _payment_report(session, ctx)
    if report == "stock":
        return await _stock_report(session, ctx, params)
    raise AppError(ErrorCode.VALIDATION_ERROR, f"Unknown report: {report}", 422)


REPORTS: tuple[str, ...] = (
    *_TITLES,
    *_RANKINGS,
    "aging-receivable",
    "aging-payable",
    "payment-behaviour",
    "stock",
)
