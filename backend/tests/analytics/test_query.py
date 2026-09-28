"""P8.1: the shared query path (D-044 #1, #2): periods bucketed in SQL in the company's time
zone, and total / series / breakdown / drill-down all summing the same detail rows."""

import uuid
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace
from typing import Any

import pytest
from sqlalchemy import Date, DateTime, cast, func, literal, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.analytics import blocks, query
from app.analytics.classification import Classes
from app.analytics.context import AnalyticsFilter, MetricContext
from app.core.periods import Granularity, QuarterMode, financial_quarter_of, period_key
from app.models.vouchers import VoucherEntry
from tests.analytics.books import Books


def _ctx(fy_start: date = date(2025, 4, 1), mode: QuarterMode = "financial") -> MetricContext:
    none: frozenset[uuid.UUID] = frozenset()
    return MetricContext(
        company_id=uuid.uuid4(),
        filter=AnalyticsFilter(date(2025, 4, 1), date(2026, 3, 31)),
        classes=Classes(none, none, none, none, none, none, none),
        fy_start=fy_start,
        books_from=None,
        company_timezone="Asia/Kolkata",
        quarter_mode=mode,
        taxable_value_mode=True,
        include_journal=True,
        returns_linkable=False,
    )


async def _bucket(session: AsyncSession, value: Any, granularity: Granularity, **kw: Any) -> Any:
    return await session.scalar(select(query.bucket(value, granularity, _ctx(**kw))))


# --- time zones (AC-62, SQL half) ---------------------------------------------------------

# 23:58 IST on 15 March is 18:28 UTC on 15 March, and already 16 March in Kiritimati (UTC+14).
LATE_ON_THE_15TH = datetime(2026, 3, 15, 18, 28, tzinfo=UTC)
# 00:30 IST on 16 March is still 15 March in UTC and New York.
EARLY_ON_THE_16TH = datetime(2026, 3, 15, 19, 0, tzinfo=UTC)


@pytest.mark.req_partial("AC-62")  # the daily series in the API: P8.8
@pytest.mark.parametrize("server_zone", ["UTC", "America/New_York", "Pacific/Kiritimati"])
async def test_a_timestamp_is_grouped_by_the_company_day_whatever_the_server_zone(
    session: AsyncSession, server_zone: str
) -> None:
    await session.execute(text(f"SET LOCAL TimeZone = '{server_zone}'"))
    for instant, local_day in ((LATE_ON_THE_15TH, 15), (EARLY_ON_THE_16TH, 16)):
        ts = literal(instant, DateTime(timezone=True))
        assert await _bucket(session, ts, "day") == date(2026, 3, local_day)
        assert await _bucket(session, ts, "month") == date(2026, 3, 1)
    # A voucher date is a DATE and is never shifted (D-020).
    assert await _bucket(session, literal(date(2026, 3, 15), Date), "day") == date(2026, 3, 15)


# --- quarters and months (AC-63, Q-1.1, Q-1.2) --------------------------------------------


@pytest.mark.parametrize(
    ("fy_start", "mode"),
    [
        (date(2025, 4, 1), "financial"),
        (date(2025, 1, 1), "financial"),
        (date(2025, 7, 15), "financial"),  # a mid-month start (D-034)
        (date(2025, 4, 1), "calendar"),
    ],
)
async def test_sql_periods_match_the_python_calendar_for_every_day(
    session: AsyncSession, fy_start: date, mode: QuarterMode
) -> None:
    days = select(
        cast(
            func.generate_series(
                literal(date(2024, 1, 1)), literal(date(2026, 12, 31)), timedelta(days=1)
            ),
            Date,
        ).label("d")
    ).subquery()
    ctx = _ctx(fy_start, mode)
    rows = await session.execute(
        select(
            days.c.d,
            query.bucket(days.c.d, "quarter", ctx),
            query.bucket(days.c.d, "month", ctx),
        )
    )
    checked = 0
    for day, quarter, month in rows.tuples():
        assert quarter == financial_quarter_of(day, fy_start, mode).start, day
        assert month == day.replace(day=1)
        checked += 1
    assert checked == 1096


# --- one detail query, many views ---------------------------------------------------------


