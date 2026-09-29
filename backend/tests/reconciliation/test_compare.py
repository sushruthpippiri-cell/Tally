"""P10.5: each comparison on its basis (docs/reconciliation-basis.md, D-008, D-048), every
comparison recorded (REC-1.3), and what the checks can and cannot catch."""

from datetime import date
from decimal import Decimal
from typing import Any

import pytest
from sqlalchemy import select

from app.models.enums import SyncRunStatus
from app.models.masters import StockItem
from app.models.sync import ReconciliationResult, ReconciliationRun
from tests.analytics.books import FY_START, Books
from tests.reconciliation.tally import AS_OF, PERIODS, Tally

AUG = date(2025, 8, 14)
FYTD = next(p for p in PERIODS if p.label.endswith("to date"))


async def rows(books: Books, run: ReconciliationRun, metric: str) -> dict[Any, Any]:
    """(period_start, period_end) or entity_id -> the result row."""
    found = await books.session.execute(
        select(ReconciliationResult).where(
            ReconciliationResult.sync_run_id == run.sync_run_id,
            ReconciliationResult.metric == metric,
        )
    )
    return {(r.entity_id or (r.period_start, r.period_end)): r for r in found.scalars().all()}


def figures(row: ReconciliationResult) -> tuple[Decimal, Decimal, str]:
    return (row.tally_value, row.local_value, row.result)


async def sale(books: Books, amount: str = "100000", **kw: Any) -> None:
    tax = str(Decimal(amount) * Decimal("0.18"))
    total = str(Decimal(amount) + Decimal(tax))
    await books.voucher(
        "Sales",
        AUG,
        [
            ("Customer A", "DEBIT", total),
            ("Sales", "CREDIT", amount),
            ("Output GST", "CREDIT", tax),
        ],
        **kw,
    )


# --- the four totals -------------------------------------------------------------------------


@pytest.mark.req("REC-1.3")
@pytest.mark.req_partial("REC-1.1")  # the Tally side's TDL is a draft until GATE-G36 passes
async def test_sales_credits_are_raw_credits_on_sales_ledgers_in_every_period(books: Books) -> None:
    """Tax lines, credit notes and cancelled vouchers are out on both sides, whether or not
    returns are linked (D-008). Every period gets a row: months, the year to date, last year."""
    await sale(books)
    await sale(books, "999", status="CANCELLED")  # Tally leaves cancelled vouchers out too
    await books.voucher(  # a return: never subtracted on this basis
        "Credit Note",
        date(2025, 9, 2),
        [("Sales", "DEBIT", "500"), ("Customer A", "CREDIT", "500")],
    )
    tally = await Tally.new(books)
    tally.total("Sales", "Sales", AUG, credit="100000")
    tally.total("Output GST", "Sales", AUG, credit="18000")  # not a Sales-class ledger
    tally.total("Customer A", "Sales", AUG, debit="118000")
    tally.total("Sales", "Credit Note", date(2025, 9, 2), debit="500")  # not a sale
    run = await tally.reconcile()
    sales = await rows(books, run, "SALES_CREDITS")
    assert len(sales) == len(PERIODS)  # REC-1.3: every comparison recorded
    aug = next(p for p in PERIODS if p.label == "2025-08")
    assert figures(sales[(aug.start, aug.end)]) == (Decimal(100000), Decimal(100000), "PASS")
    assert figures(sales[(FYTD.start, FYTD.end)]) == (Decimal(100000), Decimal(100000), "PASS")
    assert all(r.result == "PASS" for r in sales.values())


