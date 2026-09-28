"""P9.1/P9.2: customer and supplier attribution (ACC-6.x, ACC-1.4, D-046 #1). The buckets
always total the metric (ACC-6.4), and a linked return comes off its original's bucket."""

from collections import defaultdict
from datetime import date, timedelta
from decimal import Decimal

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st
from sqlalchemy.ext.asyncio import AsyncSession

from app.analytics import query
from tests.analytics.books import FY_START, Books, make_books

DAY = date(2025, 8, 14)
Buckets = dict[str | None, Decimal]


async def buckets(books: Books, metric: str = "customer_revenue", **kw: date) -> Buckets:
    ctx = await books.ctx(kw.get("start", FY_START), kw.get("end", date(2026, 3, 31)))
    rows = await query.breakdown(books.session, ctx, metric, "party_id", "party_name")
    return {name: amount for _, name, amount in rows if amount}


async def total(books: Books, metric: str = "sales", **kw: date) -> Decimal | None:
    ctx = await books.ctx(kw.get("start", FY_START), kw.get("end", date(2026, 3, 31)))
    return await query.total(books.session, ctx, metric)


async def sale(books: Books, parties: list[tuple[str, str]], amount: str, **kw: object) -> None:
    """A sale debiting `parties` [(ledger, amount)] and crediting Sales `amount`."""
    entries = [(p, "DEBIT", a) for p, a in parties] + [("Sales", "CREDIT", amount)]
    await books.voucher("Sales", kw.pop("day", DAY), entries, **kw)  # type: ignore[arg-type]


@pytest.mark.req("AC-30", "ACC-6.1")
async def test_a_sale_to_one_customer_is_that_customers(books: Books) -> None:
    await sale(books, [("Customer A", "50000")], "50000")
    assert await buckets(books) == {"Customer A": Decimal("50000")}


@pytest.mark.req("AC-31", "ACC-6.2")
async def test_a_cash_sale_is_unattributed_and_the_buckets_total_sales(books: Books) -> None:
    await sale(books, [("Cash", "700")], "700")
    await sale(books, [("Customer A", "300")], "300")
    assert await buckets(books) == {None: Decimal("700"), "Customer A": Decimal("300")}
    assert sum((await buckets(books)).values()) == await total(books)


@pytest.mark.req("ACC-6.3")
async def test_two_customers_on_one_sale_are_never_split(books: Books) -> None:
    await sale(books, [("Customer A", "600"), ("Customer B", "400")], "1000")
    # the same customer on both sides of a voucher is still one customer
    await books.voucher(
        "Sales",
        DAY,
        [("Customer B", "DEBIT", "90"), ("Customer B", "DEBIT", "10"), ("Sales", "CREDIT", "100")],
    )
    assert await buckets(books) == {None: Decimal("1000"), "Customer B": Decimal("100")}


async def _mixed(books: Books) -> None:
    s = books.voucher
    await s(
        "Sales",
        date(2025, 5, 1),
        [("Customer A", "DEBIT", "5000"), ("Sales", "CREDIT", "5000")],
        bills=[(0, "NEW_REF", "INV-A", "5000")],
    )
    await s(
        "Sales",
        date(2025, 5, 2),
        [
            ("Customer A", "DEBIT", "600"),
            ("Customer B", "DEBIT", "400"),
            ("Sales", "CREDIT", "1000"),
        ],
        bills=[(0, "NEW_REF", "INV-AB", "600")],
    )
    await s("Sales", date(2025, 5, 3), [("Cash", "DEBIT", "700"), ("Sales", "CREDIT", "700")])
    await s(
        "Sales",
        date(2025, 6, 1),
        [("Customer B", "DEBIT", "2000"), ("Sales", "CREDIT", "2000")],
        bills=[(0, "NEW_REF", "INV-B", "2000")],
    )
    await s(
        "Sales",
        date(2025, 6, 2),
        [("Customer A", "DEBIT", "90"), ("Sales", "CREDIT", "90")],
        bills=[(0, "NEW_REF", "INV-X", "90")],
        status="CANCELLED",
    )
    notes = [
        (date(2025, 7, 1), "Customer A", "500", [("INV-A", "500")], "N-A"),  # -> Customer A
        (date(2025, 7, 2), "Customer A", "100", [("INV-AB", "100")], "N-AB"),  # -> Unattributed
        (
            date(2025, 7, 3),
            "Customer A",
            "300",
            [("INV-A", "150"), ("INV-AB", "150")],
            "N-MIX",
        ),  # mixed -> Unattributed
        (date(2025, 8, 1), "Customer B", "250", [("INV-B", "250")], "N-B"),  # -> Customer B
        (date(2025, 8, 2), "Customer A", "40", [("NO-SUCH", "40")], "N-NONE"),  # unlinked
        (date(2025, 8, 3), "Customer A", "9", [("INV-X", "9")], "N-CANCELLED"),  # origin cancelled
    ]
    for day, party, amount, refs, number in notes:
        await s(
            "Credit Note",
            day,
            [("Sales", "DEBIT", amount), (party, "CREDIT", amount)],
            bills=[(1, "AGST_REF", ref, a) for ref, a in refs],
            number=number,
        )


