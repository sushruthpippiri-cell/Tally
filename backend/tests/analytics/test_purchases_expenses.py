"""P8.5: Purchase Value (ACC-1.2) and Expenses as net movement (D-044 #5, D-045 #1)."""

from datetime import date
from decimal import Decimal

import pytest

from app.analytics import query
from app.models.enums import SettingDataType
from tests.analytics.books import Books, make_books

DAY = date(2025, 8, 14)


async def total(books: Books, metric: str, **kw: object) -> Decimal:
    value = await query.total(books.session, await books.ctx(**kw), metric)  # type: ignore[arg-type]
    assert value is not None
    return value


async def by(books: Books, metric: str, key: str, label: str) -> dict[str, Decimal]:
    rows = await query.breakdown(books.session, await books.ctx(), metric, key, label)
    return {name: amount for _, name, amount in rows}


# --- purchases ----------------------------------------------------------------------------


async def _purchase(books: Books, amount: str = "5000", ref: str | None = None) -> None:
    await books.voucher(
        "Purchase",
        DAY,
        [
            ("Purchases", "DEBIT", amount),
            ("Input GST", "DEBIT", "900"),
            ("Supplier S", "CREDIT", str(Decimal(amount) + 900)),
        ],
        bills=[(2, "NEW_REF", ref, str(Decimal(amount) + 900))] if ref else None,
    )


async def _debit_note(books: Books, ref: str) -> None:
    await books.voucher(
        "Debit Note",
        date(2025, 9, 1),
        [
            ("Supplier S", "DEBIT", "1180"),
            ("Purchases", "CREDIT", "1000"),
            ("Input GST", "CREDIT", "180"),
        ],
        bills=[(0, "AGST_REF", ref, "1180")],
    )


@pytest.mark.req("AC-27")
async def test_a_purchase_counts_only_the_debit_on_the_purchase_ledger(books: Books) -> None:
    await books.voucher(
        "Purchase", DAY, [("Purchases", "DEBIT", "5000"), ("Supplier S", "CREDIT", "5000")]
    )
    assert await total(books, "purchases") == Decimal("5000")


@pytest.mark.req("ACC-1.2")
@pytest.mark.req_partial("ACC-2.2")  # sales half: test_sales.py
async def test_purchase_value_as_acc_1_2_defines_it(books: Books, g26_passed: None) -> None:
    """DEBIT entries on Purchase-list ledgers on ACTIVE PURCHASE vouchers, minus linked
    Purchase Returns, tax excluded in taxable-value mode."""
    await _purchase(books, ref="PB-1")  # +5,000 (+900 tax)
    await _debit_note(books, "PB-1")  # linked: -1,000
    await _debit_note(books, "PB-UNKNOWN")  # unlinked: not subtracted
    await books.voucher(  # cancelled
        "Purchase",
        DAY,
        [("Purchases", "DEBIT", "70"), ("Cash", "CREDIT", "70")],
        status="CANCELLED",
    )
    await books.voucher(  # a journal debiting Purchases is not a PURCHASE voucher
        "Journal", DAY, [("Purchases", "DEBIT", "8"), ("Cash", "CREDIT", "8")]
    )
    await books.voucher(  # a credit on the purchase ledger in a purchase is not a debit
        "Purchase", DAY, [("Cash", "DEBIT", "30"), ("Purchases", "CREDIT", "30")]
    )
    assert await total(books, "purchases") == Decimal("4000")
    await books.setting("analytics.taxable_value_mode", False, SettingDataType.BOOLEAN)
    assert await total(books, "purchases") == Decimal("4720")  # 5,900 - 1,180


@pytest.mark.req("ACC-5.4")
async def test_unlinked_notes_reduce_neither_sales_nor_purchases(
    books: Books, g26_passed: None
) -> None:
    await _purchase(books, ref="PB-1")
    await _debit_note(books, "PB-UNKNOWN")
    await books.voucher(
        "Sales",
        DAY,
        [("Customer A", "DEBIT", "900"), ("Sales", "CREDIT", "900")],
        bills=[(0, "NEW_REF", "INV-1", "900")],
    )
    await books.voucher(
        "Credit Note",
        DAY,
        [("Sales", "DEBIT", "100"), ("Customer A", "CREDIT", "100")],
        bills=[(1, "AGST_REF", "INV-UNKNOWN", "100")],
    )
    assert await total(books, "purchases") == Decimal("5000")
    assert await total(books, "sales") == Decimal("900")
    rows, _ = await query.drilldown(books.session, await books.ctx(), "unclassified_adjustments")
    assert sorted(r["adjustment_type"] for r in rows) == [
        "UNLINKED_CREDIT_NOTE",
        "UNLINKED_DEBIT_NOTE",
    ]


