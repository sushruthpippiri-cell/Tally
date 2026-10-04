"""P11.6: the aging API (SRS 10, D-049). "Today" is the company's local date (TZ-1.1), tested
at fixed instants around IST midnight, a month end and the financial-year end."""

from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any

import httpx
import pytest
import time_machine
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.company import User
from app.models.enums import RoleName
from tests.analytics.books import Books, make_books
from tests.factories import auth_header, make_user

D = Decimal


@pytest.fixture
async def books(session: AsyncSession) -> Books:
    return await make_books(session)


@pytest.fixture
async def owner(session: AsyncSession, books: Books) -> User:
    return await make_user(session, books.company, RoleName.OWNER)


def _url(books: Books, tail: str = "") -> str:
    return f"/companies/{books.company.company_id}/analytics/aging{tail}"


async def _sale(
    books: Books, ref: str, amount: str, due: date | None, customer: str = "Customer A"
) -> None:
    await books.voucher(
        "Sales",
        date(2025, 11, 1),
        [(customer, "DEBIT", amount), ("Sales", "CREDIT", amount)],
        bills=[(0, "NEW_REF", ref, amount, due)],
    )


async def _get(api: httpx.AsyncClient, owner: User, url: str, **params: Any) -> Any:
    r = await api.get(url, params=params, headers=auth_header(owner))
    assert r.status_code == 200, r.text
    return r.json()


async def test_the_summary_is_the_sum_of_its_parties_and_the_drilldown_of_its_bills(
    api: httpx.AsyncClient, books: Books, owner: User
) -> None:
    """One query path (rule 9): total = Σ parties per bucket; a party's bills add up to its
    bucket total less its credit."""
    await books.opening("Customer A", "DEBIT", "0")
    await books.opening("Customer B", "DEBIT", "0")
    await _sale(books, "S-1", "20000", date(2026, 1, 30))  # 45 days before 2026-03-16
    await _sale(books, "S-2", "7000", date(2026, 3, 21))  # due in 5 days
    await _sale(books, "S-3", "1000", date(2026, 2, 1), customer="Customer B")
    await books.voucher(
        "Receipt",
        date(2026, 2, 5),
        [("Cash", "DEBIT", "1500"), ("Customer B", "CREDIT", "1500")],
        bills=[(1, "AGST_REF", "S-3", "1500")],
    )
    body = await _get(api, owner, _url(books), side="receivable")
    assert body["as_of"] == "2026-03-16" and body["company_timezone"] == "Asia/Kolkata"
    assert [b["key"] for b in body["bucket_order"]] == [
        "NOT_YET_DUE",
        "0-30",
        "31-60",
        "61-90",
        "90+",
        "NO_DUE_DATE",
    ]
    total = body["total"]
    for key in total["buckets"]:
        assert D(total["buckets"][key]) == sum(D(p["buckets"][key]) for p in body["parties"])
    assert (D(total["buckets"]["31-60"]), D(total["buckets"]["NOT_YET_DUE"])) == (D(20000), D(7000))
    assert D(total["credit"]) == D(500)  # Customer B paid 1,500 on a 1,000 bill
    assert all(D(v) >= 0 for p in [total, *body["parties"]] for v in p["buckets"].values())
    for p in body["parties"]:
        bills = (
            await _get(
                api, owner, _url(books, "/bills"), side="receivable", ledger_id=p["ledger_id"]
            )
        )["bills"]
        signed = sum(-D(b["outstanding"]) if b["is_credit"] else D(b["outstanding"]) for b in bills)
        assert signed == D(p["bucket_total"]) - D(p["credit"])
    assert body["unverified_gates"] == ["G25", "G31"]