@pytest.mark.parametrize(
    ("local", "result"), [("100010", "PASS"), ("100012", "FAIL")]
)  # SRS 9.3: equal to the percentage tolerance passes; both exceeded fails
async def test_the_tolerance_decides_and_the_difference_is_recorded(
    books: Books, local: str, result: str
) -> None:
    await sale(books, local)
    tally = await Tally.new(books)
    tally.total("Sales", "Sales", AUG, credit="100000")
    tally.closings()
    run = await tally.reconcile()
    row = (await rows(books, run, "SALES_CREDITS"))[(FYTD.start, FYTD.end)]
    difference = Decimal(local) - 100000
    assert (row.absolute_difference, row.percentage_difference, row.result) == (
        difference,
        difference / 1000,  # of ₹100,000, in %
        result,
    )


async def test_purchases_receipts_and_payments_on_their_bases(books: Books) -> None:
    """Receipts: debits on Cash/Bank-list ledgers in Receipt vouchers; payments: credits in
    Payment vouchers. A contra between own accounts is neither (D-048 #4)."""
    await books.voucher(
        "Purchase", AUG, [("Purchases", "DEBIT", "4000"), ("Supplier S", "CREDIT", "4000")]
    )
    await books.voucher(
        "Receipt", AUG, [("Cash", "DEBIT", "5000"), ("Customer A", "CREDIT", "5000")]
    )
    await books.voucher(
        "Payment", AUG, [("Rent", "DEBIT", "3000"), ("HDFC Bank", "CREDIT", "3000")]
    )
    await books.voucher(
        "Contra", AUG, [("HDFC Bank", "DEBIT", "10000"), ("Cash", "CREDIT", "10000")]
    )
    tally = await Tally.new(books)
    tally.total("Purchases", "Purchase", AUG, debit="4000")
    tally.total("Cash", "Receipt", AUG, debit="5000")
    tally.total("HDFC Bank", "Payment", AUG, credit="3000")
    tally.total("HDFC Bank", "Contra", AUG, debit="10000")
    tally.total("Cash", "Contra", AUG, credit="10000")
    run = await tally.reconcile()
    for metric, amount in (("PURCHASE_DEBITS", 4000), ("RECEIPTS", 5000), ("PAYMENTS", 3000)):
        row = (await rows(books, run, metric))[(FYTD.start, FYTD.end)]
        assert figures(row) == (Decimal(amount), Decimal(amount), "PASS"), metric


async def test_a_tally_total_on_a_ledger_that_never_synced_fails_the_run(books: Books) -> None:
    """Its vouchers cannot have synced either: left out of both sides the gap would hide."""
    await sale(books)
    tally = await Tally.new(books)
    tally.total("Sales", "Sales", AUG, credit="100000")
    tally.total("Sales - Export", "Sales", AUG, credit="7000", guid="l-export")  # Tally only
    tally.closings()
    run = await tally.reconcile()
    assert run.overall == "FAIL"
    [ghost] = [n for n in run.not_compared if n["entity_guid"] == "l-export"]
    assert (ghost["metric"], ghost["name"], ghost["fails"]) == ("TOTALS", "Sales - Export", True)


async def test_the_local_side_is_the_synced_data_whatever_tally_uploaded(books: Books) -> None:
    """SRS 9.1: with no Tally totals at all, the local figure is still the synced ₹100,000."""
    await sale(books)
    tally = await Tally.new(books)
    tally.closings()
    run = await tally.reconcile()
    assert figures((await rows(books, run, "SALES_CREDITS"))[(FYTD.start, FYTD.end)]) == (
        Decimal(0),
        Decimal(100000),
        "FAIL",
    )


# --- independence (owner, D-048 #5) ---------------------------------------------------------


