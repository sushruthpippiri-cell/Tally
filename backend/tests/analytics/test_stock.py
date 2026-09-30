"""P12.1-P12.4: stock movement classification (SRS 11, D-050) through SQL, at a fixed date.
The local-date and API tests are in tests/api/test_stock_api.py."""

from datetime import date, timedelta
from decimal import Decimal
from typing import Any

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.analytics import stock
from app.analytics.stock import Thresholds
from app.core import gates
from app.models.balances import StockSnapshot
from app.models.masters import StockItem
from tests.analytics.books import Books, make_books
from tests.factories import make_stock_item

TODAY = date(2026, 3, 16)
DEFAULT = Thresholds(period_days=90, fast_percentile=75, slow_days=90, dead_days=180)
D = Decimal


async def item(books: Books, name: str, unit: str = "Nos") -> StockItem:
    found = await books.session.scalar(
        select(StockItem).where(
            StockItem.company_id == books.company.company_id, StockItem.name == name
        )
    )
    return found or await make_stock_item(books.session, books.company, name, unit)


async def sell(
    books: Books,
    name: str,
    days_ago: int,
    value: str = "100",
    qty: str = "1",
    unit: str | None = None,
    status: str = "ACTIVE",
) -> None:
    await item(books, name)
    line: Any = (name, qty, value, value, unit) if unit else (name, qty, value, value)
    await books.voucher(
        "Sales",
        TODAY - timedelta(days=days_ago),
        [("Customer A", "DEBIT", value), ("Sales", "CREDIT", value)],
        items=[line],
        status=status,
    )


async def snap(books: Books, name: str, qty: str, days_ago: int = 0, unit: str = "Nos") -> None:
    books.session.add(
        StockSnapshot(
            company_id=books.company.company_id,
            stock_item_id=(await item(books, name)).stock_item_id,
            as_of_date=TODAY - timedelta(days=days_ago),
            closing_quantity=D(qty),
            unit=unit,
        )
    )
    await books.session.flush()


async def classes(books: Books, t: Thresholds = DEFAULT, today: date = TODAY) -> dict[str, Any]:
    ctx = await books.ctx(today, today)
    rows = await books.session.execute(stock.classified(ctx, today, t))
    return {r.stock_item_name: r for r in rows}


# --- the truth table (D-050 #4), with the default thresholds N = 90, S = 90, K = 180 ----------

CASES = [
    # (stock, days since the only sale or None, expected class, note)
    ("5", None, stock.NEVER_SOLD, None),  # AC-52
    ("5", 10, stock.FAST, None),  # the only item sold: the threshold is its own value
    ("5", 89, stock.FAST, None),  # still in the 90-day period
    ("5", 90, stock.NORMAL, stock.GAP_NOTE),  # outside the period, not more than 90 days
    ("5", 91, stock.SLOW, None),
    ("5", 179, stock.SLOW, None),
    ("5", 180, stock.DEAD, None),
    ("40", 200, stock.DEAD, None),  # AC-53
    ("0", 100, stock.NOT_CLASSIFIED, None),
    ("-3", None, stock.NOT_CLASSIFIED, None),
    ("0", 10, stock.FAST, None),  # sold in the period: a sale wins over zero stock
    (None, None, stock.STOCK_UNKNOWN, None),  # no snapshot: never zero stock
    (None, 200, stock.STOCK_UNKNOWN, None),
    (None, 10, stock.FAST, None),  # sold: the class needs no stock
]


@pytest.mark.req("FR-STK-3", "FR-STK-4", "FR-STK-5", "FR-STK-12", "FR-STK-13", "FR-STK-19")
@pytest.mark.parametrize(("qty", "days", "expected", "note"), CASES)
async def test_the_truth_table(
    books: Books, qty: str | None, days: int | None, expected: str, note: str | None
) -> None:
    if qty is not None:
        await snap(books, "Soap", qty)
    if days is not None:
        await sell(books, "Soap", days)
    await item(books, "Soap")
    row = (await classes(books))["Soap"]
    assert (row.movement_class, row.note) == (expected, note)
    assert row.stock == (None if qty is None else D(qty))
    assert row.snapshot_date == (None if qty is None else TODAY)


