"""P14.1: drill-down paths (FR-DD-1-5), the FR-4.3 filters and `by` narrowing (D-053 #1-4).
Each level's figure is the one the level above showed, and every list totals to it."""

from datetime import date
from decimal import Decimal
from typing import Any

import httpx
import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.analytics import query
from app.models.company import User
from app.models.enums import RoleName, SettingDataType
from app.services.analytics import MetricName
from tests.analytics.books import Books, make_books
from tests.api.test_analytics import BALANCE_SHEET, RANGE, get, url
from tests.factories import DEFAULT_ENTRIES as SALE
from tests.factories import auth_header, make_user


@pytest.fixture
async def books(session: AsyncSession) -> Books:
    books = await make_books(session)
    for ledger in BALANCE_SHEET:
        await books.opening(ledger, "DEBIT", "0")
    return books


@pytest.fixture
async def viewer(session: AsyncSession, books: Books) -> User:
    return await make_user(session, books.company, RoleName.ACCOUNTANT)


async def _sales(books: Books) -> None:
    v = books.voucher
    sale = [("Customer A", "DEBIT", "1000"), ("Sales", "CREDIT", "1000")]
    # fully itemised: nets to zero in the product difference
    await v("Sales", date(2025, 5, 1), sale, items=[("Soap", "10", "100", "1000")], number="S1")
    # partly itemised: 400 of 1000 has no line
    await v("Sales", date(2025, 5, 2), sale, items=[("Rice", "6", "100", "600")], number="S2")
    await v(
        "Sales",
        date(2025, 6, 3),
        [("Customer B", "DEBIT", "250"), ("Sales", "CREDIT", "250")],
        items=[("Soap", "1", "100", "100"), ("Pen", "3", "50", "150")],
        number="S3",
    )
    # a cash sale: Unattributed Customer Revenue, no lines at all
    await v("POS Invoice", date(2025, 7, 4), [("Cash", "DEBIT", "90"), ("Sales", "CREDIT", "90")])