@pytest.mark.req_partial("ACC-9.5")  # Tally's own closing balance: live half with GATE-G19
async def test_a_voucher_the_shared_filter_wrongly_drops_fails_ledger_balance_only(
    books: Books,
) -> None:
    """A ₹5,000 sale that the shared voucher Collection wrongly leaves out is missing from our
    synced rows **and** from Tally's totals (same filter), so SALES_CREDITS still passes. Tally's
    own closing balances include it, so the balances of its ledgers fail."""
    await sale(books)
    tally = await Tally.new(books)
    tally.total("Sales", "Sales", AUG, credit="100000")  # the filter dropped the ₹5,000 here too
    tally.closings(
        {"Customer A": "123900", "Sales": "-105000", "Output GST": "-18900"}  # it is in these
    )
    run = await tally.reconcile()
    assert all(r.result == "PASS" for r in (await rows(books, run, "SALES_CREDITS")).values())
    balances = {
        books_name(books, entity): r.result
        for entity, r in (await rows(books, run, "LEDGER_BALANCE")).items()
    }
    assert {n for n, result in balances.items() if result == "FAIL"} == {
        "Customer A",
        "Sales",
        "Output GST",
    }
    assert run.overall == "FAIL"


def books_name(books: Books, ledger_id: Any) -> str:
    return next(n for n, led in books.ledgers.items() if led.ledger_id == ledger_id)


# --- ledger balances -----------------------------------------------------------------------


@pytest.mark.req("AC-38")
@pytest.mark.req_partial("ACC-9.5", "TEST-4.2")  # the live half: GATE-G19 captures
async def test_a_bank_ledger_opening_plus_movements_matches_tallys_closing(books: Books) -> None:
    """AC-38: ₹50,000 Dr opening + ₹20,000 net Dr movements = ₹70,000 Dr on D, and it matches
    Tally within tolerance. Every other ledger is compared too (TEST-4.2)."""
    tally = await Tally.new(books, {"HDFC Bank": "50000"})
    await books.voucher(
        "Receipt", AUG, [("HDFC Bank", "DEBIT", "30000"), ("Customer A", "CREDIT", "30000")]
    )
    await books.voucher(
        "Payment", date(2025, 9, 1), [("Rent", "DEBIT", "10000"), ("HDFC Bank", "CREDIT", "10000")]
    )
    tally.total("HDFC Bank", "Receipt", AUG, debit="30000")
    tally.total("HDFC Bank", "Payment", date(2025, 9, 1), credit="10000")
    tally.closings({"HDFC Bank": "70000", "Customer A": "-30000", "Rent": "10000"})
    run = await tally.reconcile()
    balances = await rows(books, run, "LEDGER_BALANCE")
    bank = balances[books.ledgers["HDFC Bank"].ledger_id]
    assert figures(bank) == (Decimal(70000), Decimal(70000), "PASS")
    assert (bank.period_start, bank.period_end) == (FY_START, AS_OF)
    assert len(balances) == len(books.ledgers)  # every ledger compared
    assert all(r.result == "PASS" for r in balances.values())
    assert run.overall == "PASS"


async def test_income_and_expense_ledgers_compare_this_years_movement(books: Books) -> None:
    """ACC-9.2: Tally is asked from the start of the financial year, like the Phase 8 balance."""
    tally = await Tally.new(books)
    await books.voucher(
        "Payment", date(2025, 3, 1), [("Rent", "DEBIT", "999"), ("Cash", "CREDIT", "999")]
    )
    await books.voucher("Payment", AUG, [("Rent", "DEBIT", "100"), ("Cash", "CREDIT", "100")])
    tally.closings({"Rent": "100", "Cash": "-1099"})
    run = await tally.reconcile()
    rent = (await rows(books, run, "LEDGER_BALANCE"))[books.ledgers["Rent"].ledger_id]
    assert figures(rent) == (Decimal(100), Decimal(100), "PASS")


