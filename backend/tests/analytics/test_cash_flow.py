"""P8.6: cash flow as the owner decided it (D-021): every movement on Cash/Bank-list ledgers,
netted per voucher, journals included by default, and equal to the change in the Cash/Bank
position over any period."""

from datetime import date, timedelta
from decimal import Decimal

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st
from sqlalchemy.ext.asyncio import AsyncSession

from app.analytics import query
from app.models.enums import SettingDataType
from tests.analytics.books import FY_START, Books, make_books

DAY = date(2025, 8, 14)


async def flows(books: Books, **kw: object) -> dict[str, Decimal | None]:
    ctx = await books.ctx(**kw)  # type: ignore[arg-type]
    rows = await query.breakdown(books.session, ctx, "cash_flow", "flow", "flow")
    return {flow: amount for flow, _, amount in rows}


async def by_voucher(books: Books) -> list[tuple[str, Decimal]]:
    rows, _ = await query.drilldown(books.session, await books.ctx(), "cash_flow")
    return sorted((r["voucher_type_name"], r["amount"]) for r in rows)


@pytest.mark.req("AC-37", "ACC-3.1")
@pytest.mark.req_partial("ACC-3.3")  # superseded as worded by D-021: see the Bank OD test
async def test_receipt_payment_and_an_own_transfer(books: Books) -> None:
    await books.voucher(
        "Receipt", DAY, [("Cash", "DEBIT", "5000"), ("Customer A", "CREDIT", "5000")]
    )
    await books.voucher(
        "Payment", DAY, [("Rent", "DEBIT", "3000"), ("HDFC Bank", "CREDIT", "3000")]
    )
    await books.voucher(
        "Contra", DAY, [("HDFC Bank", "DEBIT", "10000"), ("Cash", "CREDIT", "10000")]
    )
    assert await by_voucher(books) == [("Payment", Decimal("-3000")), ("Receipt", Decimal("5000"))]
    assert await flows(books) == {"INFLOW": Decimal("5000"), "OUTFLOW": Decimal("-3000")}
    assert await query.total(books.session, await books.ctx(), "cash_flow") == Decimal("2000")


@pytest.mark.req_partial("ACC-1.6", "ACC-1.7", "ACC-3.3")  # superseded as worded by D-021
async def test_every_voucher_type_that_moves_cash_counts(books: Books) -> None:
    await books.voucher("Sales", DAY, [("Cash", "DEBIT", "700"), ("Sales", "CREDIT", "700")])
    await books.voucher(
        "Purchase", DAY, [("Purchases", "DEBIT", "400"), ("HDFC Bank", "CREDIT", "400")]
    )
    await books.voucher(
        "Journal", DAY, [("HDFC Bank", "DEBIT", "9000"), ("Loan", "CREDIT", "9000")]
    )
    await books.voucher(  # money leaving the list for an unlisted overdraft account
        "Contra", DAY, [("ICICI OD", "DEBIT", "2500"), ("HDFC Bank", "CREDIT", "2500")]
    )
    await books.voucher(  # a partial transfer: only the net leaves the list
        "Contra",
        DAY,
        [("Cash", "DEBIT", "600"), ("ICICI OD", "DEBIT", "400"), ("HDFC Bank", "CREDIT", "1000")],
    )
    assert await by_voucher(books) == [
        ("Contra", Decimal("-2500")),
        ("Contra", Decimal("-400")),
        ("Journal", Decimal("9000")),
        ("Purchase", Decimal("-400")),
        ("Sales", Decimal("700")),
    ]
    assert await flows(books) == {"INFLOW": Decimal("9700"), "OUTFLOW": Decimal("-3300")}


@pytest.mark.req_partial("ACC-3.4")  # superseded as worded by D-021 #2: on by default
async def test_journals_count_by_default_and_can_be_switched_off(books: Books) -> None:
    await books.voucher(
        "Journal", DAY, [("HDFC Bank", "DEBIT", "9000"), ("Loan", "CREDIT", "9000")]
    )
    await books.voucher("Receipt", DAY, [("Cash", "DEBIT", "10"), ("Customer A", "CREDIT", "10")])
    assert await flows(books) == {"INFLOW": Decimal("9010")}
    await books.setting("cashflow.include_journal", False, SettingDataType.BOOLEAN)
    assert await flows(books) == {"INFLOW": Decimal("10")}


# --- the invariant (D-021 #5) -------------------------------------------------------------


async def net(books: Books, start: date, end: date) -> Decimal | None:
    return await query.total(books.session, await books.ctx(start, end), "cash_flow")


async def position(books: Books, day: date) -> Decimal | None:
    ctx = await books.ctx(min(FY_START, day), day)  # a balance ignores `from`
    return await query.total(books.session, ctx, "cash_bank_position")


async def assert_invariant(books: Books, start: date, end: date) -> None:
    before, after = await position(books, start - timedelta(days=1)), await position(books, end)
    assert before is not None and after is not None
    assert await net(books, start, end) == after - before, (start, end)


