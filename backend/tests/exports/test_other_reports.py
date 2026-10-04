"""The ranking, aging, payment-behaviour and stock adapters: every analytics section exports,
and each one from the service the screen calls (EXP-1.3)."""

import uuid
from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.permissions import CompanyContext
from app.exports import reports
from app.exports.reports import ExportParams
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
        [("Customer A", "DEBIT", "6000"), ("Sales", "CREDIT", "6000")],
        items=[("Soap", "100", "60", "6000")],
        bills=[(0, "NEW_REF", "INV-1", "6000", date(2025, 6, 1))],
    )
    await v(
        "Sales",
        date(2025, 8, 9),
        [("Customer B", "DEBIT", "450"), ("Sales", "CREDIT", "450")],
        items=[("Rice", "9", "50", "450")],
        bills=[(0, "NEW_REF", "INV-2", "450", date(2025, 9, 9))],
    )
    await v(
        "Purchase",
        date(2025, 6, 1),
        [("Purchases", "DEBIT", "4000"), ("Supplier S", "CREDIT", "4000")],
    )
    return books


def ctx(books: Books) -> CompanyContext:
    return CompanyContext(books.company.company_id, uuid.uuid4(), frozenset())


@pytest.mark.req("EXP-1.3")
@pytest.mark.parametrize("report", reports.REPORTS)
async def test_every_analytics_section_exports(
    session: AsyncSession, books: Books, report: str
) -> None:
    built = await reports.build(session, ctx(books), report, RANGE)
    text = await to_csv(built)
    rows = parse(text)
    assert rows[0][0] == "Report" and rows[0][1]
    assert rows[1] == ["Company", "Sharma Trading Co."]
    assert any(label == "Generated" for label, _ in built.meta)
    assert [c.heading for c in built.columns] in rows


@pytest.mark.req("TOPN-1.3")
@pytest.mark.parametrize("kind", ["customers", "suppliers", "products"])
async def test_a_ranking_export_says_top_n_or_all_and_never_totals_its_rows(
    session: AsyncSession, books: Books, kind: str
) -> None:
    top = await reports.build(session, ctx(books), kind, ExportParams(top_n=1))
    assert top.title.startswith("Top 1 ")
    assert dict(top.meta)["Listed"] == "Top 1"
    # TOPN-1.4: the only total is the reference total; no line adds up the listed rows.
    assert top.summary[0].label.lower() != "total"
    assert all("listed" not in line.label.lower() for line in top.summary)
    assert any("not" in n.lower() for n in top.notes)
    every = await reports.build(session, ctx(books), kind, ExportParams(view_all=True))
    assert every.title.startswith("All ")
    assert len([r async for r in every.rows]) >= len([r async for r in top.rows])


async def test_a_ranking_by_quantity_keeps_the_unit_and_flags_mixed_units(
    session: AsyncSession, books: Books
) -> None:
    built = await reports.build(
        session, ctx(books), "products", ExportParams(rank_by="quantity", view_all=True)
    )
    headings = [c.heading for c in built.columns]
    assert "Quantity" in headings and "Unit" in headings and "Amount" not in headings
    assert {r["Unit"] for r in table(await to_csv(built), headings)} == {"Nos", "Kgs"}


@pytest.mark.req("EXP-1.1")
@pytest.mark.parametrize("side", ["receivable", "payable"])
async def test_an_aging_export_is_as_of_a_date_with_a_column_per_bucket(
    session: AsyncSession, books: Books, side: str
) -> None:
    built = await reports.build(
        session, ctx(books), f"aging-{side}", ExportParams(date_to=date(2025, 10, 1))
    )
    assert dict(built.meta)["As of"] == "2025-10-01"
    headings = [c.heading for c in built.columns]
    assert "Party" in headings and any(h.startswith("Overdue") for h in headings)
    assert [line.label for line in built.summary][:2] == [
        "Total outstanding",
        "Credit (over-settled)",
    ]


async def test_an_aging_export_adds_up_to_its_own_total(
    session: AsyncSession, books: Books
) -> None:
    built = await reports.build(
        session, ctx(books), "aging-receivable", ExportParams(date_to=date(2025, 10, 1))
    )
    headings = [c.heading for c in built.columns]
    total = dict((line.label, line.amount) for line in built.summary)["Total outstanding"]
    rows = table(await to_csv(built), headings)
    assert sum(Decimal(r["Total outstanding"]) for r in rows) == total


async def test_payment_behaviour_exports_its_reason_when_the_gate_has_not_passed(
    session: AsyncSession, books: Books
) -> None:
    # FR-PAY-6: nothing is computed until G25 passes, and the file says why.
    built = await reports.build(session, ctx(books), "payment-behaviour", RANGE)
    assert built.notes
    text = await to_csv(built)
    assert ["Note", built.notes[0]] in parse(text)
    assert "0.00" not in [line.label for line in built.summary]


async def test_a_stock_export_counts_its_classes_as_numbers_not_money(
    session: AsyncSession, books: Books
) -> None:
    built = await reports.build(session, ctx(books), "stock", ExportParams(period_days=90))
    counts = [line for line in built.summary if line.kind == "integer"]
    assert counts and all(line.amount == line.amount.to_integral() for line in counts)
    text = await to_csv(built)
    # A count is written plainly; csv_amount's two decimal places would read as money.
    assert any(r[:2] == [counts[0].label, str(int(counts[0].amount or 0))] for r in parse(text))


async def test_a_stock_export_keeps_quantities_per_unit_side_by_side(
    session: AsyncSession, books: Books
) -> None:
    # Inside the measurement window, which ends at today in the company's time zone.
    await books.voucher(
        "Sales",
        date(2026, 2, 1),
        [("Customer A", "DEBIT", "6000"), ("Sales", "CREDIT", "6000")],
        items=[("Soap", "100", "60", "6000")],
    )
    await books.voucher(
        "Sales",
        date(2026, 2, 2),
        [("Customer B", "DEBIT", "450"), ("Sales", "CREDIT", "450")],
        items=[("Rice", "9", "50", "450")],
    )
    built = await reports.build(session, ctx(books), "stock", ExportParams(period_days=90))
    headings = [c.heading for c in built.columns]
    sold = {r["Item"]: r["Quantity sold in period"] for r in table(await to_csv(built), headings)}
    assert sold["Soap"] == "100 Nos"
    assert sold["Rice"] == "9 Kgs"
    assert sold["Pen"] == ""  # never sold


async def test_a_stock_export_names_its_period_and_snapshot_dates(
    session: AsyncSession, books: Books
) -> None:
    built = await reports.build(session, ctx(books), "stock", ExportParams(period_days=30))
    meta = dict(built.meta)
    assert " to " in meta["Measurement period"]
    assert meta["Snapshot dates"] == "no snapshot"
    assert any("snapshot" in n.lower() or "unit" in n.lower() for n in built.notes)


async def test_the_stock_table_streams_in_pages(session: AsyncSession, books: Books) -> None:
    reports.PAGE, original = 2, reports.PAGE
    try:
        built = await reports.build(session, ctx(books), "stock", ExportParams(period_days=90))
        rows = table(await to_csv(built), [c.heading for c in built.columns])
    finally:
        reports.PAGE = original
    assert len(rows) == built.total_rows == 3  # Soap, Rice, Pen