async def _all_rows(
    api: httpx.AsyncClient, user: User, path: str, **params: Any
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    rows: list[dict[str, Any]] = []
    page = 1
    while True:
        drill = await get(api, user, path, page=page, page_size=1, **params)
        rows += drill["rows"]
        if len(rows) >= drill["total_rows"]:
            return drill, rows
        page += 1


def _total(rows: list[dict[str, Any]]) -> Decimal:
    return sum((Decimal(r["amount"]) for r in rows), Decimal(0))


async def _expand(
    api: httpx.AsyncClient, user: User, books: Books, metric: str, group_by: str, **params: Any
) -> list[tuple[str, Decimal]]:
    """Every breakdown row of `group_by`, drilled: its rows total its figure (FR-DD-5)."""
    body = await get(api, user, url(books, metric), group_by=group_by, **RANGE, **params)
    by = params.pop("by", [])
    seen = []
    for b in body["breakdown"]:
        key = b["key"] or "none"
        figure = Decimal(b["figure"]["amount"])
        drill, rows = await _all_rows(
            api,
            user,
            url(books, metric, "/drilldown"),
            by=[*by, f"{group_by}:{key}"],
            **RANGE,
            **params,
        )
        assert Decimal(drill["total"]) == figure == _total(rows)
        seen.append((key, figure))
    assert sum((f for _, f in seen), Decimal(0)) == Decimal(body["summary"]["amount"])
    return seen


@pytest.mark.req("FR-DD-1")
async def test_revenue_to_customer_to_vouchers_to_voucher_detail(
    api: httpx.AsyncClient, books: Books, viewer: User
) -> None:
    await _sales(books)
    customers = await _expand(api, viewer, books, "customer-revenue", "customer")
    a, b = books.ledgers["Customer A"].ledger_id, books.ledgers["Customer B"].ledger_id
    assert sorted(customers) == sorted(
        [(str(a), Decimal(2000)), (str(b), Decimal(250)), ("none", Decimal(90))]
    )
    _, rows = await _all_rows(
        api, viewer, url(books, "customer-revenue", "/drilldown"), by=f"customer:{a}", **RANGE
    )
    assert sorted(r["voucher_number"] for r in rows) == ["S1", "S2"]
    for r in rows:
        detail = await get(
            api, viewer, f"/companies/{books.company.company_id}/vouchers/{r['voucher_id']}"
        )
        assert [(e["ledger_name"], e["direction"], e["amount"]) for e in detail["entries"]] == [
            ("Customer A", "Dr", Decimal(1000)),
            ("Sales", "Cr", Decimal(1000)),
        ]
        assert len(detail["items"]) == 1


@pytest.mark.req("FR-DD-2")
async def test_product_revenue_to_product_to_its_lines(
    api: httpx.AsyncClient, books: Books, viewer: User
) -> None:
    await _sales(books)
    products = dict(await _expand(api, viewer, books, "product-revenue", "product"))
    soap = str(next(i for i in await _items(books) if i[1] == "Soap")[0])
    assert products[soap] == Decimal(1100)
    _, rows = await _all_rows(
        api, viewer, url(books, "product-revenue", "/drilldown"), by=f"product:{soap}", **RANGE
    )
    assert [(r["voucher_number"], r["dimensions"]["quantity"]) for r in rows] == [
        ("S1", "10.000000"),
        ("S3", "1.000000"),
    ]


async def _items(books: Books) -> list[tuple[Any, str]]:
    from sqlalchemy import select

    from app.models.masters import StockItem

    rows = await books.session.execute(
        select(StockItem.stock_item_id, StockItem.name).where(
            StockItem.company_id == books.company.company_id
        )
    )
    return list(rows.tuples())


@pytest.mark.req("FR-DD-3")
async def test_expense_category_to_ledger_to_vouchers(
    api: httpx.AsyncClient, books: Books, viewer: User
) -> None:
    v = books.voucher
    await v("Payment", date(2025, 5, 1), [("Rent", "DEBIT", "700"), ("Cash", "CREDIT", "700")])
    await v(
        "Payment",
        date(2025, 5, 9),
        [("Freight", "DEBIT", "300"), ("Cash", "CREDIT", "300")],
        centres=[(0, "Retail", "100")],
    )
    await v("Payment", date(2025, 6, 1), [("Rent", "DEBIT", "50"), ("Cash", "CREDIT", "50")])
    groups = await _expand(api, viewer, books, "expenses", "group")
    assert sorted(f for _, f in groups) == [Decimal(300), Decimal(750)]
    for group, _figure in groups:
        ledgers = await _expand(api, viewer, books, "expenses", "ledger", by=[f"group:{group}"])
        assert len(ledgers) == 1
    # the cost-centre split of one entry: a Retail row and a "(No cost centre)" remainder
    centres = dict(await _expand(api, viewer, books, "expenses", "cost_centre"))
    assert centres["none"] == Decimal(950)


@pytest.mark.req("FR-DD-4")
@pytest.mark.parametrize("verified", [False, True])
async def test_product_difference_to_contributing_vouchers(
    api: httpx.AsyncClient,
    books: Books,
    viewer: User,
    verified: bool,
    set_gates: Any,
) -> None:
    set_gates(G28="PASSED" if verified else "NOT_TESTED")
    await _sales(books)
    body = await get(api, viewer, url(books, "product-difference"), **RANGE)
    sales = await get(api, viewer, url(books, "sales"), **RANGE)
    products = await get(api, viewer, url(books, "product-revenue"), **RANGE)
    assert Decimal(body["summary"]["amount"]) == Decimal(sales["summary"]["amount"]) - Decimal(
        products["summary"]["amount"]
    )
    assert body["label"] == (
        query.NON_PRODUCT_REVENUE if verified else query.PRODUCT_ATTRIBUTION_DIFFERENCE
    )
    other = query.PRODUCT_ATTRIBUTION_DIFFERENCE if verified else query.NON_PRODUCT_REVENUE
    assert other not in str(body)
    vouchers = await _expand(api, viewer, books, "product-difference", "voucher")
    numbered = {
        (await get(api, viewer, f"/companies/{books.company.company_id}/vouchers/{k}"))[
            "voucher_number"
        ]: f
        for k, f in vouchers
    }
    # S1 is fully itemised (nets to zero): not a contributing voucher
    assert numbered == {"S2": Decimal(400), None: Decimal(90)}


@pytest.mark.req("FR-4.3")
async def test_filters_narrow_the_figures_they_apply_to_and_say_so_otherwise(
    api: httpx.AsyncClient, books: Books, viewer: User
) -> None:
    await _sales(books)
    await books.voucher(
        "Payment",
        date(2025, 5, 9),
        [("Freight", "DEBIT", "300"), ("Cash", "CREDIT", "300")],
        centres=[(0, "Retail", "100")],
    )
    a = str(books.ledgers["Customer A"].ledger_id)
    soap = str(next(i for i in await _items(books) if i[1] == "Soap")[0])
    retail = await _centre(books, "Retail")
    cases = [
        ("customer-revenue", {"customer": a}, Decimal(2000)),
        ("receivables", {"customer": a}, Decimal(2000)),
        ("product-revenue", {"product": soap}, Decimal(1100)),
        ("expenses", {"cost_centre": retail}, Decimal(100)),
    ]
    for metric, params, expected in cases:
        body = await get(api, viewer, url(books, metric), **RANGE, **params)
        assert Decimal(body["summary"]["amount"]) == expected, metric
        assert body["filters_applied"]["not_applicable"] == []
        drill, rows = await _all_rows(
            api, viewer, url(books, metric, "/drilldown"), **RANGE, **params
        )
        assert Decimal(drill["total"]) == expected == _total(rows)
    # Total Sales Revenue is never narrowed by customer: same figure, and the response says so
    plain = await get(api, viewer, url(books, "sales"), **RANGE)
    body = await get(api, viewer, url(books, "sales"), customer=a, product=soap, **RANGE)
    assert body["summary"] == plain["summary"]
    assert body["filters_applied"]["not_applicable"] == ["customer", "product"]
    assert body["filters_applied"]["customer"] == a


async def _centre(books: Books, name: str) -> str:
    from sqlalchemy import select

    from app.models.masters import CostCentre

    found = await books.session.scalar(
        select(CostCentre.cost_centre_id).where(
            CostCentre.company_id == books.company.company_id, CostCentre.name == name
        )
    )
    return str(found)


async def test_drill_pages_never_repeat_or_drop_tied_rows(
    api: httpx.AsyncClient, books: Books, viewer: User
) -> None:
    """D-053 #4: one voucher's lines tie on date, number and voucher; every page size still
    returns each line exactly once."""
    lines = [("Soap", "1", str(n), str(n)) for n in (5, 1, 4, 2, 3)]
    await books.voucher(
        "Sales",
        date(2025, 5, 1),
        [("Customer A", "DEBIT", "15"), ("Sales", "CREDIT", "15")],
        items=lines,
    )
    for size in (1, 2, 3):
        rows: list[dict[str, Any]] = []
        for page in (1, 2, 3, 4, 5):
            drill = await get(
                api,
                viewer,
                url(books, "product-revenue", "/drilldown"),
                page=page,
                page_size=size,
                **RANGE,
            )
            rows += drill["rows"]
        assert sorted(r["amount"] for r in rows) == [Decimal(n) for n in (1, 2, 3, 4, 5)]


async def test_drill_rows_carry_the_vouchers_custom_fields(
    api: httpx.AsyncClient, books: Books, viewer: User
) -> None:
    voucher = await books.voucher("Sales", date(2025, 5, 1), SALE, number="S1")
    voucher.custom_fields = {"salesman": "Ravi"}
    await books.session.flush()
    _, rows = await _all_rows(api, viewer, url(books, "sales", "/drilldown"), **RANGE)
    assert [r["custom_fields"] for r in rows] == [{"salesman": "Ravi"}]


@pytest.mark.parametrize(
    ("metric", "params"),
    [
        ("sales", {"by": "customer:x"}),  # not one of the metric's group_by options
        ("sales", {"by": "ledger"}),  # no key
        ("sales", {"by": "ledger:not-a-uuid"}),
        ("sales", {"customer": "not-a-uuid"}),
    ],
)
async def test_bad_narrowing_is_refused(
    api: httpx.AsyncClient, books: Books, viewer: User, metric: str, params: dict[str, str]
) -> None:
    for rest in ("", "/drilldown"):
        r = await api.get(
            url(books, metric, rest), params={**RANGE, **params}, headers=auth_header(viewer)
        )
        assert r.status_code == 422, r.text


@pytest.mark.req_partial("FR-DD-5")  # random filter combinations: the P14.9 property test
@pytest.mark.parametrize("metric", [m.value for m in MetricName])
async def test_every_metric_drills_by_its_ledger_or_first_dimension(
    api: httpx.AsyncClient, books: Books, viewer: User, metric: str
) -> None:
    from tests.api.test_analytics import _activity

    await _activity(books)
    await _sales(books)
    group_by = next(iter(query.METRICS[metric.replace("-", "_")].GROUP_BY))
    body = await get(api, viewer, url(books, metric), group_by=group_by, **RANGE)
    for b in body["breakdown"]:
        drill, rows = await _all_rows(
            api,
            viewer,
            url(books, metric, "/drilldown"),
            by=f"{group_by}:{b['key'] or 'none'}",
            **RANGE,
        )
        if b["figure"]["available"]:
            assert Decimal(drill["total"]) == _total(rows)
            signed = Decimal(b["figure"]["amount"])
            if b["figure"]["direction"] == "Cr":
                signed = -signed
            assert Decimal(drill["total"]) == signed


async def test_taxable_mode_off_moves_the_difference_label_back(
    api: httpx.AsyncClient, books: Books, viewer: User, set_gates: Any
) -> None:
    set_gates(G28="PASSED")
    await books.setting("analytics.taxable_value_mode", False, SettingDataType.BOOLEAN)
    body = await get(api, viewer, url(books, "product-difference"), **RANGE)
    assert body["label"] == query.PRODUCT_ATTRIBUTION_DIFFERENCE


async def test_another_companys_rows_never_appear(
    api: httpx.AsyncClient, session: AsyncSession, books: Books, viewer: User
) -> None:
    other = await make_books(session, name="Other Traders")
    await other.voucher("Sales", date(2025, 5, 1), SALE)
    a = str(other.ledgers["Customer A"].ledger_id)
    body = await get(api, viewer, url(books, "customer-revenue"), customer=a, **RANGE)
    assert Decimal(body["summary"]["amount"]) == 0