@pytest.mark.req("AC-52")
async def test_stock_and_no_sale_ever_is_never_sold_not_slow_or_dead(books: Books) -> None:
    await snap(books, "Soap", "12")
    assert (await classes(books))["Soap"].movement_class == stock.NEVER_SOLD


@pytest.mark.req("AC-53", "FR-STK-16")
async def test_a_snapshot_of_40_and_no_sale_for_200_days_is_dead_with_its_date(
    books: Books,
) -> None:
    await snap(books, "Soap", "40", days_ago=1)
    await sell(books, "Soap", 200)
    row = (await classes(books))["Soap"]
    assert (row.movement_class, row.stock, row.snapshot_date, row.days_since_last_sale) == (
        stock.DEAD,
        D(40),
        TODAY - timedelta(days=1),
        200,
    )


@pytest.mark.req("FR-STK-1")
@pytest.mark.parametrize(
    ("period", "days", "expected"), [(30, 45, stock.NORMAL), (180, 120, stock.FAST)]
)
async def test_the_period_decides_the_gap_and_the_overlap(
    books: Books, period: int, days: int, expected: str
) -> None:
    """N = 30: a sale 45 days ago is outside the period but within 90 days (the gap: Normal,
    noted). N = 180: a sale 120 days ago is in the period, which beats Slow."""
    await snap(books, "Soap", "5")
    await sell(books, "Soap", days)
    t = Thresholds(period, 75, 90, 180)
    assert (await classes(books, t))["Soap"].movement_class == expected


@pytest.mark.req_partial("FR-STK-15")  # Tally-computed quantity: GATE-G18 live capture
async def test_the_latest_snapshot_on_or_before_today_is_the_stock(books: Books) -> None:
    await snap(books, "Soap", "7", days_ago=3)
    await snap(books, "Soap", "9", days_ago=1)
    await snap(books, "Soap", "99", days_ago=-2)  # dated after today: ignored
    row = (await classes(books))["Soap"]
    assert (row.stock, row.snapshot_date) == (D(9), TODAY - timedelta(days=1))


# --- the fast threshold (FR-STK-2, D-050 #3) -------------------------------------------------


async def _sales(books: Books, values: list[str], percentile: int = 75) -> dict[str, Any]:
    for n, value in enumerate(values):
        await sell(books, f"Item {n}", 5, value)
    return await classes(books, Thresholds(90, percentile, 90, 180))


@pytest.mark.req("FR-STK-2", "FR-STK-20")
@pytest.mark.parametrize(
    ("values", "percentile", "fast", "threshold"),
    [
        (["100"], 75, [0], "100"),  # one item sold: it is fast
        (["100", "300"], 75, [1], "250"),  # 100 + 0.75 x 200
        (["300", "300"], 75, [0, 1], "300"),  # equal: both
        (["1", "2", "3", "4"], 75, [3], "3.25"),  # position 2.25: 3 + 0.25 x 1
        (["1", "2", "3", "3", "3"], 75, [2, 3, 4], "3"),  # every tie at the threshold is fast
        (["1", "2", "3", "4"], 50, [2, 3], "2.5"),
        (["1", "2", "3", "4"], 99, [3], "3.97"),
    ],
)
async def test_the_percentile_threshold(
    books: Books, values: list[str], percentile: int, fast: list[int], threshold: str
) -> None:
    rows = await _sales(books, values, percentile)
    got = sorted(int(n.split()[1]) for n, r in rows.items() if r.movement_class == stock.FAST)
    assert got == fast
    assert {r.threshold for r in rows.values()} == {D(threshold)}


async def test_nothing_sold_means_no_threshold_and_no_fast(books: Books) -> None:
    await snap(books, "Soap", "5")
    rows = await classes(books)
    assert {r.threshold for r in rows.values()} == {None}
    assert stock.FAST not in {r.movement_class for r in rows.values()}