@pytest.mark.req("AC-46")
async def test_a_bill_due_in_5_days_shows_no_overdue_days(
    api: httpx.AsyncClient, books: Books, owner: User
) -> None:
    await _sale(books, "S-2", "7000", date(2026, 3, 21))
    [bill] = (
        await _get(
            api,
            owner,
            _url(books, "/bills"),
            side="receivable",
            ledger_id=str(books.ledgers["Customer A"].ledger_id),
        )
    )["bills"]
    assert (bill["bucket"], bill["days_overdue"], bill["outstanding"]) == (
        "NOT_YET_DUE",
        None,
        "7000.0000",
    )


@pytest.mark.req_partial("TZ-1.1")  # aging and payment behaviour; the rest of the app: P0-P8
@pytest.mark.parametrize(
    ("due", "before", "after"),
    [
        (date(2025, 12, 15), "2026-01-14T18:29:59Z", "2026-01-14T18:30:00Z"),  # IST midnight
        (date(2026, 1, 29), "2026-02-28T18:29:59Z", "2026-02-28T18:30:00Z"),  # month end
        (date(2026, 3, 1), "2026-03-31T18:29:59Z", "2026-03-31T18:30:00Z"),  # FY end
    ],
)
async def test_today_is_the_companys_local_date(
    api: httpx.AsyncClient, books: Books, owner: User, due: date, before: str, after: str
) -> None:
    """At 23:59:59 IST the bill is 30 days overdue; one second later it is the next day in
    India, 31 days and the next bucket, while the UTC date has not changed."""
    await _sale(books, "S-1", "100", due)
    ledger = str(books.ledgers["Customer A"].ledger_id)
    seen = []
    for instant in (before, after):
        with time_machine.travel(datetime.fromisoformat(instant).astimezone(UTC), tick=False):
            [bill] = (
                await _get(api, owner, _url(books, "/bills"), side="receivable", ledger_id=ledger)
            )["bills"]
        seen.append((bill["days_overdue"], bill["bucket"]))
    assert seen == [(30, "0-30"), (31, "31-60")]


async def test_as_of_and_the_allocation_drilldown(
    api: httpx.AsyncClient, books: Books, owner: User
) -> None:
    await _sale(books, "S-1", "10000", date(2026, 1, 31))
    await books.voucher(
        "Receipt",
        date(2026, 3, 1),
        [("Cash", "DEBIT", "6000"), ("Customer A", "CREDIT", "6000")],
        bills=[(1, "AGST_REF", "S-1", "6000")],
    )
    past = await _get(api, owner, _url(books), side="receivable", as_of="2026-02-15")
    assert D(past["total"]["buckets"]["0-30"]) == D(10000)
    rows = (
        await _get(
            api,
            owner,
            _url(books, "/allocations"),
            side="receivable",
            ledger_id=str(books.ledgers["Customer A"].ledger_id),
            reference="S-1",
        )
    )["allocations"]
    assert [(r["allocation_type"], r["amount"], r["voucher_type_name"]) for r in rows] == [
        ("NEW_REF", "10000.0000", "Sales"),
        ("AGST_REF", "-6000.0000", "Receipt"),
    ]


async def test_a_side_with_no_bills_at_all_is_zero_not_an_error(
    api: httpx.AsyncClient, books: Books, owner: User
) -> None:
    """GROUPING SETS emits a row per set even over no input, and SUM() of nothing is NULL, so
    both sides of a company that has never had a bill used to fail the schema. Every figure of
    an empty side is zero: nothing is unavailable."""
    for side in ("receivable", "payable"):
        body = await _get(api, owner, _url(books), side=side)
        total = body["total"]
        assert D(total["bucket_total"]) == D(0)
        assert all(D(v) == D(0) for v in total["buckets"].values())
        assert D(total["credit"]) == D(0)
        assert D(total["unadjusted_advances"]) == D(0)
        assert D(total["on_account"]) == D(0)
        assert D(total["unmatched_settlements"]) == D(0)
        assert D(total["net_exposure"]) == D(0)
        assert body["parties"] == []
        # The buckets are the real ones, never a NULL key from the empty grouping set.
        assert set(total["buckets"]) == {b["key"] for b in body["bucket_order"]}
