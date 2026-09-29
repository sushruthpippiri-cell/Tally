"""P11.2-P11.5: aging per bill (SRS 10, FR-AGE-1/2, AGE-BILL-2-4, D-049), at fixed dates."""

import uuid
from datetime import date, timedelta
from decimal import Decimal
from typing import Any

import pytest

from app.analytics import aging
from app.core.permissions import CompanyContext
from app.models.balances import OpeningBillAllocation
from app.services import data_quality
from tests.analytics.books import FY_START, Books

TODAY = date(2026, 3, 16)  # the test clock's date in Asia/Kolkata
D = Decimal


async def sale(
    books: Books, ref: str, amount: str, due: date | None, day: date = date(2025, 12, 1), **kw: Any
) -> None:
    await books.voucher(
        "Sales",
        day,
        [("Customer A", "DEBIT", amount), ("Sales", "CREDIT", amount)],
        bills=[(0, "NEW_REF", ref, amount, due)],
        **kw,
    )


async def receipt(
    books: Books,
    ref: str,
    amount: str,
    day: date = date(2026, 1, 10),
    kind: str = "AGST_REF",
    party: str = "Customer A",
) -> None:
    await books.voucher(
        "Receipt",
        day,
        [("Cash", "DEBIT", amount), (party, "CREDIT", amount)],
        bills=[(1, kind, ref, amount)],
    )


async def aged(
    books: Books, side: str = "receivable", as_of: date = TODAY, boundaries: list[int] | None = None
) -> aging.Aging:
    ctx = await books.ctx(FY_START, as_of)
    return await aging.aging(books.session, ctx, side, boundaries or [30, 60, 90])


async def bills(books: Books, side: str = "receivable", as_of: date = TODAY) -> list[Any]:
    ctx = await books.ctx(FY_START, as_of)
    return list((await books.session.execute(aging.bills(ctx, side, [30, 60, 90]))).mappings())


def party(result: aging.Aging, name: str) -> aging.Party:
    return next(p for p in result.parties if p.ledger_name == name)


def nonzero(buckets: dict[str, Decimal]) -> dict[str, Decimal]:
    return {k: v for k, v in buckets.items() if v}


async def dq(books: Books, check: str) -> list[dict[str, Any]]:
    ctx = CompanyContext(books.company.company_id, uuid.uuid4(), frozenset())
    return (await data_quality.items(books.session, ctx, check, 200, 0)).items


# --- AC-45, AC-46, AC-47 and the bucket boundaries -----------------------------------------


@pytest.mark.req("AC-45", "FR-AGE-1")
async def test_a_bill_due_45_days_ago_is_in_31_to_60(books: Books) -> None:
    await sale(books, "S-1", "20000", TODAY - timedelta(days=45))
    result = await aged(books)
    assert nonzero(result.total.buckets) == {"31-60": D(20000)}
    assert nonzero(party(result, "Customer A").buckets) == {"31-60": D(20000)}


@pytest.mark.req("AC-46")
async def test_a_bill_due_in_5_days_is_not_yet_due_and_never_negative(books: Books) -> None:
    await sale(books, "S-1", "7000", TODAY + timedelta(days=5))
    assert nonzero((await aged(books)).total.buckets) == {aging.NOT_YET_DUE: D(7000)}
    [bill] = await bills(books)
    assert (bill["bucket"], bill["days_overdue"]) == (aging.NOT_YET_DUE, None)


@pytest.mark.req("AC-47")
async def test_a_bill_with_no_due_date_is_due_date_unavailable(books: Books) -> None:
    await sale(books, "S-1", "3000", None)
    assert nonzero((await aged(books)).total.buckets) == {aging.NO_DUE_DATE: D(3000)}