@pytest.mark.req("ACC-6.4")
@pytest.mark.parametrize(
    ("start", "end"),
    [
        (FY_START, date(2026, 3, 31)),  # the year
        (date(2025, 5, 1), date(2025, 5, 31)),  # sales only
        (date(2025, 7, 1), date(2025, 8, 31)),  # returns only: negative buckets
        (date(2025, 5, 2), date(2025, 7, 2)),  # a mix
    ],
)
async def test_customers_plus_unattributed_equal_total_sales_with_returns(
    books: Books, g26_passed: None, start: date, end: date
) -> None:
    await _mixed(books)
    found = await buckets(books, start=start, end=end)
    assert sum(found.values(), Decimal(0)) == await total(books, start=start, end=end)


async def test_a_return_comes_off_the_bucket_its_sale_was_counted_in(
    books: Books, g26_passed: None
) -> None:
    await _mixed(books)
    rows, _ = await query.drilldown(
        books.session, await books.ctx(date(2025, 7, 1), date(2025, 8, 31)), "customer_revenue"
    )
    assert {(r["voucher_number"], r["party_name"], r["amount"]) for r in rows} == {
        ("N-A", "Customer A", Decimal("-500")),  # its sale was Customer A's
        ("N-AB", None, Decimal("-100")),  # its sale had two customers: Unattributed
        ("N-MIX", None, Decimal("-300")),  # originals in different buckets: never split
        ("N-B", "Customer B", Decimal("-250")),
    }  # N-NONE and N-CANCELLED are unlinked: not subtracted at all
    assert await buckets(books) == {
        "Customer A": Decimal("4500"),
        None: Decimal("1300"),  # 1,000 + 700 - 100 - 300
        "Customer B": Decimal("1750"),
    }


# --- property: the identity, and every bucket, against a model -----------------------------

PARTIES = ["Customer A", "Customer B", "Customer C"]
cents = st.integers(min_value=1, max_value=99_999).map(lambda n: Decimal(n) / 100)
sale_st = st.tuples(
    st.lists(st.sampled_from(PARTIES), max_size=2, unique=True),  # 0, 1 or 2 customers
    cents,
    st.integers(min_value=0, max_value=300),  # day offset
    st.sampled_from(["ACTIVE", "ACTIVE", "ACTIVE", "CANCELLED", "MISSING_IN_TALLY"]),
)
note_st = st.tuples(
    st.integers(min_value=0, max_value=9),  # which sale's bill (or a bogus one if none)
    cents,
    st.integers(min_value=0, max_value=300),
    st.sampled_from(["ACTIVE", "ACTIVE", "CANCELLED"]),
)


@pytest.mark.req("ACC-6.4")
@settings(
    max_examples=30, deadline=None, suppress_health_check=[HealthCheck.function_scoped_fixture]
)
@given(
    sales=st.lists(sale_st, min_size=1, max_size=6),
    notes=st.lists(note_st, max_size=4),
    period=st.tuples(
        st.integers(min_value=0, max_value=300), st.integers(min_value=0, max_value=300)
    ),
)
async def test_attribution_matches_a_model_for_random_sales_and_returns(
    session: AsyncSession,
    g26_passed: None,
    sales: list[tuple[list[str], Decimal, int, str]],
    notes: list[tuple[int, Decimal, int, str]],
    period: tuple[int, int],
) -> None:
    books = await make_books(session)
    await books.ledger("Customer C", books.groups["Sundry Debtors"])
    start = FY_START + timedelta(days=min(period))
    end = FY_START + timedelta(days=max(period))
    expected: dict[str | None, Decimal] = defaultdict(Decimal)
    origins: list[tuple[str, str, str | None, str]] = []  # (party, ref, bucket, status)
    for i, (parties, amount, offset, status) in enumerate(sales):
        day = FY_START + timedelta(days=offset)
        debits = parties or ["Cash"]
        share = amount / len(debits)
        entries = [(p, "DEBIT", str(share)) for p in debits]
        entries[-1] = (debits[-1], "DEBIT", str(amount - share * (len(debits) - 1)))
        ref = f"R{i}"
        bills = [(0, "NEW_REF", ref, str(amount))] if parties else None
        await books.voucher(
            "Sales", day, [*entries, ("Sales", "CREDIT", str(amount))], bills=bills, status=status
        )
        bucket = parties[0] if len(parties) == 1 else None
        if parties:
            origins.append((parties[0], ref, bucket, status))
        if status == "ACTIVE" and start <= day <= end:
            expected[bucket] += amount
    for which, amount, offset, status in notes:
        day = FY_START + timedelta(days=offset)
        party, ref, bucket, origin_status = (
            origins[which % len(origins)] if origins else ("Customer A", "BOGUS", None, "ACTIVE")
        )
        await books.voucher(
            "Credit Note",
            day,
            [("Sales", "DEBIT", str(amount)), (party, "CREDIT", str(amount))],
            bills=[(1, "AGST_REF", ref, str(amount))],
            status=status,
        )
        linked = ref != "BOGUS" and origin_status == "ACTIVE"
        if linked and status == "ACTIVE" and start <= day <= end:
            expected[bucket] -= amount
    found = await buckets(books, start=start, end=end)
    assert found == {k: v for k, v in expected.items() if v}
    assert sum(found.values(), Decimal(0)) == (await total(books, start=start, end=end))
