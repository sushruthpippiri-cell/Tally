"""P8.8: the analytics API. Every view of a metric (summary, series, breakdown, drill-down)
comes from the same detail query, so they agree to the paisa (ACC-4.4, FR-DD-5)."""

from datetime import UTC, date, datetime
from decimal import Decimal
from decimal import Decimal as D
from typing import Any

import httpx
import pytest
import time_machine
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.company import User
from app.models.enums import RoleName
from app.services.analytics import MetricName
from tests.analytics.books import FY_START, Books, make_books
from tests.factories import auth_header, make_user

BALANCE_SHEET = [
    "Customer A",
    "Customer B",
    "Supplier S",
    "Output GST",
    "Input GST",
    "Cash",
    "HDFC Bank",
    "ICICI OD",
    "Loan",
]
RANGE = {"from": "2025-04-01", "to": "2026-03-31"}


@pytest.fixture
async def books(session: AsyncSession) -> Books:
    books = await make_books(session)
    for ledger in BALANCE_SHEET:
        await books.opening(ledger, "DEBIT", "0")
    return books


@pytest.fixture
async def viewer(session: AsyncSession, books: Books) -> User:
    return await make_user(session, books.company, RoleName.ACCOUNTANT)


def url(books: Books, metric: str, rest: str = "") -> str:
    return f"/companies/{books.company.company_id}/analytics/{metric}{rest}"


async def get(api: httpx.AsyncClient, user: User, path: str, **params: Any) -> dict[str, Any]:
    r = await api.get(path, params=params, headers=auth_header(user))
    assert r.status_code == 200, r.text
    body: dict[str, Any] = _money(r.json())
    return body


def _money(value: Any) -> Any:
    """Every "amount" (a JSON string, at the stored scale) as a Decimal, for comparing."""
    if isinstance(value, dict):
        return {
            k: Decimal(v) if k == "amount" and isinstance(v, str) else _money(v)
            for k, v in value.items()
        }
    return [_money(v) for v in value] if isinstance(value, list) else value


def signed(figure: dict[str, Any]) -> Decimal:
    amount = Decimal(figure["amount"])
    return -amount if figure["direction"] == "Cr" else amount


async def _activity(books: Books) -> None:
    v = books.voucher
    await v(
        "Sales",
        date(2025, 5, 2),
        [
            ("Customer A", "DEBIT", "11800"),
            ("Sales", "CREDIT", "10000"),
            ("Output GST", "CREDIT", "1800"),
        ],
    )
    await v("POS Invoice", date(2025, 8, 9), [("Cash", "DEBIT", "450"), ("Sales", "CREDIT", "450")])
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
    await v(
        "Receipt",
        date(2025, 9, 3),
        [("HDFC Bank", "DEBIT", "5000"), ("Customer A", "CREDIT", "5000")],
    )
    await v("Contra", date(2025, 9, 4), [("Cash", "DEBIT", "200"), ("HDFC Bank", "CREDIT", "200")])
    await v(
        "Credit Note",
        date(2026, 1, 10),
        [("Sales", "DEBIT", "300"), ("Customer A", "CREDIT", "300")],
    )


@pytest.mark.req_partial("ACC-4.4")  # exports on the same path: P14
@pytest.mark.req_partial("FR-DD-5")  # the drill-downs of later phases' metrics: P9-P12
@pytest.mark.parametrize("metric", [m.value for m in MetricName])
async def test_every_view_of_every_metric_agrees(
    api: httpx.AsyncClient, books: Books, viewer: User, metric: str
) -> None:
    await _activity(books)
    body = await get(api, viewer, url(books, metric), **RANGE)
    summary = body["summary"]
    assert summary["available"], body["notes"]
    balance = summary["direction"] is not None
    figure = signed(summary) if balance else Decimal(summary["amount"])
    assert (
        sum(
            (
                signed(b["figure"]) if balance else Decimal(b["figure"]["amount"])
                for b in body["breakdown"]
            ),
            Decimal(0),
        )
        == figure
    )
    if not balance:
        assert sum((Decimal(p["amount"]) for p in body["series"]), Decimal(0)) == figure
    rows: list[dict[str, Any]] = []
    page = 1
    while True:
        drill = await get(
            api, viewer, url(books, metric, "/drilldown"), page=page, page_size=2, **RANGE
        )
        rows += drill["rows"]
        if len(rows) >= drill["total_rows"]:
            break
        page += 1
    assert Decimal(drill["total"]) == figure
    assert sum((Decimal(r["amount"]) for r in rows), Decimal(0)) == figure


