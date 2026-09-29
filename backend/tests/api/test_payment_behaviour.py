"""P11.7: customer payment behaviour (SRS 10.4, FR-PAY-1-6, D-049 #5), through the API."""

from datetime import date
from decimal import Decimal
from typing import Any

import httpx
import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import gates
from app.models.company import User
from app.models.enums import RoleName, SettingDataType
from tests.analytics.books import Books, make_books
from tests.factories import auth_header, make_user

D = Decimal


@pytest.fixture
async def books(session: AsyncSession) -> Books:
    return await make_books(session)


@pytest.fixture
async def owner(session: AsyncSession, books: Books) -> User:
    return await make_user(session, books.company, RoleName.OWNER)


@pytest.fixture
def g25_passed(monkeypatch: pytest.MonkeyPatch) -> None:
    passed = {g: "NOT_TESTED" for g in gates.load_gate_status()} | {"G25": "PASSED"}
    monkeypatch.setattr(gates, "_default_statuses", lambda: passed)


async def _sale(
    books: Books, ref: str, amount: str, day: date, due: date | None, party: str = "Customer A"
) -> None:
    await books.voucher(
        "Sales",
        day,
        [(party, "DEBIT", amount), ("Sales", "CREDIT", amount)],
        bills=[(0, "NEW_REF", ref, amount, due)],
    )


async def _settle(
    books: Books,
    ref: str,
    amount: str,
    day: date,
    vtype: str = "Receipt",
    party: str = "Customer A",
) -> None:
    other = {"Receipt": "Cash", "Credit Note": "Sales", "Journal": "Rent"}[vtype]
    await books.voucher(
        vtype,
        day,
        [(other, "DEBIT", amount), (party, "CREDIT", amount)],
        bills=[(1, "AGST_REF", ref, amount)],
    )


async def _get(api: httpx.AsyncClient, books: Books, owner: User) -> Any:
    r = await api.get(
        f"/companies/{books.company.company_id}/analytics/payment-behaviour",
        headers=auth_header(owner),
    )
    assert r.status_code == 200, r.text
    return r.json()


@pytest.mark.req("FR-PAY-6")
async def test_hidden_until_the_allocation_type_gate_passes(
    api: httpx.AsyncClient, books: Books, owner: User
) -> None:
    await _sale(books, "S-1", "10000", date(2025, 6, 1), date(2025, 6, 11))
    await _settle(books, "S-1", "10000", date(2025, 6, 11))
    body = await _get(api, books, owner)
    assert body == {
        "available": False,
        "reason": "Awaiting Tally validation (G25)",
        "window_from": None,
        "window_to": None,
        "min_settlements": None,
        "overall": None,
        "customers": [],
        "excluded_settlements": {},
        "notes": [],
        "unverified_gates": ["G25", "G31"],
    }


@pytest.mark.req("AC-51", "FR-PAY-1", "FR-PAY-3")
@pytest.mark.req_partial("FR-PAY-2")  # superseded as worded: receipts only (D-049 #5)
async def test_ac51_part_settlements_average_14_days_to_pay(
    api: httpx.AsyncClient, books: Books, owner: User, g25_passed: None
) -> None:
    """A ₹10,000 bill dated 1 June, ₹6,000 settled 11 June and ₹4,000 on 21 June:
    (6,000 × 10 + 4,000 × 20) ÷ 10,000 = 14. Two settlements, so the minimum is set to 2 here
    (the default 3 would show "insufficient history", tested below)."""
    await books.setting("payment.min_settlements", 2, SettingDataType.INTEGER)
    await _sale(books, "S-1", "10000", date(2025, 6, 1), date(2025, 6, 15))
    await _settle(books, "S-1", "6000", date(2025, 6, 11))
    await _settle(books, "S-1", "4000", date(2025, 6, 21))
    body = await _get(api, books, owner)
    [customer] = body["customers"]
    assert (customer["ledger_name"], customer["settlements"]) == ("Customer A", 2)
    assert D(customer["avg_days_to_pay"]) == D(14)
    # FR-PAY-3: from the due date (15 June), early payment counts 0: (6,000×0 + 4,000×6) ÷ 10,000
    assert D(customer["avg_days_past_due"]) == D("2.4")
    assert D(body["overall"]["avg_days_to_pay"]) == D(14)
    assert (body["window_to"], body["window_from"]) == ("2026-03-16", "2025-03-16")


@pytest.mark.req("FR-PAY-5")
async def test_fewer_than_three_settlements_is_insufficient_history(
    api: httpx.AsyncClient, books: Books, owner: User, g25_passed: None
) -> None:
    await _sale(books, "S-1", "10000", date(2025, 6, 1), None)
    await _settle(books, "S-1", "6000", date(2025, 6, 11))
    await _settle(books, "S-1", "4000", date(2025, 6, 21))
    [customer] = (await _get(api, books, owner))["customers"]
    assert customer["insufficient_history"] is True
    assert (customer["avg_days_to_pay"], customer["avg_days_past_due"]) == (None, None)


@pytest.mark.req("FR-PAY-4")
async def test_only_receipts_count_and_the_rest_is_listed(
    api: httpx.AsyncClient, books: Books, owner: User, g25_passed: None
) -> None:
    """Owner (D-049 #5): a credit note or a write-off journal settling a bill is not a payment.
    Advances, on-account amounts and refunds are not settlements (FR-PAY-4). Outside the
    window is out. A bill without a due date is left out of days past due, and counted."""
    await books.setting("payment.min_settlements", 1, SettingDataType.INTEGER)
    await _sale(books, "S-1", "10000", date(2025, 6, 1), None)
    await _settle(books, "S-1", "5000", date(2025, 6, 21))  # 20 days: the only payment
    await _settle(books, "S-1", "3000", date(2025, 6, 2), vtype="Credit Note")  # a return
    await _settle(books, "S-1", "500", date(2025, 6, 3), vtype="Journal")  # a write-off
    await books.voucher(  # an advance: never a settlement
        "Receipt",
        date(2025, 7, 1),
        [("Cash", "DEBIT", "900"), ("Customer A", "CREDIT", "900")],
        bills=[(1, "ADVANCE", "ADV-1", "900")],
    )
    await books.voucher(  # a refund raises the bill: never a settlement
        "Payment",
        date(2025, 7, 2),
        [("Customer A", "DEBIT", "200"), ("Cash", "CREDIT", "200")],
        bills=[(0, "AGST_REF", "S-1", "200")],
    )
    await _sale(books, "OLD", "100", date(2025, 1, 1), None)
    await _settle(books, "OLD", "100", date(2025, 3, 1))  # before the 365-day window
    body = await _get(api, books, owner)
    [customer] = body["customers"]
    assert (customer["settlements"], D(customer["settled_amount"])) == (1, D(5000))
    assert D(customer["avg_days_to_pay"]) == D(20)
    assert customer["avg_days_past_due"] is None  # no due date on the only bill
    assert body["excluded_settlements"] == {"CREDIT_NOTE": 1, "JOURNAL": 1}
    assert body["notes"] == [
        "Only settlements on Receipt vouchers are payments: 1 on credit notes (returns and "
        "discounts); 1 on journals left out.",
        "1 settlement(s) of bills with no due date left out of average days past due.",
    ]