@pytest.mark.parametrize(
    ("days", "bucket"),
    [
        (0, "0-30"),
        (30, "0-30"),
        (31, "31-60"),
        (60, "31-60"),
        (61, "61-90"),
        (90, "61-90"),
        (91, "90+"),
    ],
)
async def test_bucket_boundaries_by_days_overdue(books: Books, days: int, bucket: str) -> None:
    await sale(books, "S-1", "100", TODAY - timedelta(days=days), day=date(2025, 4, 1))
    [bill] = await bills(books)
    assert (bill["days_overdue"], bill["bucket"]) == (days, bucket)


@pytest.mark.parametrize(
    ("days", "bucket"), [(15, "0-15"), (16, "16-45"), (45, "16-45"), (46, "45+")]
)
async def test_configured_boundaries_make_their_own_buckets(
    books: Books, days: int, bucket: str
) -> None:
    await sale(books, "S-1", "100", TODAY - timedelta(days=days), day=date(2025, 4, 1))
    result = await aged(books, boundaries=[15, 45])
    assert result.labels == ["0-15", "16-45", "45+"]
    assert nonzero(result.total.buckets) == {bucket: D(100)}


# --- outstanding: signed allocations (owner point 1) ---------------------------------------


@pytest.mark.req("FR-AGE-2")
async def test_outstanding_nets_receipts_part_settlements_and_credit_notes(books: Books) -> None:
    await sale(books, "S-1", "10000", TODAY - timedelta(days=10))
    await receipt(books, "S-1", "6000")
    await books.voucher(  # a linked credit note settles the same bill
        "Credit Note",
        date(2026, 2, 1),
        [("Sales", "DEBIT", "3000"), ("Customer A", "CREDIT", "3000")],
        bills=[(1, "AGST_REF", "S-1", "3000")],
    )
    [bill] = await bills(books)
    assert (bill["reference_name"], bill["outstanding"], bill["bucket"]) == ("S-1", D(1000), "0-30")


async def test_a_refund_against_a_bill_raises_what_is_outstanding(books: Books) -> None:
    """Owner: ₹10,000 billed, ₹10,000 received, ₹2,000 paid back against the bill -> ₹2,000
    owed again. As absolute amounts "New minus every Against" would give -₹2,000."""
    await sale(books, "S-1", "10000", TODAY - timedelta(days=40))
    await receipt(books, "S-1", "10000")
    await books.voucher(
        "Payment",
        date(2026, 2, 1),
        [("Customer A", "DEBIT", "2000"), ("Cash", "CREDIT", "2000")],
        bills=[(0, "AGST_REF", "S-1", "2000")],
    )
    result = await aged(books)
    assert nonzero(result.total.buckets) == {"31-60": D(2000)}
    assert result.total.credit == 0


async def test_a_bill_paid_more_than_it_was_raised_for_is_a_credit_never_a_bucket(
    books: Books,
) -> None:
    await sale(books, "S-1", "10000", TODAY - timedelta(days=40))
    await receipt(books, "S-1", "12000")
    result = await aged(books)
    assert result.total.credit == D(2000) and party(result, "Customer A").credit == D(2000)
    assert nonzero(result.total.buckets) == {}  # no bucket, and nothing negative anywhere
    assert all(v >= 0 for p in [result.total, *result.parties] for v in p.buckets.values())
    assert result.total.net_exposure == D(-2000)
    [item] = await dq(books, "over_settled_bills")
    assert (item["side"], item["reference_name"], D(item["credit"])) == (
        "receivable",
        "S-1",
        D(2000),
    )


