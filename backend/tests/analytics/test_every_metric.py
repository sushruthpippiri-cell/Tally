"""P8.10: rules every metric in the registry obeys. A new metric must add a case here."""

from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import update

from app.analytics import query
from app.models.masters import Ledger
from tests.analytics.books import Books
from tests.factories import Entry

DAY = date(2025, 8, 14)
# metric -> (voucher type, entries of one contributing voucher, the classified ledger in it)
CASES: dict[str, tuple[str, list[Entry], str]] = {
    # Items qualify by voucher, not by ledger (ACC-1.8): no unresolved-ledger case.
    "product_revenue": (
        "Sales",
        [("Customer A", "DEBIT", "100"), ("Sales", "CREDIT", "100")],
        "",
    ),
    "sales": ("Sales", [("Customer A", "DEBIT", "100"), ("Sales", "CREDIT", "100")], "Sales"),
    "customer_revenue": (
        "Sales",
        [("Customer A", "DEBIT", "100"), ("Sales", "CREDIT", "100")],
        "Sales",
    ),
    "purchases": (
        "Purchase",
        [("Purchases", "DEBIT", "100"), ("Supplier S", "CREDIT", "100")],
        "Purchases",
    ),
    "supplier_purchases": (
        "Purchase",
        [("Purchases", "DEBIT", "100"), ("Supplier S", "CREDIT", "100")],
        "Purchases",
    ),
    "expenses": ("Payment", [("Rent", "DEBIT", "100"), ("Loan", "CREDIT", "100")], "Rent"),
    "cash_flow": ("Receipt", [("Cash", "DEBIT", "100"), ("Loan", "CREDIT", "100")], "Cash"),
    "cash_bank_position": (
        "Receipt",
        [("Cash", "DEBIT", "100"), ("Loan", "CREDIT", "100")],
        "Cash",
    ),
    "receivables": (
        "Sales",
        [("Customer A", "DEBIT", "100"), ("Sales", "CREDIT", "100")],
        "Customer A",
    ),
    "payables": (
        "Purchase",
        [("Purchases", "DEBIT", "100"), ("Supplier S", "CREDIT", "100")],
        "Supplier S",
    ),
    "ledger_balances": ("Payment", [("Rent", "DEBIT", "100"), ("Loan", "CREDIT", "100")], "Rent"),
    "unclassified_adjustments": (
        "Credit Note",
        [("Sales", "DEBIT", "100"), ("Customer A", "CREDIT", "100")],
        "Sales",
    ),
    # reconciliation-only (D-048 #4): Tally's totals are compared on these bases
    "recon_receipts": ("Receipt", [("Cash", "DEBIT", "100"), ("Loan", "CREDIT", "100")], "Cash"),
    "recon_payments": ("Payment", [("Rent", "DEBIT", "100"), ("Cash", "CREDIT", "100")], "Cash"),
}
OPENINGS = [
    "Customer A",
    "Customer B",
    "Supplier S",
    "Cash",
    "HDFC Bank",
    "ICICI OD",
    "Loan",
    "Output GST",
    "Input GST",
]


def test_every_registered_metric_has_a_case() -> None:
    assert set(CASES) == set(query.METRICS)


async def _unresolved_copy(books: Books, name: str) -> str:
    """The same ledger under a group whose chain is broken: no anchor (ACC-7.4)."""
    original = books.ledgers[name]
    group = next(g for g in books.groups.values() if g.group_id == original.group_id)
    broken = await books.ledger(f"{name} (broken)", group)
    await books.session.execute(
        update(Ledger)
        .where(Ledger.ledger_id == broken.ledger_id)
        .values(classification_group_id=None)
    )
    return broken.name


@pytest.mark.req("ACC-4.5")
@pytest.mark.req_partial("ACC-7.4")  # listed for review: tests/sync/test_hierarchy.py (P6)
@pytest.mark.parametrize("metric", sorted(CASES))
async def test_cancelled_missing_and_unresolved_never_count(books: Books, metric: str) -> None:
    vtype, entries, classified = CASES[metric]
    for ledger in OPENINGS:
        await books.opening(ledger, "DEBIT", "0")
    items = [("Soap", "1", "100", "100")] if metric == "product_revenue" else None
    await books.voucher(vtype, DAY, entries, items=items)

    async def figure(**flags: bool) -> Decimal | None:
        ctx = await books.ctx(**flags)
        if metric == "ledger_balances":  # all ledgers together always total zero: read one
            rows = await query.breakdown(books.session, ctx, metric, "ledger_id", "ledger_name")
            return {name: amount for _, name, amount in rows}[classified]
        return await query.total(books.session, ctx, metric)

    standard = await figure()
    assert standard not in (None, Decimal(0))
    await books.voucher(vtype, DAY, entries, items=items, status="CANCELLED")
    await books.voucher(vtype, DAY, entries, items=items, status="MISSING_IN_TALLY")
    if classified:
        broken = await _unresolved_copy(books, classified)
        await books.voucher(
            vtype, DAY, [(broken if e[0] == classified else e[0], *e[1:]) for e in entries]
        )  # type: ignore[misc]
    assert await figure() == standard
    assert await figure(include_cancelled=True) == 2 * standard
    assert await figure(include_cancelled=True, include_missing=True) == 3 * standard
