"""P8.4: Total Sales Revenue (ACC-1.1, ACC-2.x, ACC-5.x, ACC-8.x) and its single query path."""

from datetime import date
from decimal import Decimal

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st
from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from app.analytics import query
from app.models.enums import Nature, SettingDataType
from app.models.masters import Ledger
from tests.analytics.books import Books, make_books

DAY = date(2025, 8, 14)


async def sales(books: Books, **kw: object) -> Decimal:
    return await query.total(books.session, await books.ctx(**kw), "sales")  # type: ignore[arg-type]


async def sale(books: Books, amount: str = "10000", vtype: str = "Sales", **kw: object) -> None:
    await books.voucher(
        vtype, DAY, [("Customer A", "DEBIT", amount), ("Sales", "CREDIT", amount)], **kw
    )


@pytest.mark.req("AC-26")
@pytest.mark.req_partial("ACC-2.1")  # purchases, expenses, cash flow: P8.5, P8.6
async def test_a_sale_counts_once_not_twice_and_not_zero(books: Books) -> None:
    await sale(books)
    assert await sales(books) == Decimal("10000")


async def test_only_credits_on_sales_ledgers_count(books: Books) -> None:
    # A debit on the sales ledger (e.g. a discount) is not revenue, and neither is anything
    # on a ledger outside the Sales list.
    await books.voucher(
        "Sales",
        DAY,
        [
            ("Customer A", "DEBIT", "9500"),
            ("Sales", "DEBIT", "500"),
            ("Sales", "CREDIT", "10000"),
        ],
    )
    await books.voucher(
        "Sales", DAY, [("Customer A", "DEBIT", "300"), ("Freight", "CREDIT", "300")]
    )
    assert await sales(books) == Decimal("10000")


@pytest.mark.req_partial("ACC-2.2")  # purchases: P8.5
async def test_tax_is_excluded_in_taxable_value_mode_and_included_when_it_is_off(
    books: Books,
) -> None:
    await books.voucher(
        "Sales",
        DAY,
        [
            ("Customer A", "DEBIT", "11800"),
            ("Sales", "CREDIT", "10000"),
            ("Output GST", "CREDIT", "1800"),
        ],
    )
    assert await sales(books) == Decimal("10000")
    await books.setting("analytics.taxable_value_mode", False, SettingDataType.BOOLEAN)
    assert await sales(books) == Decimal("11800")


@pytest.mark.req("AC-28")
@pytest.mark.req_partial("ACC-7.4")  # the other classified metrics: P8.5-P8.7
async def test_nested_groups_count_and_unresolved_or_unlisted_ledgers_do_not(books: Books) -> None:
    online = await books.group("Sales – Online", books.groups["Sales Accounts"])
    await books.ledger("Online Sales", online)
    other_income = await books.group("Commission Received", None, nature=Nature.INCOME)
    await books.ledger("Commission", other_income)  # top-level group, not on the Sales list
    broken = await books.ledger("Broken Sales", books.groups["Sales Accounts"])
    await books.session.execute(
        update(Ledger)
        .where(Ledger.ledger_id == broken.ledger_id)
        .values(classification_group_id=None)  # its group chain is broken (UNRESOLVED)
    )
    for ledger, amount in [("Online Sales", "700"), ("Commission", "40"), ("Broken Sales", "9")]:
        await books.voucher(
            "Sales", DAY, [("Customer A", "DEBIT", amount), (ledger, "CREDIT", amount)]
        )
    assert await sales(books) == Decimal("700")


@pytest.mark.req("AC-29")
@pytest.mark.req_partial("ACC-8.2", "ACC-8.3")  # every type-filtered metric: P8.5-P9
async def test_a_custom_sales_type_counts_and_other_base_types_do_not(books: Books) -> None:
    await sale(books, "1000", "POS Invoice")
    await sale(books, "20", "Memorandum")  # OTHER: an unresolved or non-accounting type
    await sale(books, "300", "Journal")  # a journal crediting Sales is not a SALES voucher
    assert await sales(books) == Decimal("1000")


