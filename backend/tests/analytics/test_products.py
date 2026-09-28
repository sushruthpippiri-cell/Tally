"""P9.3: Product-attributed Revenue and the difference under one label (ACC-1.8-1.10,
ACC-VAL-1, D-046 #2-3, #5)."""

from collections.abc import Callable
from datetime import date
from decimal import Decimal

import pytest

from app.analytics import query
from app.analytics.query import NON_PRODUCT_REVENUE, PRODUCT_ATTRIBUTION_DIFFERENCE
from app.models.enums import SettingDataType
from tests.analytics.books import Books

DAY = date(2025, 8, 14)


async def product(books: Books) -> Decimal | None:
    return await query.total(books.session, await books.ctx(), "product_revenue")


async def _ac32(books: Books) -> None:
    await books.ledger("Service Charges", books.groups["Sales Accounts"])
    await books.voucher(
        "Sales",
        DAY,
        [
            ("Customer A", "DEBIT", "100000"),
            ("Sales", "CREDIT", "92000"),
            ("Service Charges", "CREDIT", "8000"),
        ],
        items=[("Soap", "1000", "50", "50000"), ("Rice", "600", "70", "42000")],
    )


@pytest.mark.req("AC-32", "ACC-1.10")
async def test_the_difference_is_a_data_quality_figure_until_g28(books: Books) -> None:
    await _ac32(books)
    diff = await query.product_difference(books.session, await books.ctx())
    assert (diff.total_sales, diff.product_attributed, diff.amount) == (
        Decimal("100000"),
        Decimal("92000"),
        Decimal("8000"),
    )
    assert diff.label == PRODUCT_ATTRIBUTION_DIFFERENCE  # not "service revenue"


@pytest.mark.req("ACC-1.8")
async def test_only_lines_on_qualifying_sales_vouchers_count(books: Books) -> None:
    lines = [("Soap", "10", "10", "100")]
    entries = [("Customer A", "DEBIT", "100"), ("Sales", "CREDIT", "100")]
    await books.voucher("Sales", DAY, entries, items=lines)
    await books.voucher("POS Invoice", DAY, entries, items=lines)  # derived from Sales
    await books.voucher("Sales", DAY, entries, items=lines, status="CANCELLED")
    await books.voucher("Memorandum", DAY, entries, items=lines)  # OTHER
    await books.voucher(
        "Purchase",
        DAY,
        [("Purchases", "DEBIT", "100"), ("Supplier S", "CREDIT", "100")],
        items=lines,
    )
    assert await product(books) == Decimal("200")


async def test_a_linked_credit_notes_lines_come_off(books: Books, g26_passed: None) -> None:
    await books.voucher(
        "Sales",
        DAY,
        [("Customer A", "DEBIT", "500"), ("Sales", "CREDIT", "500")],
        items=[("Soap", "50", "10", "500")],
        bills=[(0, "NEW_REF", "INV-1", "500")],
    )
    for ref in ("INV-1", "NO-SUCH"):
        await books.voucher(
            "Credit Note",
            DAY,
            [("Sales", "DEBIT", "30"), ("Customer A", "CREDIT", "30")],
            items=[("Soap", "3", "10", "30")],
            bills=[(1, "AGST_REF", ref, "30")],
        )
    assert await product(books) == Decimal("470")  # only the linked note
    rows, _ = await query.drilldown(books.session, await books.ctx(), "product_revenue")
    assert sorted((r["quantity"], r["unit"]) for r in rows) == [
        (Decimal("-3"), "Nos"),
        (Decimal("50"), "Nos"),
    ]
    diff = await query.product_difference(books.session, await books.ctx())
    assert diff.amount == Decimal("0")  # the same return treatment on both sides


@pytest.mark.req("ACC-1.9")
@pytest.mark.parametrize(
    ("g28", "taxable_mode", "label"),
    [
        ("NOT_TESTED", True, PRODUCT_ATTRIBUTION_DIFFERENCE),
        ("FAILED", True, PRODUCT_ATTRIBUTION_DIFFERENCE),
        ("PASSED", True, NON_PRODUCT_REVENUE),
        # Lines are before tax: with tax in Total Sales the bases differ (D-046 #5).
        ("PASSED", False, PRODUCT_ATTRIBUTION_DIFFERENCE),
    ],
)
async def test_the_label_needs_g28_and_taxable_value_mode(
    books: Books, set_gates: Callable[..., None], g28: str, taxable_mode: bool, label: str
) -> None:
    set_gates(G28=g28)
    await books.setting("analytics.taxable_value_mode", taxable_mode, SettingDataType.BOOLEAN)
    await _ac32(books)
    assert (await query.product_difference(books.session, await books.ctx())).label == label
