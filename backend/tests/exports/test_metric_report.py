"""The metric adapter (EXP-1.3, EXP-1.4, EXP-1.5): a report built from the same service calls
the screen makes, rendered to CSV."""

import uuid
from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError
from app.core.permissions import CompanyContext
from app.exports import reports
from app.exports.reports import ExportParams
from app.models.config import CustomFieldMapping
from app.services.analytics import MetricName, Narrowing
from tests.analytics.books import FY_END, FY_START, Books, make_books
from tests.exports.conftest import parse, table, to_csv

RANGE = ExportParams(date_from=FY_START, date_to=FY_END)


@pytest.fixture
async def books(session: AsyncSession) -> Books:
    books = await make_books(session, name="Sharma Trading Co.")
    for ledger in ("Customer A", "Customer B", "Supplier S", "Cash", "HDFC Bank"):
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
        items=[("Soap", "100", "60", "6000")],
    )
    await v(
        "Sales",
        date(2025, 8, 9),
        [("Customer B", "DEBIT", "450"), ("Sales", "CREDIT", "450")],
        items=[("Rice", "9", "50", "450")],
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
        centres=[(0, "Retail", "600")],
    )
    return books


def ctx(books: Books) -> CompanyContext:
    return CompanyContext(books.company.company_id, uuid.uuid4(), frozenset())


@pytest.mark.req("EXP-1.3")
@pytest.mark.parametrize("metric", [m.value for m in MetricName])
async def test_every_metric_exports_rows_that_add_to_its_own_summary(
    session: AsyncSession, books: Books, metric: str
) -> None:
    report = await reports.build(session, ctx(books), metric, RANGE)
    summary = report.summary[0]
    text = await to_csv(report)
    headings = [c.heading for c in report.columns]
    amount = next(h for h in headings if h.startswith("Amount"))
    rows = table(text, headings)
    total = sum((Decimal(r[amount]) for r in rows if r[amount]), Decimal(0))
    expected = summary.amount or Decimal(0)
    if summary.direction == "Cr":
        expected = -expected
    assert total == expected, f"{metric}: {total} != {expected}"
    assert len(rows) == report.total_rows


@pytest.mark.req("EXP-1.4")
async def test_a_sales_export_carries_all_three_figures_and_one_difference_label(
    session: AsyncSession, books: Books
) -> None:
    report = await reports.build(session, ctx(books), "sales", RANGE)
    labels = [line.label for line in report.summary]
    assert labels[:2] == ["Total Sales Revenue", "Product-attributed Revenue"]
    # ACC-VAL-1: exactly one difference label, and it is the backend's own.
    assert labels[2] in (
        "Product Attribution Difference",
        "Unattributed / Non-product Sales Revenue",
    )
    assert len({*labels}) == 3
    amounts = [line.amount for line in report.summary]
    assert amounts[0] is not None and amounts[1] is not None and amounts[2] is not None
    assert amounts[0] - amounts[1] == amounts[2]


@pytest.mark.req("EXP-1.1")
async def test_the_header_names_the_company_the_range_and_the_generation_time(
    session: AsyncSession, books: Books
) -> None:
    report = await reports.build(session, ctx(books), "sales", RANGE)
    meta = dict(report.meta)
    assert report.company_name == "Sharma Trading Co."
    assert meta["Date range"] == "2025-04-01 to 2026-03-31"
    assert report.company_timezone in meta["Generated"]


@pytest.mark.req("EXP-1.1")
async def test_an_active_filter_is_named_in_the_header_by_name_not_id(
    session: AsyncSession, books: Books
) -> None:
    customer = books.ledgers["Customer A"].ledger_id
    params = ExportParams(date_from=FY_START, date_to=FY_END, narrow=Narrowing(customer=customer))
    report = await reports.build(session, ctx(books), "customer-revenue", params)
    assert dict(report.meta)["Filter: Customer"] == "Customer A"


async def test_a_filter_that_cannot_narrow_a_figure_says_so_rather_than_lying(
    session: AsyncSession, books: Books
) -> None:
    # D-053 #1: Total Sales Revenue is never narrowed by customer.
    params = ExportParams(
        date_from=FY_START,
        date_to=FY_END,
        narrow=Narrowing(customer=books.ledgers["Customer A"].ledger_id),
    )
    report = await reports.build(session, ctx(books), "sales", params)
    assert "does not apply to this figure" in dict(report.meta)["Filter: Customer"]
    assert any("does not apply to Total Sales Revenue" in n for n in report.notes)