async def test_the_payable_side_mirrors_it(books: Books) -> None:
    """Credit +: a purchase raises what we owe, a payment lowers it, a supplier's refund
    raises it again, and an over-payment is a credit."""
    await books.voucher(
        "Purchase",
        date(2025, 12, 1),
        [("Purchases", "DEBIT", "5000"), ("Supplier S", "CREDIT", "5000")],
        bills=[(1, "NEW_REF", "P-1", "5000", TODAY - timedelta(days=70))],
    )
    await books.voucher(
        "Payment",
        date(2026, 1, 5),
        [("Supplier S", "DEBIT", "5000"), ("Cash", "CREDIT", "5000")],
        bills=[(0, "AGST_REF", "P-1", "5000")],
    )
    await receipt(books, "P-1", "1500", party="Supplier S")  # a refund from the supplier
    result = await aged(books, "payable")
    assert nonzero(result.total.buckets) == {"61-90": D(1500)}
    await books.voucher(
        "Payment",
        date(2026, 2, 5),
        [("Supplier S", "DEBIT", "4000"), ("Cash", "CREDIT", "4000")],
        bills=[(0, "AGST_REF", "P-1", "4000")],
    )
    over = await aged(books, "payable")
    assert (over.total.credit, nonzero(over.total.buckets)) == (D(2500), {})


# --- advances, on account, unmatched, net exposure -----------------------------------------


@pytest.mark.req("AC-48", "AGE-BILL-3")
async def test_an_advance_is_unadjusted_until_a_bill_takes_it(books: Books) -> None:
    await receipt(books, "ADV-1", "5000", kind="ADVANCE")
    first = await aged(books)
    assert (first.total.advances, nonzero(first.total.buckets)) == (D(5000), {})
    await books.voucher(  # a sale that uses ₹2,000 of the advance (GATE-G25, D-049 #2)
        "Sales",
        date(2026, 2, 1),
        [("Customer A", "DEBIT", "7000"), ("Sales", "CREDIT", "7000")],
        bills=[(0, "AGST_REF", "ADV-1", "2000"), (0, "NEW_REF", "S-9", "5000", TODAY)],
    )
    later = await aged(books)
    assert later.total.advances == D(3000)
    assert nonzero(later.total.buckets) == {"0-30": D(5000)}
    assert later.total.net_exposure == D(2000)  # 5,000 billed less 3,000 still in advance


@pytest.mark.req("AC-49")
async def test_on_account_is_its_own_line(books: Books) -> None:
    await books.voucher(
        "Payment",
        date(2026, 1, 5),
        [("Supplier S", "DEBIT", "1500"), ("Cash", "CREDIT", "1500")],
        bills=[(0, "ON_ACCOUNT", "", "1500")],
    )
    result = await aged(books, "payable")
    assert (result.total.on_account, nonzero(result.total.buckets)) == (D(1500), {})
    assert party(result, "Supplier S").on_account == D(1500)


@pytest.mark.req("AC-50", "AGE-BILL-4")
async def test_customer_and_supplier_advances_stay_on_their_sides(books: Books) -> None:
    await receipt(books, "ADV-C", "5000", kind="ADVANCE")
    await books.voucher(
        "Payment",
        date(2026, 1, 5),
        [("Supplier S", "DEBIT", "5000"), ("Cash", "CREDIT", "5000")],
        bills=[(0, "ADVANCE", "ADV-S", "5000")],
    )
    receivable, payable = await aged(books), await aged(books, "payable")
    assert (receivable.total.advances, payable.total.advances) == (D(5000), D(5000))
    assert [p.ledger_name for p in receivable.parties] == ["Customer A"]
    assert [p.ledger_name for p in payable.parties] == ["Supplier S"]
    assert (receivable.total.net_exposure, payable.total.net_exposure) == (D(-5000), D(-5000))


async def test_a_settlement_of_a_cancelled_bill_is_unmatched_and_listed(books: Books) -> None:
    await sale(books, "S-7", "1000", TODAY, status="CANCELLED")
    await receipt(books, "S-7", "1000")
    result = await aged(books)
    assert (result.total.unmatched, nonzero(result.total.buckets)) == (D(1000), {})
    [item] = await dq(books, "unmatched_settlements")
    assert (item["reference_name"], D(item["amount"])) == ("S-7", D(1000))


# --- opening bills, reused names, unsupported, no bill details, as of ----------------------


