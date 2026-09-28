"""P9.4: rankings (TOPN-1.x, FR-2.4, D-046 #4): a Top-N list is the full list's own query
with a cut-off, Unattributed is never ranked, and quantities are ranked per unit."""

from datetime import date
from decimal import Decimal

import pytest

from app.analytics import query
from tests.analytics.books import Books

DAY = date(2025, 8, 14)
CUSTOMER = (("party_id",), "party_name")


async def _customers(books: Books, amounts: list[str]) -> None:
    for i, amount in enumerate(amounts):
        name = f"Client {i:02d}"
        await books.ledger(name, books.groups["Sundry Debtors"])
        await books.voucher("Sales", DAY, [(name, "DEBIT", amount), ("Sales", "CREDIT", amount)])
    await books.voucher("Sales", DAY, [("Cash", "DEBIT", "99999"), ("Sales", "CREDIT", "99999")])


@pytest.mark.req("TOPN-1.2")
async def test_top_n_is_the_first_n_rows_of_the_full_list(books: Books) -> None:
    # ties on purpose: 500 x3 and 20 x2
    await _customers(books, ["500", "20", "750", "500", "1", "500", "20", "3000"])
    s, ctx = books.session, await books.ctx()
    full = await query.ranking(s, ctx, "customer_revenue", *CUSTOMER)
    assert (full.is_top_n, full.total_count, len(full.rows)) == (False, 8, 8)
    assert [r["rank"] for r in full.rows] == list(range(1, 9))
    assert [r["value"] for r in full.rows] == sorted((r["value"] for r in full.rows), reverse=True)
    for n in range(1, 10):
        top = await query.ranking(s, ctx, "customer_revenue", *CUSTOMER, n=n)
        assert top.rows == full.rows[:n], n
        assert (top.is_top_n, top.total_count, top.n) == (True, 8, n)


@pytest.mark.req_partial("FR-2.4")  # through the API: tests/api/test_rankings.py
async def test_unattributed_is_never_ranked(books: Books) -> None:
    await _customers(books, ["10"])  # plus a 99,999 cash sale, the largest bucket
    ranked = await query.ranking(books.session, await books.ctx(), "customer_revenue", *CUSTOMER)
    assert [(r["party_name"], r["value"]) for r in ranked.rows] == [("Client 00", Decimal("10"))]


@pytest.mark.req_partial("FR-STK-10")  # the stock view's statement of the limitation: P12
async def test_quantities_are_ranked_per_unit_and_multi_unit_items_are_flagged(
    books: Books,
) -> None:
    sale = [("Customer A", "DEBIT", "100"), ("Sales", "CREDIT", "100")]
    await books.voucher(
        "Sales", DAY, sale, items=[("Soap", "40", "1", "40"), ("Rice", "25", "2", "50")]
    )
    await books.voucher("Sales", DAY, sale, items=[("Soap", "2", "5", "10", "Box")])  # 2 boxes
    ranked = await query.ranking(
        books.session,
        await books.ctx(),
        "product_revenue",
        ("stock_item_id", "unit"),
        "stock_item_name",
        measure="quantity",
    )
    assert [
        (r["stock_item_name"], r["value"], r["unit"], r["siblings"] > 1) for r in ranked.rows
    ] == [
        ("Soap", Decimal("40"), "Nos", True),  # never 42 "units": Nos and Box are not summed
        ("Rice", Decimal("25"), "Kgs", False),
        ("Soap", Decimal("2"), "Box", True),
    ]
    top = await query.ranking(
        books.session,
        await books.ctx(),
        "product_revenue",
        ("stock_item_id", "unit"),
        "stock_item_name",
        measure="quantity",
        n=1,
    )
    assert top.rows == ranked.rows[:1]  # the flag is computed over the whole list
