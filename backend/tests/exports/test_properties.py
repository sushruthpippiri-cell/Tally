"""FR-DD-5 as a property: whatever the filters, an export's detail rows add up to the summary
figure printed above them, for every metric.

The individual cases are in tests/api/test_drilldown.py; this is the part that was left as
partial there - random combinations of period, statuses, chosen filter and narrowing.
"""

import uuid
from datetime import date, timedelta
from decimal import Decimal
from typing import Any

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.analytics import query
from app.core.permissions import CompanyContext
from app.exports import reports
from app.exports.reports import ExportParams
from app.models.masters import CostCentre, StockItem
from app.services.analytics import MetricName, Narrowing
from tests.analytics.books import FY_START, Books, make_books
from tests.exports.conftest import table, to_csv

METRICS = [m.value for m in MetricName]
BOOKS_END = date(2026, 3, 31)


@pytest.fixture
async def books(session: AsyncSession) -> Books:
    """One set of books with something of everything: the examples vary the filters, not the
    data (the fixture is function-scoped, so every example shares it - reads only)."""
    books = await make_books(session, name="Property Traders")
    for ledger in books.ledgers:
        await books.opening(ledger, "DEBIT", "0")
    v = books.voucher
    await v(
        "Sales",
        date(2025, 5, 2),
        [
            ("Customer A", "DEBIT", "11800"),
            ("Sales", "CREDIT", "10000"),
            ("Output GST", "CREDIT", "1800"),
        ],
        items=[("Soap", "100", "100", "10000")],
        bills=[(0, "NEW_REF", "INV-1", "11800", date(2025, 6, 1))],
    )
    await v(
        "POS Invoice",
        date(2025, 8, 9),
        [("Cash", "DEBIT", "450"), ("Sales", "CREDIT", "450")],
        items=[("Rice", "9", "50", "450")],
    )
    await v(
        "Sales",
        date(2026, 2, 2),
        [("Customer B", "DEBIT", "900"), ("Sales", "CREDIT", "900")],
        items=[("Pen", "9", "100", "900")],
        status="CANCELLED",
    )
    await v(
        "Sales",
        date(2026, 2, 3),
        [("Customer B", "DEBIT", "700"), ("Sales", "CREDIT", "700")],
        status="MISSING_IN_TALLY",
    )
    await v(
        "Purchase",
        date(2025, 6, 1),
        [("Purchases", "DEBIT", "4000"), ("Supplier S", "CREDIT", "4000")],
    )
    await v(
        "Payment",
        date(2025, 7, 1),
        [("Rent", "DEBIT", "1000"), ("HDFC Bank", "CREDIT", "1000")],
        centres=[(0, "Retail", "600"), (0, "Online", "400")],
    )
    await v(
        "Payment",
        date(2025, 9, 1),
        [("Freight", "DEBIT", "300"), ("Cash", "CREDIT", "300")],
    )
    await v(
        "Receipt",
        date(2025, 9, 3),
        [("HDFC Bank", "DEBIT", "5000"), ("Customer A", "CREDIT", "5000")],
        bills=[(1, "AGST_REF", "INV-1", "5000")],
    )
    await v("Contra", date(2025, 9, 4), [("Cash", "DEBIT", "200"), ("HDFC Bank", "CREDIT", "200")])
    await v(
        "Credit Note",
        date(2026, 1, 10),
        [("Sales", "DEBIT", "300"), ("Customer A", "CREDIT", "300")],
    )
    await v(
        "Journal",
        date(2025, 10, 1),
        [("Rent", "DEBIT", "150"), ("Loan", "CREDIT", "150")],
    )
    return books


def _ctx(books: Books) -> CompanyContext:
    return CompanyContext(books.company.company_id, uuid.uuid4(), frozenset())


@pytest.fixture
async def ids(books: Books) -> dict[str, uuid.UUID]:
    """The ids FR-4.3's filters take: a customer, a product and a cost centre."""
    item = await session_scalar(books, StockItem, StockItem.name == "Soap")
    centre = await session_scalar(books, CostCentre, CostCentre.name == "Retail")
    return {
        "customer": books.ledgers["Customer A"].ledger_id,
        "product": item,
        "cost_centre": centre,
    }


async def session_scalar(books: Books, model: Any, where: Any) -> uuid.UUID:
    found = await books.session.execute(
        select(model).where(model.company_id == books.company.company_id, where)
    )
    row = found.scalars().one()
    return uuid.UUID(str(getattr(row, f"{model.__tablename__[:-1]}_id")))


def _chosen(ids: dict[str, uuid.UUID], which: int) -> dict[str, uuid.UUID]:
    """One of FR-4.3's filters, or none. A filter a metric cannot apply is reported, not
    applied silently (D-053 #1) - and the property must hold either way."""
    keys = ["customer", "product", "cost_centre"]
    return {} if which == 0 else {keys[which - 1]: ids[keys[which - 1]]}


@settings(
    max_examples=40, deadline=None, suppress_health_check=[HealthCheck.function_scoped_fixture]
)
@given(
    metric=st.sampled_from(METRICS),
    start=st.integers(min_value=-40, max_value=400),
    length=st.integers(min_value=0, max_value=400),
    cancelled=st.booleans(),
    missing=st.booleans(),
    which_filter=st.integers(min_value=0, max_value=3),
    narrow=st.booleans(),
)
@pytest.mark.req("FR-DD-5")
@pytest.mark.req("EXP-1.3")
async def test_an_exports_rows_always_add_up_to_its_own_summary(
    books: Books,
    ids: dict[str, uuid.UUID],
    metric: str,
    start: int,
    length: int,
    cancelled: bool,
    missing: bool,
    which_filter: int,
    narrow: bool,
) -> None:
    date_from = FY_START + timedelta(days=start)
    params = ExportParams(
        date_from=date_from,
        date_to=date_from + timedelta(days=length),
        include_cancelled=cancelled,
        include_missing=missing,
        narrow=Narrowing(**_chosen(ids, which_filter)),
    )
    if narrow:
        # The NULL bucket of the metric's own first group_by: "Unattributed", "(No cost
        # centre)" (D-053 #2). Narrowing to real keys is covered case by case in
        # tests/api/test_drilldown.py; here it is one more dimension of randomness.
        option = next(iter(query.METRICS[metric.replace("-", "_")].GROUP_BY))
        params = ExportParams(
            date_from=params.date_from,
            date_to=params.date_to,
            include_cancelled=cancelled,
            include_missing=missing,
            narrow=Narrowing(**_chosen(ids, which_filter), by=(f"{option}:none",)),
        )

    reports.PAGE, original = 2, reports.PAGE
    try:
        report = await reports.build(books.session, _ctx(books), metric, params)
        text = await to_csv(report)
    finally:
        reports.PAGE = original
    summary = report.summary[0]
    expected = summary.amount or Decimal(0)
    if summary.direction == "Cr":
        expected = -expected

    headings = [c.heading for c in report.columns]
    amount = next(h for h in headings if h.startswith("Amount"))
    rows = table(text, headings)
    assert len(rows) == report.total_rows
    assert sum((Decimal(r[amount]) for r in rows if r[amount]), Decimal(0)) == expected