def opening_bill(books: Books, ref: str, amount: str, due: date | None, day: date | None) -> None:
    books.session.add(
        OpeningBillAllocation(
            company_id=books.company.company_id,
            ledger_id=books.ledgers["Customer A"].ledger_id,
            reference_name=ref,
            bill_date=day,
            due_date=due,
            amount_absolute=D(amount),
            accounting_direction="DEBIT",
            financial_year_start=FY_START,
        )
    )


async def test_opening_bills_are_aged_like_new_references(books: Books) -> None:
    """Owner point 2 (D-022): from their own bill and due dates; settled by Against
    References like any bill."""
    opening_bill(books, "OB-1", "8000", TODAY - timedelta(days=40), date(2025, 3, 1))
    opening_bill(books, "OB-2", "500", None, None)
    await receipt(books, "OB-1", "3000")
    [ob1, ob2] = sorted(await bills(books), key=lambda b: b["reference_name"])
    assert (ob1["bill_date"], ob1["outstanding"], ob1["bucket"]) == (
        date(2025, 3, 1),
        D(5000),
        "31-60",
    )
    assert (ob2["outstanding"], ob2["bucket"]) == (D(500), aging.NO_DUE_DATE)


async def test_a_reused_bill_name_is_one_bill_marked_unverified_and_listed(books: Books) -> None:
    """Owner (D-049 #7): invoice numbers restarting each year give one party two bills named
    "1"; they are not merged silently."""
    opening_bill(books, "1", "4000", date(2025, 3, 15), date(2025, 3, 1))  # FY 2024-25
    await sale(books, "1", "6000", TODAY - timedelta(days=5), day=date(2026, 2, 1))  # FY 2025-26
    await sale(books, "2", "100", TODAY)
    reused = {b["reference_name"]: b["reused"] for b in await bills(books)}
    assert reused == {"1": True, "2": False}
    [item] = await dq(books, "bill_reference_reused")
    assert (item["reference_name"], D(item["outstanding"])) == ("1", D(10000))


@pytest.mark.req("AGE-BILL-2")
async def test_unsupported_allocations_are_never_aged(books: Books) -> None:
    await sale(books, "S-1", "1000", TODAY)
    await books.voucher(
        "Receipt",
        date(2026, 1, 10),
        [("Cash", "DEBIT", "400"), ("Customer A", "CREDIT", "400")],
        bills=[(1, "UNSUPPORTED", "S-1", "400")],
    )
    result = await aged(books)
    assert nonzero(result.total.buckets) == {"0-30": D(1000)}
    assert result.total.net_exposure == D(1000)
    assert [i["reference_name"] for i in await dq(books, "unsupported_bill_allocations")] == ["S-1"]


async def test_a_party_without_bill_details_is_one_balance_never_bucketed(books: Books) -> None:
    """SRS 10.3: its balance (ACC-9.4), "bill details not available". A ledger with a zero
    balance is left out; one whose opening never arrived is listed as unavailable."""
    await books.opening("Customer A", "DEBIT", "0")
    await books.opening("Customer B", "DEBIT", "0")
    await books.voucher(
        "Sales", date(2026, 1, 1), [("Customer B", "DEBIT", "900"), ("Sales", "CREDIT", "900")]
    )
    result = await aged(books)
    assert [(name, amount) for _, name, amount in result.no_bill_details] == [
        ("Customer B", D(900))
    ]
    assert nonzero(result.total.buckets) == {}


async def test_aging_as_of_a_past_date_ignores_later_allocations(books: Books) -> None:
    await sale(books, "S-1", "1000", date(2026, 1, 31))
    await receipt(books, "S-1", "1000", day=date(2026, 3, 1))
    past = await aged(books, as_of=date(2026, 2, 15))
    assert nonzero(past.total.buckets) == {"0-30": D(1000)}  # 15 days overdue then
    assert nonzero((await aged(books)).total.buckets) == {}


async def test_the_unverified_gates_are_listed(books: Books) -> None:
    assert (await aged(books)).unverified_gates == ["G25", "G31"]