# --- returns (ACC-5.x) --------------------------------------------------------------------


async def _invoice_and_note(books: Books, note_ref: str) -> None:
    await books.voucher(
        "Sales",
        DAY,
        [
            ("Customer A", "DEBIT", "11800"),
            ("Sales", "CREDIT", "10000"),
            ("Output GST", "CREDIT", "1800"),
        ],
        bills=[(0, "NEW_REF", "INV-1", "11800")],
    )
    await books.voucher(
        "Credit Note",
        date(2025, 9, 1),
        [
            ("Sales", "DEBIT", "2000"),
            ("Output GST", "DEBIT", "360"),
            ("Customer A", "CREDIT", "2360"),
        ],
        bills=[(2, "AGST_REF", note_ref, "2360")],
    )


@pytest.mark.req("AC-35")
async def test_a_linked_credit_note_reduces_sales(books: Books, g26_passed: None) -> None:
    await _invoice_and_note(books, "INV-1")
    assert await sales(books) == Decimal("8000")  # tax excluded on both sides
    await books.setting("analytics.taxable_value_mode", False, SettingDataType.BOOLEAN)
    assert await sales(books) == Decimal("9440")  # 11,800 - 2,360
    # The return counts in the period of the note.
    assert await sales(books, date_from=DAY, date_to=DAY) == Decimal("11800")


@pytest.mark.req("ACC-1.1")
async def test_total_sales_revenue_as_acc_1_1_defines_it(books: Books, g26_passed: None) -> None:
    """CREDIT entries on Sales-list ledgers, on ACTIVE vouchers of base type SALES, minus
    linked Sales Returns, tax excluded in taxable-value mode: every clause at once."""
    await _invoice_and_note(books, "INV-1")  # +10,000 sale (+1,800 tax), -2,000 linked return
    await sale(books, "500", "POS Invoice")  # +500: derived from Sales
    await sale(books, "70", status="CANCELLED")  # not ACTIVE
    await sale(books, "8", "Journal")  # not a SALES voucher
    await books.voucher(  # a debit on the sales ledger is not a credit
        "Sales", DAY, [("Sales", "DEBIT", "30"), ("Cash", "CREDIT", "30")]
    )
    assert await sales(books) == Decimal("8500")


@pytest.mark.req("AC-36")
@pytest.mark.req_partial("ACC-5.4")  # purchases: P8.5
async def test_an_unlinked_credit_note_is_not_subtracted_and_is_listed(
    books: Books, g26_passed: None
) -> None:
    await _invoice_and_note(books, "NO-SUCH-BILL")
    assert await sales(books) == Decimal("10000")
    rows, _ = await query.drilldown(books.session, await books.ctx(), "unclassified_adjustments")
    assert [(r["adjustment_type"], r["amount"]) for r in rows] == [
        ("UNLINKED_CREDIT_NOTE", Decimal("2000"))
    ]


async def test_before_g26_passes_no_note_is_subtracted(books: Books) -> None:
    await _invoice_and_note(books, "INV-1")
    assert await sales(books) == Decimal("10000")


# --- statuses, tenancy, one query path ------------------------------------------------------


@pytest.mark.req_partial("ACC-4.5")  # purchases, expenses, cash flow, balances: P8.5-P8.7
async def test_cancelled_and_missing_sales_are_left_out_unless_asked_for(books: Books) -> None:
    await sale(books, "100")
    await sale(books, "20", status="CANCELLED")
    await sale(books, "3", status="MISSING_IN_TALLY")
    assert await sales(books) == Decimal("100")
    assert await sales(books, include_cancelled=True, include_missing=True) == Decimal("123")


async def test_another_companys_sales_never_count(books: Books, session: AsyncSession) -> None:
    other = await make_books(session, name="Other Co")
    await sale(books, "100")
    await sale(other, "5")
    assert await sales(books) == Decimal("100")
    assert await sales(other) == Decimal("5")