async def _mixed(books: Books) -> None:
    await books.opening("Cash", "DEBIT", "1000")
    await books.opening("HDFC Bank", "DEBIT", "50000")
    rows = [
        ("Sales", date(2025, 4, 1), [("Cash", "DEBIT", "700"), ("Sales", "CREDIT", "700")]),
        (
            "Receipt",
            date(2025, 6, 10),
            [("HDFC Bank", "DEBIT", "5000"), ("Customer A", "CREDIT", "5000")],
        ),
        (
            "Payment",
            date(2025, 6, 30),
            [("Rent", "DEBIT", "3000"), ("HDFC Bank", "CREDIT", "3000")],
        ),
        ("Contra", date(2025, 7, 1), [("Cash", "DEBIT", "2000"), ("HDFC Bank", "CREDIT", "2000")]),
        (
            "Contra",
            date(2025, 8, 5),
            [("ICICI OD", "DEBIT", "2500"), ("HDFC Bank", "CREDIT", "2500")],
        ),
        ("Purchase", date(2025, 9, 30), [("Purchases", "DEBIT", "400"), ("Cash", "CREDIT", "400")]),
        (
            "Journal",
            date(2026, 3, 31),
            [("HDFC Bank", "DEBIT", "9000"), ("Loan", "CREDIT", "9000")],
        ),
        ("Memorandum", date(2026, 4, 1), [("Cash", "DEBIT", "15"), ("Customer B", "CREDIT", "15")]),
        ("Credit Note", date(2026, 4, 2), [("Sales", "DEBIT", "50"), ("Cash", "CREDIT", "50")]),
        ("Payment", date(2026, 5, 20), [("Freight", "DEBIT", "80"), ("Cash", "CREDIT", "80")]),
    ]
    for vtype, day, entries in rows:
        await books.voucher(vtype, day, entries)
    await books.voucher(  # cancelled: counts in neither
        "Receipt",
        date(2025, 6, 15),
        [("Cash", "DEBIT", "123"), ("Customer A", "CREDIT", "123")],
        status="CANCELLED",
    )


@pytest.mark.parametrize(
    ("start", "end"),
    [
        (FY_START, date(2025, 4, 30)),  # from books-beginning
        (date(2025, 6, 1), date(2025, 6, 30)),  # a month
        (date(2025, 7, 1), date(2025, 9, 30)),  # a quarter, with the contra out of the list
        (date(2026, 2, 1), date(2026, 5, 31)),  # across the financial-year boundary
        (date(2025, 6, 30), date(2025, 6, 30)),  # a single day
        (date(2025, 11, 1), date(2025, 11, 30)),  # nothing moved
        (FY_START, date(2026, 12, 31)),  # everything
    ],
)
async def test_net_cash_flow_equals_the_change_in_the_cash_bank_position(
    books: Books, start: date, end: date
) -> None:
    await _mixed(books)
    await assert_invariant(books, start, end)


amounts = st.integers(min_value=1, max_value=99999).map(lambda n: Decimal(n) / 100)
LEDGERS = ["Cash", "HDFC Bank", "ICICI OD", "Customer A", "Sales", "Rent", "Loan"]
TYPES = [
    "Sales",
    "Purchase",
    "Receipt",
    "Payment",
    "Contra",
    "Journal",
    "Credit Note",
    "Memorandum",
]
voucher_st = st.tuples(
    st.sampled_from(TYPES),
    st.dates(min_value=FY_START, max_value=date(2026, 9, 30)),
    st.lists(
        st.tuples(st.sampled_from(LEDGERS), st.sampled_from(LEDGERS), amounts),
        min_size=1,
        max_size=3,
    ),
    st.sampled_from(["ACTIVE", "ACTIVE", "ACTIVE", "CANCELLED", "MISSING_IN_TALLY"]),
)


@settings(
    max_examples=25, deadline=None, suppress_health_check=[HealthCheck.function_scoped_fixture]
)
@given(
    vouchers=st.lists(voucher_st, min_size=1, max_size=8),
    period=st.tuples(
        st.dates(min_value=FY_START, max_value=date(2026, 9, 30)),
        st.integers(min_value=0, max_value=400),
    ),
)
async def test_the_invariant_holds_for_random_vouchers_and_periods(
    session: AsyncSession,
    vouchers: list[tuple[str, date, list[tuple[str, str, Decimal]], str]],
    period: tuple[date, int],
) -> None:
    books = await make_books(session)
    await books.opening("Cash", "DEBIT", "0")
    await books.opening("HDFC Bank", "CREDIT", "250")
    for vtype, day, pairs, status in vouchers:
        entries = [
            e for dr, cr, a in pairs for e in ((dr, "DEBIT", str(a)), (cr, "CREDIT", str(a)))
        ]
        await books.voucher(vtype, day, entries, status=status)
    start, days = period
    await assert_invariant(books, start, start + timedelta(days=days))