# --- expenses -----------------------------------------------------------------------------


@pytest.mark.req_partial("ACC-1.5")  # superseded as worded by D-044 #5 (net movement)
async def test_a_journal_crediting_an_expense_ledger_reduces_expenses(books: Books) -> None:
    await books.voucher(
        "Payment", DAY, [("Rent", "DEBIT", "12000"), ("HDFC Bank", "CREDIT", "12000")]
    )
    await books.voucher(  # a provision reversed
        "Journal", DAY, [("Loan", "DEBIT", "2000"), ("Rent", "CREDIT", "2000")]
    )
    await books.voucher(  # a refund credited to the expense
        "Receipt", DAY, [("Cash", "DEBIT", "500"), ("Freight", "CREDIT", "500")]
    )
    await books.voucher("Payment", DAY, [("Freight", "DEBIT", "800"), ("Cash", "CREDIT", "800")])
    assert await total(books, "expenses") == Decimal("10300")  # 12,000 - 2,000 + 800 - 500
    assert await by(books, "expenses", "ledger_id", "ledger_name") == {
        "Rent": Decimal("10000"),
        "Freight": Decimal("300"),
    }


@pytest.mark.req_partial("ACC-1.5")  # superseded as worded by D-044 #5 (net movement)
async def test_a_reclassification_between_expense_heads_moves_the_breakdown_not_the_total(
    books: Books,
) -> None:
    await books.voucher("Payment", DAY, [("Rent", "DEBIT", "1000"), ("Cash", "CREDIT", "1000")])
    await books.voucher("Payment", DAY, [("Freight", "DEBIT", "400"), ("Cash", "CREDIT", "400")])
    before = await total(books, "expenses")
    await books.voucher("Journal", DAY, [("Rent", "DEBIT", "150"), ("Freight", "CREDIT", "150")])
    assert await total(books, "expenses") == before == Decimal("1400")
    assert await by(books, "expenses", "ledger_id", "ledger_name") == {
        "Rent": Decimal("1150"),
        "Freight": Decimal("250"),
    }
    assert await by(books, "expenses", "group_id", "group_name") == {
        "Indirect Expenses": Decimal("1150"),
        "Direct Expenses": Decimal("250"),
    }


@pytest.mark.req_partial("ACC-1.5")  # grouped by cost centre; superseded wording: D-044 #5
async def test_the_cost_centre_breakdown_totals_the_metric(books: Books) -> None:
    await books.voucher(  # fully split
        "Payment",
        DAY,
        [("Rent", "DEBIT", "1000"), ("HDFC Bank", "CREDIT", "1000")],
        centres=[(0, "Retail", "600"), (0, "Online", "400")],
    )
    await books.voucher(  # partly split: 300 has no cost centre
        "Payment",
        DAY,
        [("Freight", "DEBIT", "500"), ("Cash", "CREDIT", "500")],
        centres=[(0, "Online", "200")],
    )
    await books.voucher(  # a credit allocated to a centre takes the entry's direction
        "Journal",
        DAY,
        [("Loan", "DEBIT", "50"), ("Rent", "CREDIT", "50")],
        centres=[(1, "Retail", "50")],
    )
    await books.voucher("Payment", DAY, [("Rent", "DEBIT", "70"), ("Cash", "CREDIT", "70")])
    expected = Decimal("1520")
    assert await total(books, "expenses") == expected
    centres = await by(books, "expenses", "cost_centre_id", "cost_centre_name")
    assert centres == {
        "Retail": Decimal("550"),
        "Online": Decimal("600"),
        "(No cost centre)": Decimal("370"),
    }
    assert sum(centres.values()) == expected
    rows, count = await query.drilldown(books.session, await books.ctx(), "expenses")
    assert count == 6 and sum(r["amount"] for r in rows) == expected


async def test_expenses_leave_out_cancelled_and_other_companies(books: Books) -> None:
    other = await make_books(books.session, name="Other Co")
    await books.voucher("Payment", DAY, [("Rent", "DEBIT", "100"), ("Cash", "CREDIT", "100")])
    await books.voucher(
        "Payment", DAY, [("Rent", "DEBIT", "9"), ("Cash", "CREDIT", "9")], status="CANCELLED"
    )
    await other.voucher("Payment", DAY, [("Rent", "DEBIT", "5"), ("Cash", "CREDIT", "5")])
    assert await total(books, "expenses") == Decimal("100")
    assert await total(books, "expenses", include_cancelled=True) == Decimal("109")
    assert await total(other, "expenses") == Decimal("5")