@pytest.mark.req_partial("ACC-4.4", "FR-DD-5", "FR-2.1")  # API/exports: tests/api/test_exports.py
async def test_every_view_of_sales_sums_to_the_same_figure(books: Books, g26_passed: None) -> None:
    await _invoice_and_note(books, "INV-1")
    await sale(books, "450", "POS Invoice")
    await books.voucher(
        "Sales", date(2026, 2, 1), [("Customer B", "DEBIT", "75"), ("Sales", "CREDIT", "75")]
    )
    s, ctx = books.session, await books.ctx()
    total = await query.total(s, ctx, "sales")
    assert total == Decimal("8525")
    for granularity in ("day", "month", "quarter"):
        points = await query.series(s, ctx, "sales", granularity)  # type: ignore[arg-type]
        assert sum(p.amount for p in points) == total
    by_ledger = await query.breakdown(s, ctx, "sales", "ledger_id", "ledger_name")
    assert sum(a for _, _, a in by_ledger) == total
    rows, count = await query.drilldown(s, ctx, "sales")
    assert count == len(rows) == 4 and sum(r["amount"] for r in rows) == total
    assert [p.period for p in await query.series(s, ctx, "sales", "quarter")] == [
        "FY2025-26 Q2",
        "FY2025-26 Q4",
    ]


# --- property: single-sided whatever the voucher looks like --------------------------------

SALES_LEDGERS = ["Sales", "Sales – Online"]
PARTIES = ["Customer A", "Customer B", "Cash", "HDFC Bank"]
NON_CLASS = ["Customer A", "Cash", "Loan", "ICICI OD", "Supplier S"]
amounts = st.decimals(min_value="0.01", max_value="99999.99", places=2)
voucher_st = st.fixed_dictionaries(
    {
        "credits": st.lists(
            st.tuples(st.sampled_from(SALES_LEDGERS), amounts), min_size=1, max_size=4
        ),
        "tax": st.one_of(st.none(), amounts),
        "party": st.sampled_from(PARTIES),
        "noise": st.lists(
            st.tuples(st.sampled_from(NON_CLASS), st.sampled_from(NON_CLASS), amounts), max_size=3
        ),
    }
)


@pytest.mark.req("ACC-2.1")
@settings(
    max_examples=25, deadline=None, suppress_health_check=[HealthCheck.function_scoped_fixture]
)
@given(vouchers=st.lists(voucher_st, min_size=1, max_size=5))
async def test_sales_is_the_sum_of_sales_credits_and_nothing_else(
    session: AsyncSession, vouchers: list[dict[str, object]]
) -> None:
    """Random balanced sales vouchers: Total Sales = Σ the credits on Sales-class ledgers.
    Extra balanced debit/credit pairs on non-class ledgers in the same vouchers (duplicating
    the debit side elsewhere) change nothing. A fresh company per example."""
    books = await make_books(session)
    await books.ledger(
        "Sales – Online", await books.group("Sales – Online", books.groups["Sales Accounts"])
    )
    expected = Decimal(0)
    for v in vouchers:
        credits = [(ledger, "CREDIT", str(a)) for ledger, a in v["credits"]]  # type: ignore[attr-defined]
        tax = [("Output GST", "CREDIT", str(v["tax"]))] if v["tax"] is not None else []
        gross = sum((Decimal(a) for _, _, a in credits + tax), Decimal(0))
        noise = [
            e
            for dr, cr, a in v["noise"]  # type: ignore[attr-defined]
            for e in ((dr, "DEBIT", str(a)), (cr, "CREDIT", str(a)))
        ]
        await books.voucher(
            "Sales", DAY, [(v["party"], "DEBIT", str(gross)), *credits, *tax, *noise]
        )  # type: ignore[list-item]
        expected += sum((Decimal(a) for _, _, a in credits), Decimal(0))
    assert await sales(books) == expected
