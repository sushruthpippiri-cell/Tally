"""P12.5: the stock API (SRS 11, D-050). "Today" and "days since last sale" use the company's
local date (TZ-1.1), tested at fixed instants around IST midnight, a month end and the FY end."""

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Any

import httpx
import pytest
import time_machine
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.balances import StockSnapshot
from app.models.company import User
from app.models.enums import RoleName, SettingDataType
from tests.analytics.books import Books, make_books
from tests.analytics.test_stock import item, sell
from tests.factories import auth_header, make_user

TODAY = date(2026, 3, 16)


@pytest.fixture
async def books(session: AsyncSession) -> Books:
    return await make_books(session)


@pytest.fixture
async def owner(session: AsyncSession, books: Books) -> User:
    return await make_user(session, books.company, RoleName.OWNER)


async def snap(books: Books, name: str, qty: str, day: date = TODAY, unit: str = "Nos") -> None:
    books.session.add(
        StockSnapshot(
            company_id=books.company.company_id,
            stock_item_id=(await item(books, name)).stock_item_id,
            as_of_date=day,
            closing_quantity=Decimal(qty),
            unit=unit,
        )
    )
    await books.session.flush()


async def get(api: httpx.AsyncClient, books: Books, owner: User, **params: Any) -> Any:
    r = await api.get(
        f"/companies/{books.company.company_id}/analytics/stock",
        params=params,
        headers=auth_header(owner),
    )
    assert r.status_code == 200, r.text
    return r.json()


def by_name(body: Any) -> dict[str, Any]:
    return {i["name"]: i for i in body["items"]}


@pytest.mark.req("FR-STK-14", "FR-STK-16", "FR-STK-17")
async def test_counts_classes_labels_and_filters(
    api: httpx.AsyncClient, books: Books, owner: User
) -> None:
    await snap(books, "Soap", "12")  # no sale since the books began
    await snap(books, "Rice", "0", unit="Kgs")  # not classified
    await sell(books, "Pen", 5, "100")  # fast, stock unknown
    body = await get(api, books, owner)
    counts = {c["key"]: c["count"] for c in body["classes"]}
    assert (counts["NEVER_SOLD"], counts["NOT_CLASSIFIED"], counts["FAST"]) == (1, 1, 1)
    labels = {c["key"]: c["label"] for c in body["classes"]}
    assert labels["NEVER_SOLD"] == "No sale since 2025-04-01"  # owner (D-050 #6)
    items = by_name(body)
    assert set(items) == {"Soap", "Pen"}  # FR-STK-19: not classified is not listed
    assert (items["Soap"]["label"], items["Soap"]["snapshot_date"]) == (
        "No sale since 2025-04-01",
        "2026-03-16",
    )
    assert (items["Pen"]["stock"], items["Pen"]["snapshot_date"]) == (None, None)  # unknown
    assert body["total_items"] == 2 and body["basis"] == "value"
    assert any("books-beginning" in n for n in body["notes"])
    never = await get(api, books, owner, **{"class": "NEVER_SOLD"})  # its own filter
    assert [i["name"] for i in never["items"]] == ["Soap"] and never["total_items"] == 1
    hidden = await get(api, books, owner, **{"class": "NOT_CLASSIFIED"})
    assert [i["name"] for i in hidden["items"]] == ["Rice"]
    assert body["unverified_gates"] == ["G18", "G27"]


@pytest.mark.req("FR-STK-10")
async def test_the_unit_limitation_is_stated_and_quantities_are_per_unit(
    api: httpx.AsyncClient, books: Books, owner: User
) -> None:
    await sell(books, "Soap", 3, "120", qty="12", unit="Nos")
    await sell(books, "Soap", 4, "1200", qty="10", unit="Box")
    body = await get(api, books, owner)
    soap = by_name(body)["Soap"]
    assert soap["multi_unit"] is True
    assert soap["period_quantities"] == [
        {"unit": "Box", "quantity": "10.000000"},
        {"unit": "Nos", "quantity": "12.000000"},
    ]
    assert body["limitations"] and "not converted" in body["limitations"][0]


@pytest.mark.parametrize(
    ("newest_days_ago", "stale_setting", "warned"),
    [(2, None, False), (3, None, True), (3, 5, False)],
)
async def test_a_stale_snapshot_is_warned_about_with_its_date(
    api: httpx.AsyncClient,
    books: Books,
    owner: User,
    newest_days_ago: int,
    stale_setting: int | None,
    warned: bool,
) -> None:
    """Owner (D-050 #10): older than `stock.snapshot_stale_days` (default 2) -> a warning."""
    if stale_setting:
        await books.setting("stock.snapshot_stale_days", stale_setting, SettingDataType.INTEGER)
    newest = TODAY - timedelta(days=newest_days_ago)
    await snap(books, "Soap", "5", newest)
    warnings = (await get(api, books, owner))["warnings"]
    assert bool(warnings) is warned
    if warned:
        assert str(newest) in warnings[0]


async def test_no_snapshot_at_all_is_warned_about(
    api: httpx.AsyncClient, books: Books, owner: User
) -> None:
    body = await get(api, books, owner)
    assert body["warnings"] == ["No closing-stock snapshot has been received from Tally yet."]


@pytest.mark.req("FR-STK-1")
async def test_the_period_can_be_chosen_per_request(
    api: httpx.AsyncClient, books: Books, owner: User
) -> None:
    await snap(books, "Soap", "5")
    await sell(books, "Soap", 45)
    assert by_name(await get(api, books, owner, period_days=30))["Soap"]["note"] == (
        "no sale in selected period"
    )
    assert by_name(await get(api, books, owner, period_days=60))["Soap"]["movement_class"] == "FAST"
    r = await api.get(
        f"/companies/{books.company.company_id}/analytics/stock",
        params={"period_days": 45},
        headers=auth_header(owner),
    )
    assert r.status_code == 422


# --- local date (owner point 4) --------------------------------------------------------------


@pytest.mark.req_partial("TZ-1.1")  # stock; aging and payment behaviour: P11; the rest: P0-P8
@pytest.mark.parametrize(
    ("instant", "days", "before", "after"),
    [
        ("2026-01-14T18:29:59Z", 90, "NORMAL", "SLOW"),  # IST midnight: 90 -> 91 days
        ("2026-01-14T18:29:59Z", 179, "SLOW", "DEAD"),  # 179 -> 180
        ("2026-02-28T18:29:59Z", 90, "NORMAL", "SLOW"),  # a month end
        ("2026-03-31T18:29:59Z", 179, "SLOW", "DEAD"),  # the financial-year end
    ],
)
async def test_days_since_last_sale_use_the_companys_local_date(
    api: httpx.AsyncClient,
    books: Books,
    owner: User,
    instant: str,
    days: int,
    before: str,
    after: str,
) -> None:
    """At 23:59:59 IST the last sale is `days` ago; one second later it is the next day in
    India (the UTC date has not changed), one day more, and the next class."""
    first = datetime.fromisoformat(instant).astimezone(UTC)
    local_day = date(first.year, first.month, first.day)  # 18:29:59Z is still that IST day
    await sell(books, "Soap", (TODAY - local_day).days + days)  # dated local_day - days
    await snap(books, "Soap", "5", local_day - timedelta(days=days - 1))
    seen = []
    for moment in (first, first + timedelta(seconds=1)):
        with time_machine.travel(moment, tick=False):
            soap = by_name(await get(api, books, owner))["Soap"]
        seen.append((soap["days_since_last_sale"], soap["movement_class"]))
    assert seen == [(days, before), (days + 1, after)]