@pytest.fixture
def entries_metric(monkeypatch: pytest.MonkeyPatch) -> str:
    """Stands in for a metric until P8.4: credits on Sales-class ledgers."""
    fake = SimpleNamespace(
        detail_query=lambda ctx: blocks.entries(ctx, VoucherEntry.amount_absolute).where(
            VoucherEntry.accounting_direction == "CREDIT", blocks.in_class(ctx.classes.sales)
        )
    )
    monkeypatch.setitem(query.METRICS, "test_entries", fake)  # type: ignore[arg-type]
    return "test_entries"


async def _sales(books: Books) -> None:
    for day, customer, amount in [
        (date(2025, 6, 30), "Customer A", "1000"),  # FY2025-26 Q1
        (date(2025, 7, 1), "Customer B", "250.50"),  # Q2
        (date(2025, 8, 14), "Customer A", "4000"),  # Q2: an August sale (AC-63)
        (date(2026, 1, 5), "Customer A", "10"),  # Q4
    ]:
        await books.voucher(
            "Sales", day, [(customer, "DEBIT", amount), ("Sales", "CREDIT", amount)]
        )
    await books.voucher(
        "Sales",
        date(2025, 8, 20),
        [("Customer B", "DEBIT", "999"), ("Sales", "CREDIT", "999")],
        status="CANCELLED",
    )


@pytest.mark.req("AC-63")
@pytest.mark.req_partial("FR-2.1", "FR-DD-5")  # the real metrics: P8.4-P8.6
async def test_total_series_breakdown_and_drilldown_sum_the_same_rows(
    books: Books, entries_metric: str
) -> None:
    await _sales(books)
    ctx = await books.ctx()
    s = books.session
    total = await query.total(s, ctx, entries_metric)
    assert total == Decimal("5260.50")
    quarters = await query.series(s, ctx, entries_metric, "quarter")
    assert [(p.period, p.amount) for p in quarters] == [
        ("FY2025-26 Q1", Decimal("1000")),
        ("FY2025-26 Q2", Decimal("4250.50")),  # the August sale is in Q2
        ("FY2025-26 Q4", Decimal("10")),
    ]
    for granularity in ("day", "month", "quarter"):
        points = await query.series(s, ctx, entries_metric, granularity)  # type: ignore[arg-type]
        assert sum(p.amount for p in points) == total
        assert all(
            p.period == period_key(p.start, granularity, ctx.fy_start)
            for p in points  # type: ignore[arg-type]
        )
    ledgers = await query.breakdown(s, ctx, entries_metric, "ledger_id", "ledger_name")
    assert [(name, amount) for _, name, amount in ledgers] == [("Sales", total)]
    rows, count = await query.drilldown(s, ctx, entries_metric, offset=0, limit=2)
    rest, _ = await query.drilldown(s, ctx, entries_metric, offset=2, limit=100)
    assert count == 4 and len(rows) == 2 and len(rest) == 2
    assert sum(r["amount"] for r in rows + rest) == total
    assert [r["voucher_date"] for r in rows + rest] == sorted(
        r["voucher_date"] for r in rows + rest
    )


@pytest.mark.req_partial("ACC-4.5")  # every real metric: P8.4-P8.7
async def test_cancelled_and_missing_vouchers_count_only_when_asked(
    books: Books, entries_metric: str
) -> None:
    await _sales(books)
    await books.voucher(
        "Sales",
        date(2025, 9, 1),
        [("Customer A", "DEBIT", "7"), ("Sales", "CREDIT", "7")],
        status="MISSING_IN_TALLY",
    )
    s = books.session
    assert await query.total(s, await books.ctx(), entries_metric) == Decimal("5260.50")
    widened = await books.ctx(include_cancelled=True)
    assert await query.total(s, widened, entries_metric) == Decimal("6259.50")
    widened = await books.ctx(include_cancelled=True, include_missing=True)
    assert await query.total(s, widened, entries_metric) == Decimal("6266.50")


async def test_dates_outside_the_filter_and_other_companies_are_left_out(
    books: Books, entries_metric: str
) -> None:
    from tests.analytics.books import make_books

    await _sales(books)
    other = await make_books(books.session, name="Other Co")
    await other.voucher(
        "Sales", date(2025, 8, 1), [("Customer A", "DEBIT", "500"), ("Sales", "CREDIT", "500")]
    )
    s = books.session
    q1 = await books.ctx(date(2025, 4, 1), date(2025, 6, 30))
    assert await query.total(s, q1, entries_metric) == Decimal("1000")
    assert await query.total(s, await other.ctx(), entries_metric) == Decimal("500")
