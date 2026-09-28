"""P8.7: balances roll forward from books-beginning (ACC-9.x, D-039 #5, D-044 #6, D-045 #2-3)."""

from datetime import date
from decimal import Decimal

import pytest

from app.analytics import query
from app.models.enums import SettingDataType
from tests.analytics.books import FY_START, Books

D = date(2025, 12, 31)


async def figure(
    books: Books, metric: str, day: date = D, since: date = FY_START
) -> Decimal | None:
    return await query.total(books.session, await books.ctx(since, day), metric)


async def per_ledger(books: Books, metric: str, **kw: date) -> dict[str, Decimal | None]:
    ctx = await books.ctx(kw.get("since", FY_START), kw.get("day", D))
    rows = await query.breakdown(books.session, ctx, metric, "ledger_id", "ledger_name")
    return {name: amount for _, name, amount in rows}


@pytest.mark.req_partial("AC-38")  # "matches Tally within tolerance": P10 (G19)
@pytest.mark.req_partial("ACC-9.1")  # roll-forward from books-beginning replaces it (D-039 #5)
async def test_a_bank_ledger_is_its_opening_plus_net_movements(books: Books) -> None:
    await books.opening("HDFC Bank", "DEBIT", "50000")
    await books.voucher(
        "Receipt",
        date(2025, 6, 1),
        [("HDFC Bank", "DEBIT", "30000"), ("Customer A", "CREDIT", "30000")],
    )
    await books.voucher(
        "Payment", date(2025, 9, 1), [("Rent", "DEBIT", "10000"), ("HDFC Bank", "CREDIT", "10000")]
    )
    await books.voucher(  # after D: not in D's balance
        "Payment", date(2026, 1, 5), [("Rent", "DEBIT", "1"), ("HDFC Bank", "CREDIT", "1")]
    )
    await books.voucher(  # cancelled: never counts
        "Receipt",
        date(2025, 7, 1),
        [("HDFC Bank", "DEBIT", "999"), ("Cash", "CREDIT", "999")],
        status="CANCELLED",
    )
    assert (await per_ledger(books, "ledger_balances"))["HDFC Bank"] == Decimal("70000")  # Dr


async def test_one_books_beginning_opening_carries_across_years(books: Books) -> None:
    await books.opening("HDFC Bank", "DEBIT", "1000")
    await books.voucher(
        "Receipt",
        date(2025, 5, 1),
        [("HDFC Bank", "DEBIT", "200"), ("Customer A", "CREDIT", "200")],
    )
    await books.voucher(
        "Receipt", date(2026, 5, 1), [("HDFC Bank", "DEBIT", "30"), ("Customer A", "CREDIT", "30")]
    )
    next_year = await per_ledger(
        books, "ledger_balances", since=date(2026, 4, 1), day=date(2026, 6, 30)
    )
    assert next_year["HDFC Bank"] == Decimal("1230")


@pytest.mark.req("ACC-9.2")
async def test_income_and_expense_ledgers_report_the_period_movement_only(books: Books) -> None:
    for day, amount in [(date(2025, 5, 1), "100"), (date(2026, 5, 1), "7")]:
        await books.voucher("Sales", day, [("Cash", "DEBIT", amount), ("Sales", "CREDIT", amount)])
        await books.voucher("Payment", day, [("Rent", "DEBIT", amount), ("Cash", "CREDIT", amount)])
    this_year = await per_ledger(books, "ledger_balances", since=FY_START, day=D)
    next_year = await per_ledger(
        books, "ledger_balances", since=date(2026, 4, 1), day=date(2027, 3, 31)
    )
    assert (this_year["Sales"], this_year["Rent"]) == (Decimal("-100"), Decimal("100"))
    assert (next_year["Sales"], next_year["Rent"]) == (Decimal("-7"), Decimal("7"))  # no carry


@pytest.mark.req("ACC-9.6")
async def test_no_opening_row_is_unavailable_never_zero_and_a_zero_opening_is_a_figure(
    books: Books,
) -> None:
    await books.opening("HDFC Bank", "DEBIT", "500")
    await books.voucher(
        "Contra", date(2025, 6, 1), [("Cash", "DEBIT", "100"), ("HDFC Bank", "CREDIT", "100")]
    )
    assert await figure(books, "cash_bank_position") is None  # Cash has no opening
    ctx = await books.ctx(FY_START, D)
    assert await query.unavailable(books.session, ctx, "cash_bank_position") == (1, ["Cash"])
    assert (await per_ledger(books, "cash_bank_position")) == {
        "Cash": None,  # listed first
        "HDFC Bank": Decimal("400"),
    }
    await books.opening("Cash", "DEBIT", "0")  # blank in Tally = zero (D-044 #6)
    assert await figure(books, "cash_bank_position") == Decimal("500")
    assert await query.unavailable(books.session, ctx, "cash_bank_position") == (0, [])


@pytest.mark.req("ACC-9.3")
async def test_cash_and_bank_position_counts_bank_od_only_when_listed(books: Books) -> None:
    for ledger in ("Cash", "HDFC Bank", "ICICI OD"):
        await books.opening(ledger, "DEBIT", "0")
    await books.voucher(
        "Payment", date(2025, 6, 1), [("Rent", "DEBIT", "300"), ("ICICI OD", "CREDIT", "300")]
    )
    await books.voucher(
        "Receipt", date(2025, 6, 2), [("Cash", "DEBIT", "1000"), ("Customer A", "CREDIT", "1000")]
    )
    assert await figure(books, "cash_bank_position") == Decimal("1000")
    await books.setting(
        "classification.cash_bank_groups",
        [
            {"type": "PREDEFINED", "reserved_name": "Cash-in-Hand"},
            {"type": "PREDEFINED", "reserved_name": "Bank Accounts"},
            {"type": "PREDEFINED", "reserved_name": "Bank OD A/c"},
        ],
        SettingDataType.JSON,
    )
    assert await figure(books, "cash_bank_position") == Decimal("700")


@pytest.mark.req("ACC-9.4")
async def test_receivables_and_payables_on_a_date(books: Books) -> None:
    await books.opening("Customer A", "DEBIT", "2000")
    await books.opening("Customer B", "DEBIT", "0")
    await books.opening("Supplier S", "CREDIT", "800")
    await books.voucher(
        "Sales", date(2025, 6, 1), [("Customer B", "DEBIT", "500"), ("Sales", "CREDIT", "500")]
    )
    await books.voucher(
        "Receipt", date(2025, 7, 1), [("Cash", "DEBIT", "1500"), ("Customer A", "CREDIT", "1500")]
    )
    await books.voucher(
        "Purchase",
        date(2025, 7, 2),
        [("Purchases", "DEBIT", "300"), ("Supplier S", "CREDIT", "300")],
    )
    assert await figure(books, "receivables") == Decimal("1000")  # Dr
    assert await figure(books, "payables") == Decimal("-1100")  # Cr
    assert await figure(books, "receivables", day=date(2025, 6, 30)) == Decimal("2500")