@settings(
    max_examples=30, deadline=None, suppress_health_check=[HealthCheck.function_scoped_fixture]
)
@given(
    values=st.lists(st.integers(min_value=1, max_value=10**6), min_size=1, max_size=9),
    p=st.integers(1, 99),
)
async def test_the_threshold_is_postgres_percentile_cont_in_numeric(
    session: AsyncSession, values: list[int], p: int
) -> None:
    """Same definition as percentile_cont (which works in floats); ours stays NUMERIC."""
    books = await make_books(session)
    rows = await _sales(books, [str(v) for v in values], p)
    [ours] = {r.threshold for r in rows.values()}
    theirs = await session.scalar(
        text(
            "SELECT percentile_cont(:f) WITHIN GROUP (ORDER BY v) "
            "FROM unnest(CAST(:values AS integer[])) AS v"
        ),
        {"f": p / 100, "values": values},
    )
    assert abs(float(ours) - float(theirs)) < 1e-6


# --- sales: cancelled, returns, units ------------------------------------------------------


@pytest.mark.req("FR-STK-6")
async def test_cancelled_sales_never_count_and_linked_returns_net_the_value(
    books: Books, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A cancelled sale is no sale. A linked return lowers the item's period value (so Rice,
    not Soap, is fast) and is never a "last sale" (G26 forced PASSED)."""
    passed = {g: "NOT_TESTED" for g in gates.load_gate_status()} | {"G26": "PASSED"}
    monkeypatch.setattr(gates, "_default_statuses", lambda: passed)
    await sell(books, "Pen", 5, "5000", status="CANCELLED")
    await books.voucher(
        "Sales",
        TODAY - timedelta(days=20),
        [("Customer A", "DEBIT", "1000"), ("Sales", "CREDIT", "1000")],
        items=[("Soap", "10", "100", "1000")],
        bills=[(0, "NEW_REF", "S-1", "1000")],
    )
    await books.voucher(
        "Credit Note",
        TODAY - timedelta(days=2),
        [("Sales", "DEBIT", "600"), ("Customer A", "CREDIT", "600")],
        items=[("Soap", "6", "100", "600")],
        bills=[(1, "AGST_REF", "S-1", "600")],
    )
    await sell(books, "Rice", 20, "800", unit="Kgs")
    rows = await classes(books)
    assert rows["Pen"].movement_class == stock.STOCK_UNKNOWN  # no snapshot, not sold
    assert (rows["Soap"].period_sales_value, rows["Soap"].movement_class) == (D(400), stock.NORMAL)
    assert rows["Rice"].movement_class == stock.FAST
    assert rows["Soap"].last_sale_date == TODAY - timedelta(days=20)  # not the return's date


@pytest.mark.req("AC-54")
@pytest.mark.req_partial("FR-STK-10")  # the limitation stated on the view: the API test
async def test_an_item_sold_in_two_units_is_flagged_and_its_quantities_kept_apart(
    books: Books,
) -> None:
    await sell(books, "Soap", 3, "120", qty="12", unit="Nos")
    await sell(books, "Soap", 4, "1200", qty="10", unit="Box")
    await sell(books, "Pen", 4, "50", qty="5")
    ctx = await books.ctx(TODAY, TODAY)
    multi = (await books.session.execute(stock.multi_unit_items(ctx, TODAY))).all()
    assert [(r.stock_item_name, sorted(r.units)) for r in multi] == [("Soap", ["Box", "Nos"])]
    quantities = (await books.session.execute(stock.quantities(ctx, TODAY, DEFAULT))).all()
    soap = (await item(books, "Soap")).stock_item_id
    assert sorted((r.unit, r.quantity) for r in quantities if r.stock_item_id == soap) == [
        ("Box", D(10)),
        ("Nos", D(12)),
    ]


# --- the partition, as a property (owner point 1) ------------------------------------------


def _model(
    qty: Decimal | None,
    sales: list[tuple[int, int, bool]],
    t: Thresholds,
    threshold: Decimal | None,
) -> tuple[str, str | None]:
    """D-050 #4 in plain Python: (class, note)."""
    active = [(d, v) for d, v, cancelled in sales if not cancelled]
    in_period = [v for d, v in active if d <= t.period_days - 1]
    last = min((d for d, _ in active), default=None)
    if in_period:
        assert threshold is not None
        return (stock.FAST if sum(in_period) >= threshold else stock.NORMAL), None
    if qty is None:
        return stock.STOCK_UNKNOWN, None
    if qty <= 0:
        return stock.NOT_CLASSIFIED, None
    if last is None:
        return stock.NEVER_SOLD, None
    if last >= t.dead_days:
        return stock.DEAD, None
    if last > t.slow_days:
        return stock.SLOW, None
    return stock.NORMAL, stock.GAP_NOTE


