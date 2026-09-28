"""P9.5: the ranking endpoints (TOPN-1.x, FR-2.4, ACC-VAL-1, D-046 #4-5)."""

from collections.abc import Callable
from datetime import date
from decimal import Decimal
from typing import Any

import httpx
import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.analytics.query import NON_PRODUCT_REVENUE, PRODUCT_ATTRIBUTION_DIFFERENCE
from app.models.company import User
from app.models.enums import RoleName, SettingDataType
from tests.analytics.books import Books, make_books
from tests.factories import auth_header, make_user

DAY = date(2025, 8, 14)
RANGE = {"from": "2025-04-01", "to": "2026-03-31"}


@pytest.fixture
async def books(session: AsyncSession) -> Books:
    return await make_books(session)


@pytest.fixture
async def viewer(session: AsyncSession, books: Books) -> User:
    return await make_user(session, books.company, RoleName.ACCOUNTANT)


async def get(
    api: httpx.AsyncClient, user: User, books: Books, kind: str, **params: Any
) -> dict[str, Any]:
    r = await api.get(
        f"/companies/{books.company.company_id}/analytics/{kind}",
        params=RANGE | params,
        headers=auth_header(user),
    )
    assert r.status_code == 200, r.text
    body: dict[str, Any] = r.json()
    return body


async def _customers(books: Books, count: int) -> None:
    for i in range(count):
        name = f"Client {i:02d}"
        await books.ledger(name, books.groups["Sundry Debtors"])
        amount = str(1000 + 10 * i)
        await books.voucher("Sales", DAY, [(name, "DEBIT", amount), ("Sales", "CREDIT", amount)])
    await books.voucher("Sales", DAY, [("Cash", "DEBIT", "777"), ("Sales", "CREDIT", "777")])


@pytest.mark.req("AC-33", "TOPN-1.1", "TOPN-1.4")
@pytest.mark.req_partial("TOPN-1.3")  # the "View All" control itself: the UI, P14
async def test_top_10_of_25_customers_and_view_all(
    api: httpx.AsyncClient, books: Books, viewer: User
) -> None:
    await _customers(books, 25)
    top = await get(api, viewer, books, "customers")
    assert (top["label"], top["is_top_n"], top["n"], top["total_count"]) == ("Top 10", True, 10, 25)
    assert [r["rank"] for r in top["rows"]] == list(range(1, 11))
    assert top["rows"][0]["name"] == "Client 24"  # the largest
    # no figure for the Top 10 together, and nothing says they add up to total sales
    assert set(top) == {
        "ranking", "rank_by", "label", "is_top_n", "n", "total_count", "filters_applied",
        "company_timezone", "rows", "unattributed", "product_attributed", "difference",
        "reference_total", "notes",
    }  # fmt: skip
    assert "not meant to add up" in top["notes"][0]
    assert top["unattributed"] == {"label": "Unattributed Customer Revenue", "amount": "777.0000"}
    assert Decimal(top["reference_total"]["amount"]) == sum(
        (Decimal(1000 + 10 * i) for i in range(25)), Decimal(777)
    )
    everything = await get(api, viewer, books, "customers", view_all=True)
    assert (everything["label"], everything["is_top_n"], len(everything["rows"])) == (
        "All",
        False,
        25,
    )
    assert top["rows"] == everything["rows"][:10]  # TOPN-1.2 through the API
    await books.setting("analytics.top_n_default", 5, SettingDataType.INTEGER)  # per company
    assert len((await get(api, viewer, books, "customers"))["rows"]) == 5
    assert len((await get(api, viewer, books, "customers", top_n=3))["rows"]) == 3


@pytest.mark.req("FR-2.4")
async def test_customers_and_products_by_revenue_and_quantity(
    api: httpx.AsyncClient, books: Books, viewer: User
) -> None:
    sale = [("Customer A", "DEBIT", "100"), ("Sales", "CREDIT", "100")]
    await books.voucher(
        "Sales", DAY, sale, items=[("Soap", "40", "1", "40"), ("Rice", "25", "2", "50")]
    )
    await books.voucher("Sales", DAY, sale, items=[("Soap", "2", "5", "10", "Box")])
    await books.voucher(
        "Purchase", DAY, [("Purchases", "DEBIT", "60"), ("Supplier S", "CREDIT", "60")]
    )
    customers = await get(api, viewer, books, "customers")
    assert [(r["name"], r["amount"]) for r in customers["rows"]] == [("Customer A", "200.0000")]
    suppliers = await get(api, viewer, books, "suppliers")
    assert suppliers["reference_total"]["label"] == "Purchase Value"
    assert [(r["name"], r["amount"]) for r in suppliers["rows"]] == [("Supplier S", "60.0000")]
    revenue = await get(api, viewer, books, "products")
    assert [(r["name"], r["amount"]) for r in revenue["rows"]] == [
        ("Rice", "50.0000"),
        ("Soap", "50.0000"),
    ]
    by_quantity = await get(api, viewer, books, "products", rank_by="quantity", view_all=True)
    assert [
        (r["name"], Decimal(r["quantity"]), r["unit"], r["multiple_units"])
        for r in by_quantity["rows"]
    ] == [
        ("Soap", Decimal(40), "Nos", True),
        ("Rice", Decimal(25), "Kgs", False),
        ("Soap", Decimal(2), "Box", True),
    ]
    assert any("own unit" in n for n in by_quantity["notes"])
    top = await get(api, viewer, books, "products", rank_by="quantity", top_n=2)
    assert top["rows"] == by_quantity["rows"][:2]
    h = auth_header(viewer)
    path = f"/companies/{books.company.company_id}/analytics/customers"
    assert (await api.get(path, params={"rank_by": "quantity"}, headers=h)).status_code == 422


@pytest.mark.req("ACC-VAL-1")
@pytest.mark.parametrize(
    ("g28", "taxable_mode", "label"),
    [
        ("NOT_TESTED", True, PRODUCT_ATTRIBUTION_DIFFERENCE),
        ("FAILED", True, PRODUCT_ATTRIBUTION_DIFFERENCE),
        ("PASSED", True, NON_PRODUCT_REVENUE),
        ("PASSED", False, PRODUCT_ATTRIBUTION_DIFFERENCE),  # tax in Total Sales (D-046 #5)
    ],
)
async def test_exactly_one_difference_label(
    api: httpx.AsyncClient,
    books: Books,
    viewer: User,
    set_gates: Callable[..., None],
    g28: str,
    taxable_mode: bool,
    label: str,
) -> None:
    set_gates(G28=g28)
    await books.setting("analytics.taxable_value_mode", taxable_mode, SettingDataType.BOOLEAN)
    await books.voucher(
        "Sales",
        DAY,
        [
            ("Customer A", "DEBIT", "118"),
            ("Sales", "CREDIT", "100"),
            ("Output GST", "CREDIT", "18"),
        ],
        items=[("Soap", "10", "9", "90")],
    )
    r = await api.get(
        f"/companies/{books.company.company_id}/analytics/products",
        params=RANGE,
        headers=auth_header(viewer),
    )
    other = (
        NON_PRODUCT_REVENUE
        if label == PRODUCT_ATTRIBUTION_DIFFERENCE
        else PRODUCT_ATTRIBUTION_DIFFERENCE
    )
    assert r.json()["difference"]["label"] == label
    assert r.text.count(label) == 1 and other not in r.text  # never both, anywhere
    expected = Decimal("10") if taxable_mode else Decimal("28")  # 100 - 90, or 118 - 90
    assert Decimal(r.json()["difference"]["amount"]) == expected