@pytest.mark.req("EXP-1.5")
async def test_a_mapped_custom_field_is_a_column_in_the_detail_rows(
    session: AsyncSession, books: Books
) -> None:
    session.add(
        CustomFieldMapping(
            company_id=books.company.company_id,
            collection_type="VOUCHER",
            tally_field="UDFSalesman",
            field_key="salesman",
            data_type="TEXT",
            is_active=True,
        )
    )
    voucher = await books.voucher(
        "Sales",
        date(2025, 6, 6),
        [("Customer A", "DEBIT", "500"), ("Sales", "CREDIT", "500")],
    )
    voucher.custom_fields = {"salesman": "R. Nair"}
    await session.flush()
    report = await reports.build(session, ctx(books), "sales", RANGE)
    headings = [c.heading for c in report.columns]
    assert "Salesman" in headings
    rows = table(await to_csv(report), headings)
    assert [r["Salesman"] for r in rows if r["Salesman"]] == ["R. Nair"]


async def test_a_balance_export_has_a_signed_column_and_a_side(
    session: AsyncSession, books: Books
) -> None:
    report = await reports.build(session, ctx(books), "receivables", RANGE)
    headings = [c.heading for c in report.columns]
    assert "Amount (Dr +)" in headings and "Dr/Cr" in headings
    sides = {r["Dr/Cr"] for r in table(await to_csv(report), headings)}
    assert sides <= {"Dr", "Cr", ""}


async def test_a_product_export_keeps_quantity_and_unit_and_never_sums_them(
    session: AsyncSession, books: Books
) -> None:
    report = await reports.build(session, ctx(books), "product-revenue", RANGE)
    headings = [c.heading for c in report.columns]
    assert "Quantity" in headings and "Unit" in headings
    rows = table(await to_csv(report), headings)
    assert {r["Unit"] for r in rows} == {"Nos", "Kgs"}


async def test_only_the_metrics_whose_page_draws_a_chart_carry_one(
    session: AsyncSession, books: Books
) -> None:
    # EXP-1.2 is "the charts shown on screen": no more, no fewer. Every charted metric has
    # activity in these books, so the set is exactly CHARTED.
    charted = {
        m.value
        for m in MetricName
        if (await reports.build(session, ctx(books), m.value, RANGE)).charts
    }
    assert charted == reports.CHARTED


async def test_an_unknown_report_is_refused(session: AsyncSession, books: Books) -> None:
    with pytest.raises(AppError) as raised:
        await reports.build(session, ctx(books), "not-a-report", RANGE)
    assert raised.value.http_status == 422


async def test_ids_are_not_columns_the_owner_has_to_read(
    session: AsyncSession, books: Books
) -> None:
    report = await reports.build(session, ctx(books), "expenses", RANGE)
    assert not any(c.key.endswith("_id") for c in report.columns)
    assert "Group name" in [c.heading for c in report.columns]


async def test_the_detail_table_streams_in_pages(session: AsyncSession, books: Books) -> None:
    for day in range(1, 12):
        await books.voucher(
            "Sales",
            date(2025, 10, day),
            [("Customer A", "DEBIT", "10"), ("Sales", "CREDIT", "10")],
        )
    reports.PAGE, original = 3, reports.PAGE
    try:
        report = await reports.build(session, ctx(books), "sales", RANGE)
        rows = table(await to_csv(report), [c.heading for c in report.columns])
    finally:
        reports.PAGE = original
    assert len(rows) == report.total_rows
    assert sum(Decimal(r["Amount"]) for r in rows) == report.summary[0].amount


async def test_nothing_in_the_period_still_produces_a_readable_file(
    session: AsyncSession, books: Books
) -> None:
    empty = ExportParams(date_from=date(2024, 4, 1), date_to=date(2024, 4, 30))
    report = await reports.build(session, ctx(books), "sales", empty)
    rows = parse(await to_csv(report))
    assert ["Rows", "0"] in rows
    assert report.total_rows == 0