def _percentile(values: list[int], p: int) -> Decimal | None:
    if not values:
        return None
    ordered = sorted(values)
    pos = D(p) / 100 * (len(ordered) - 1)
    lo = int(pos)
    frac = pos - lo
    hi = ordered[min(lo + 1, len(ordered) - 1)]
    return ordered[lo] + frac * (hi - ordered[lo])


item_st = st.tuples(
    st.one_of(st.none(), st.sampled_from(["-2", "0", "0.5", "7", "40"])),
    st.lists(st.tuples(st.integers(0, 400), st.integers(1, 5000), st.booleans()), max_size=3),
)
thresholds_st = st.builds(
    lambda n, p, s, gap: Thresholds(n, p, s, s + gap),
    st.sampled_from([30, 60, 90, 180]),
    st.integers(1, 99),
    st.integers(1, 300),
    st.integers(1, 200),
)


@pytest.mark.req_partial("FR-STK-7")  # stored per company: tests/core (P2); used: the API tests
@settings(
    max_examples=40, deadline=None, suppress_health_check=[HealthCheck.function_scoped_fixture]
)
@given(items=st.lists(item_st, min_size=1, max_size=6), t=thresholds_st)
async def test_every_item_is_in_exactly_one_class_for_any_allowed_settings(
    session: AsyncSession,
    items: list[tuple[str | None, list[tuple[int, int, bool]]]],
    t: Thresholds,
) -> None:
    """Owner point 1: for random items and any thresholds the settings allow (N in 30/60/90/180,
    dead > slow, P 1-99), SQL gives every active item one row and exactly the class the table
    says."""
    books = await make_books(session)
    books.company.books_from = date(2024, 1, 1)  # every random sale is in the synced history
    for n, (qty, sales) in enumerate(items):
        name = f"Item {n}"
        await item(books, name)
        if qty is not None:
            await snap(books, name, qty)
        for days_ago, value, cancelled in sales:
            await sell(
                books, name, days_ago, str(value), status="CANCELLED" if cancelled else "ACTIVE"
            )
    rows = await classes(books, t)
    sold_values = [
        sum(v for d, v, c in sales if not c and d <= t.period_days - 1)
        for _, sales in items
        if any(not c and d <= t.period_days - 1 for d, _, c in sales)
    ]
    threshold = _percentile(sold_values, t.fast_percentile)
    for n, (qty, sales) in enumerate(items):
        row = rows[f"Item {n}"]
        expected = _model(None if qty is None else D(qty), sales, t, threshold)
        assert (row.movement_class, row.note) == expected, (n, qty, sales, t)
    assert set(r.movement_class for r in rows.values()) <= set(stock.CLASSES)


async def test_data_quality_lists_items_without_a_snapshot_and_multi_unit_items(
    books: Books,
) -> None:
    from app.core.permissions import CompanyContext
    from app.services import data_quality

    await snap(books, "Soap", "5")
    await sell(books, "Rice", 3, "10", qty="1", unit="Kgs")
    await sell(books, "Rice", 4, "10", qty="1", unit="Bag")
    ctx = CompanyContext(books.company.company_id, books.company.company_id, frozenset())

    async def names(check: str, key: str) -> list[str]:
        items = (await data_quality.items(books.session, ctx, check, 100, 0)).items
        return [i[key] for i in items]

    assert await names("stock_items_without_snapshot", "name") == ["Pen", "Rice"]
    assert await names("multi_unit_items", "stock_item_name") == ["Rice"]