async def test_the_figures_are_the_ones_the_metrics_define(
    api: httpx.AsyncClient, books: Books, viewer: User
) -> None:
    await _activity(books)

    async def figure(metric: str, **params: Any) -> dict[str, Any]:
        return (await get(api, viewer, url(books, metric), **(RANGE | params)))["summary"]

    assert (await figure("sales"))["amount"] == D("10450")  # the note is unlinked (G26)
    assert (await figure("purchases"))["amount"] == D("4000")
    assert (await figure("expenses"))["amount"] == D("1000")
    assert (await figure("cash-flow"))["amount"] == D("4450")  # +450 +5000 -1000; contra 0
    for metric, amount, direction in [
        ("cash-bank-position", D("4450"), "Dr"),  # = the cash flow: the openings are zero
        ("receivables", D("6500"), "Dr"),
        ("payables", D("4000"), "Cr"),
    ]:
        assert await figure(metric) == {
            "amount": amount,
            "direction": direction,
            "available": True,
            "unavailable_count": 0,
            "unavailable_ledgers": [],
        }
    body = await get(api, viewer, url(books, "expenses"), group_by="cost_centre", **RANGE)
    assert {b["label"]: b["figure"]["amount"] for b in body["breakdown"]} == {
        "Retail": D("600"),
        "(No cost centre)": D("400"),
    }
    flows = await get(api, viewer, url(books, "cash-flow"), **RANGE)
    assert {b["label"]: b["figure"]["amount"] for b in flows["breakdown"]} == {
        "INFLOW": D("5450"),
        "OUTFLOW": D("-1000"),
    }
    assert any("D-021" in n for n in flows["notes"])
    sales = await get(api, viewer, url(books, "sales"), **RANGE)
    assert any("G26" in n for n in sales["notes"])
    raw = await api.get(url(books, "sales"), params=RANGE, headers=auth_header(viewer))
    assert isinstance(raw.json()["summary"]["amount"], str)  # money is never a JSON number


@pytest.mark.req("AC-62")
async def test_daily_grouping_and_today_follow_the_company_time_zone(
    api: httpx.AsyncClient, session: AsyncSession, books: Books, viewer: User
) -> None:
    """11:58 PM IST on 15 March (already the 16th for a server at UTC+14): "today" is the
    15th, and the voucher dated the 15th is grouped on the 15th (D-020: voucher dates are
    never shifted)."""
    await books.voucher(
        "Sales", date(2026, 3, 15), [("Cash", "DEBIT", "7"), ("Sales", "CREDIT", "7")]
    )
    await books.voucher(
        "Sales", date(2026, 3, 16), [("Cash", "DEBIT", "9"), ("Sales", "CREDIT", "9")]
    )
    await session.execute(text("SET LOCAL TimeZone = 'Pacific/Kiritimati'"))
    with time_machine.travel(datetime(2026, 3, 15, 18, 28, tzinfo=UTC), tick=False):
        body = await get(api, viewer, url(books, "sales"), granularity="day")
    assert (body["filters_applied"]["date_from"], body["filters_applied"]["date_to"]) == (
        str(FY_START),
        "2026-03-15",
    )
    assert [(p["period"], p["amount"]) for p in body["series"]] == [("2026-03-15", D("7"))]
    assert body["company_timezone"] == "Asia/Kolkata"
    # 00:30 IST on the 16th is still the 15th in UTC: "today" is the 16th.
    with time_machine.travel(datetime(2026, 3, 15, 19, 0, tzinfo=UTC), tick=False):
        body = await get(api, viewer, url(books, "sales"), granularity="day")
    assert body["filters_applied"]["date_to"] == "2026-03-16"
    assert [p["period"] for p in body["series"]] == ["2026-03-15", "2026-03-16"]


async def test_an_unavailable_balance_names_its_ledgers(
    api: httpx.AsyncClient, session: AsyncSession, viewer: User, books: Books
) -> None:
    """D-045 #3: one ledger without an opening makes the figure unavailable, and says which."""
    await books.ledger("Petty Cash", books.groups["Cash-in-Hand"])  # no opening row
    body = await get(api, viewer, url(books, "cash-bank-position"), **RANGE)
    assert body["summary"] == {
        "amount": None,
        "direction": None,
        "available": False,
        "unavailable_count": 1,
        "unavailable_ledgers": ["Petty Cash"],
    }
    assert body["breakdown"][0]["label"] == "Petty Cash"
    assert body["breakdown"][0]["figure"]["available"] is False
    assert any("Petty Cash" in n and "ledgers_without_opening_balance" in n for n in body["notes"])


async def test_bad_requests_are_refused(api: httpx.AsyncClient, books: Books, viewer: User) -> None:
    h = auth_header(viewer)
    assert (await api.get(url(books, "profit"), headers=h)).status_code == 422
    assert (
        await api.get(url(books, "sales"), params={"group_by": "customer"}, headers=h)
    ).status_code == 422
    r = await api.get(
        url(books, "sales"), params={"from": "2026-01-02", "to": "2026-01-01"}, headers=h
    )
    assert r.status_code == 422 and r.json()["code"] == "VALIDATION_ERROR"
    assert (
        await api.get(url(books, "sales"), params={"granularity": "week"}, headers=h)
    ).status_code == 422


async def test_another_companys_figures_are_never_reachable(
    api: httpx.AsyncClient, session: AsyncSession, books: Books, viewer: User
) -> None:
    other = await make_books(session, name="Other Co")
    await other.voucher(
        "Sales", date(2025, 5, 1), [("Cash", "DEBIT", "5"), ("Sales", "CREDIT", "5")]
    )
    outsider = await make_user(session, other.company, RoleName.OWNER)
    assert (await api.get(url(books, "sales"), headers=auth_header(outsider))).status_code == 403
    assert (await get(api, viewer, url(books, "sales"), **RANGE))["summary"]["amount"] == D("0")
    assert (await get(api, outsider, url(other, "sales"), **RANGE))["summary"]["amount"] == D("5")
