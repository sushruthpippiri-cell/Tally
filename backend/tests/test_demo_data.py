"""P14.D: `make demo-data` loads its company through the real Agent protocol, and the company
has what the dashboard needs to be checked by hand (D-053 #8)."""

from decimal import Decimal
from typing import Any

import httpx
import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from tally_tools.demo_data import UnsafeDatabase, assert_dev_database, load
from tests.factories import auth_header, make_user


async def _get(api: httpx.AsyncClient, user: dict[str, str], path: str, **params: Any) -> Any:
    r = await api.get(path, params=params, headers=user)
    assert r.status_code == 200, r.text
    return r.json()


async def test_the_demo_company_loads_through_the_agent_protocol(
    api: httpx.AsyncClient, session: AsyncSession
) -> None:
    user = auth_header(await make_user(session))
    loaded = await load(api, user)
    assert loaded["rejected"] == 0
    assert loaded["vouchers"] > 300
    base = f"/companies/{loaded['company_id']}"
    span = {"from": str(loaded["books_from"]), "to": str(loaded["as_of"])}

    # Total Sales Revenue is the generator's own sum of sales credits (the cancelled sale is
    # left out; the unlinked credit note is not subtracted until G26)
    sales = await _get(api, user, f"{base}/analytics/sales", **span)
    assert Decimal(sales["summary"]["amount"]) == loaded["sales_credits"]
    # every ledger together balances, openings included
    ledgers = await _get(api, user, f"{base}/analytics/ledger-balances", **span)
    assert Decimal(ledgers["summary"]["amount"]) == 0
    # overdue receivables in at least three buckets, plus the advance
    aging = await _get(api, user, f"{base}/analytics/aging", side="receivable")
    overdue = {k: Decimal(v) for k, v in aging["total"]["buckets"].items() if k[0].isdigit()}
    assert sum(1 for v in overdue.values() if v > 0) >= 3, overdue
    assert Decimal(aging["total"]["unadjusted_advances"]) > 0
    # the vouchers without inventory lines make a product difference
    difference = await _get(
        api, user, f"{base}/analytics/product-difference", group_by="voucher", **span
    )
    assert len(difference["breakdown"]) >= 4
    # expenses split over both cost centres and "(No cost centre)"
    expenses = await _get(api, user, f"{base}/analytics/expenses", group_by="cost_centre", **span)
    assert {b["label"] for b in expenses["breakdown"]} == {
        "Head Office",
        "Godown",
        "(No cost centre)",
    }
    # the mapped custom field reached the vouchers (AC-61 by hand)
    rows = await _get(api, user, f"{base}/analytics/sales/drilldown", page_size=500, **span)
    assert any((r["custom_fields"] or {}).get("salesman") for r in rows["rows"])
    # stock: a never-sold item in stock and an out-of-stock one, from today's snapshot
    stock = await _get(api, user, f"{base}/analytics/stock", page_size=500)
    counts = {c["key"]: c["count"] for c in stock["classes"]}
    assert counts["NEVER_SOLD"] >= 1 and counts["FAST"] >= 1, counts

    assert (await load(api, user))["already_loaded"]


@pytest.mark.parametrize(
    "url",
    [
        "postgresql+psycopg://u:p@db.example.com:5432/tally",
        "postgresql+psycopg://u:p@localhost:5432/tally_test",
        "postgresql+psycopg://u:p@localhost:5432/tally_bench",
    ],
)
def test_demo_data_refuses_any_database_but_the_local_dev_one(url: str) -> None:
    with pytest.raises(UnsafeDatabase):
        assert_dev_database(url)
    assert assert_dev_database("postgresql+psycopg://u:p@localhost:5432/tally") == "tally"