async def test_what_cannot_be_compared_is_listed_and_only_real_gaps_fail(books: Books) -> None:
    """Data Quality problems (no opening, ACC-9.6; an unresolved chain, ACC-7.4) are listed but
    do not fail the run; a ledger Tally reports and we lack, or the reverse, does."""
    tally = await Tally.new(books, bare=True)
    for name in ("Customer A", "Customer B", "Supplier S", "Output GST", "Input GST", "Cash"):
        await books.opening(name, "DEBIT", "0")  # HDFC Bank, ICICI OD, Loan have none
    broken = await books.ledger("Suspense", books.groups["Sundry Debtors"])
    broken.classification_group_id = None
    tally.closings()
    run = await tally.reconcile()
    reasons = {n["name"]: (n["reason"], n["fails"]) for n in run.not_compared}
    assert reasons["HDFC Bank"] == ("opening balance unavailable (Data Quality)", False)
    assert reasons["Suspense"] == ("unresolved group chain (Data Quality)", False)
    assert run.overall == "PASS"

    again = await Tally.new(books, bare=True)
    again.closings(omit=frozenset({"Customer B"}))  # a ledger we have, Tally did not report
    run = await again.reconcile()
    [gap] = [n for n in run.not_compared if n["name"] == "Customer B"]
    assert (gap["reason"], gap["fails"]) == ("not in Tally's closing balances", True)
    assert run.overall == "FAIL"


async def test_no_tally_balances_at_all_is_incomplete_and_a_partial_run_is_too(
    books: Books,
) -> None:
    tally = await Tally.new(books)
    assert (await tally.reconcile()).overall == "INCOMPLETE"  # nothing failed, nothing came
    partial = await Tally.new(books, bare=True)
    partial.run.status = SyncRunStatus.PARTIAL
    partial.closings()
    assert (await partial.reconcile()).overall == "INCOMPLETE"


# --- stock (D-048 #3) ------------------------------------------------------------------------


async def test_stock_compares_this_runs_snapshot_with_tallys_second_read(books: Books) -> None:
    items = {
        i.name: i
        for i in (
            await books.session.execute(
                select(StockItem).where(StockItem.company_id == books.company.company_id)
            )
        ).scalars()
    }
    tally = await Tally.new(books)
    tally.closings()
    soap, rice, pen = items["Soap"], items["Rice"], items["Pen"]
    tally.snapshot(soap.stock_item_id, "40")
    tally.stock(soap.tally_guid, "40")
    tally.snapshot(rice.stock_item_id, "98", "Kgs")
    tally.stock(rice.tally_guid, "100", "Kgs")  # AC-44 at run level: 2 % > 0.5 %
    tally.snapshot(pen.stock_item_id, "5", run=False)  # an earlier run's snapshot only
    tally.stock(pen.tally_guid, "5")
    run = await tally.reconcile()
    stock = await rows(books, run, "STOCK_QTY")
    assert figures(stock[soap.stock_item_id]) == (Decimal(40), Decimal(40), "PASS")
    assert figures(stock[rice.stock_item_id]) == (Decimal(100), Decimal(98), "FAIL")
    pen_skip = next(n for n in run.not_compared if n["name"] == "Pen")
    assert (pen_skip["reason"], pen_skip["fails"]) == ("no snapshot stored by this run", True)


async def test_stock_in_different_units_is_never_compared(books: Books) -> None:
    soap = (
        await books.session.execute(
            select(StockItem).where(
                StockItem.company_id == books.company.company_id, StockItem.name == "Soap"
            )
        )
    ).scalar_one()
    tally = await Tally.new(books)
    tally.closings()
    tally.snapshot(soap.stock_item_id, "4", "Box")
    tally.stock(soap.tally_guid, "48", "Nos")
    run = await tally.reconcile()
    skip = next(n for n in run.not_compared if n["name"] == "Soap")
    assert (skip["reason"], skip["fails"]) == ("units differ: Tally Nos, stored Box", True)
    assert await rows(books, run, "STOCK_QTY") == {}


async def test_the_run_lists_the_gates_its_figures_still_wait_for(books: Books) -> None:
    tally = await Tally.new(books)
    tally.closings()
    run = await tally.reconcile()
    assert run.unverified_gates == ["G18", "G19", "G21", "G23", "G36", "G37"]
    assert run.as_of == AS_OF
