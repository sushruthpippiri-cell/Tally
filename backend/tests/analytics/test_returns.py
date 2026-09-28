"""P8.3: which credit and debit notes are returns (ACC-5.x), and the Unclassified Adjustments
metric and Data Quality check for the rest."""

from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.analytics import query
from app.analytics.returns import CREDIT_NOTE, DEBIT_NOTE, linked_notes
from app.core import gates
from app.core.permissions import CompanyContext
from app.services import data_quality
from tests.analytics.books import Books

SALE_DAY, NOTE_DAY = date(2025, 5, 10), date(2025, 6, 2)
METRIC = "unclassified_adjustments"


@pytest.fixture
def g26_passed(monkeypatch: pytest.MonkeyPatch) -> None:
    statuses = {g: "NOT_TESTED" for g in gates.load_gate_status()} | {"G26": "PASSED"}
    monkeypatch.setattr(gates, "_default_statuses", lambda: statuses)


async def _sale(books: Books, ref: str = "INV-1", status: str = "ACTIVE") -> None:
    await books.voucher(
        "Sales",
        SALE_DAY,
        [
            ("Customer A", "DEBIT", "11800"),
            ("Sales", "CREDIT", "10000"),
            ("Output GST", "CREDIT", "1800"),
        ],
        bills=[(0, "NEW_REF", ref, "11800")],
        status=status,
    )


async def _credit_note(books: Books, ref: str = "INV-1", party: str = "Customer A") -> str:
    note = await books.voucher(
        "Credit Note",
        NOTE_DAY,
        [("Sales", "DEBIT", "2000"), ("Output GST", "DEBIT", "360"), (party, "CREDIT", "2360")],
        bills=[(2, "AGST_REF", ref, "2360")],
        number="CN-1",
    )
    return str(note.voucher_id)


async def _purchase_and_debit_note(books: Books, ref: str = "PB-9") -> str:
    await books.voucher(
        "Purchase",
        SALE_DAY,
        [("Purchases", "DEBIT", "5000"), ("Supplier S", "CREDIT", "5000")],
        bills=[(1, "NEW_REF", "PB-9", "5000")],
    )
    note = await books.voucher(
        "Debit Note",
        NOTE_DAY,
        [("Supplier S", "DEBIT", "700"), ("Purchases", "CREDIT", "700")],
        bills=[(0, "AGST_REF", ref, "700")],
    )
    return str(note.voucher_id)


async def _linked(books: Books, note: str) -> set[str]:
    stmt = linked_notes(
        books.company.company_id,
        gates.gate_passed("G26"),
        CREDIT_NOTE if note == "credit" else DEBIT_NOTE,
    )
    return {str(v) for v in (await books.session.scalars(stmt)).all()}


async def _adjustments(books: Books) -> list[tuple[str, str, Decimal]]:
    rows, _ = await query.drilldown(books.session, await books.ctx(), METRIC)
    return [(r["adjustment_type"], r["ledger_name"], r["amount"]) for r in rows]


@pytest.mark.req("ACC-5.5")
async def test_until_g26_passes_even_a_perfectly_linked_note_is_unlinked(books: Books) -> None:
    await _sale(books)
    await _credit_note(books)
    assert await _linked(books, "credit") == set()
    assert await _adjustments(books) == [("UNLINKED_CREDIT_NOTE", "Sales", Decimal("2000"))]


@pytest.mark.req("ACC-5.1")
async def test_a_credit_note_is_a_return_only_when_it_names_a_sales_bill(
    books: Books, g26_passed: None
) -> None:
    await _sale(books)
    await _sale(books, ref="INV-CANCELLED", status="CANCELLED")
    await books.voucher(  # a NEW_REF from a purchase, same party and name: not a sales bill
        "Purchase",
        SALE_DAY,
        [("Purchases", "DEBIT", "50"), ("Customer A", "CREDIT", "50")],
        bills=[(1, "NEW_REF", "INV-FROM-PURCHASE", "50")],
    )
    linked = await _credit_note(books)
    unlinked = {
        await _credit_note(books, ref="NO-SUCH-BILL"),
        await _credit_note(books, ref="INV-1", party="Customer B"),  # another party's INV-1
        await _credit_note(books, ref="INV-CANCELLED"),
        await _credit_note(books, ref="INV-FROM-PURCHASE"),
    }
    assert await _linked(books, "credit") == {linked}
    assert linked not in unlinked


@pytest.mark.req("ACC-5.2")
async def test_a_debit_note_is_a_return_only_when_it_names_a_purchase_bill(
    books: Books, g26_passed: None
) -> None:
    linked = await _purchase_and_debit_note(books)
    other = await books.voucher(
        "Debit Note",
        NOTE_DAY,
        [("Supplier S", "DEBIT", "10"), ("Purchases", "CREDIT", "10")],
        bills=[(0, "AGST_REF", "PB-UNKNOWN", "10")],
    )
    assert await _linked(books, "debit") == {linked}
    assert await _adjustments(books) == [("UNLINKED_DEBIT_NOTE", "Purchases", Decimal("10"))]
    assert str(other.voucher_id) not in await _linked(books, "debit")


@pytest.mark.req("ACC-5.3")
@pytest.mark.req_partial("ACC-5.4")  # not subtracted from sales: P8.4; from purchases: P8.5
async def test_unlinked_notes_are_classified_and_listed_with_what_they_would_reverse(
    books: Books, g26_passed: None
) -> None:
    await _sale(books)
    await _credit_note(books)  # linked: not an adjustment
    await _credit_note(books, ref="NO-SUCH-BILL")
    await _purchase_and_debit_note(books, ref="PB-UNKNOWN")
    assert await _adjustments(books) == [
        ("UNLINKED_CREDIT_NOTE", "Sales", Decimal("2000")),  # tax excluded (taxable-value mode)
        ("UNLINKED_DEBIT_NOTE", "Purchases", Decimal("700")),
    ]


async def test_with_taxable_value_mode_off_the_notes_tax_is_listed_too(books: Books) -> None:
    from app.models.enums import SettingDataType

    await books.setting("analytics.taxable_value_mode", False, SettingDataType.BOOLEAN)
    await _credit_note(books)
    assert sorted(await _adjustments(books)) == [
        ("UNLINKED_CREDIT_NOTE", "Output GST", Decimal("360")),
        ("UNLINKED_CREDIT_NOTE", "Sales", Decimal("2000")),
    ]


async def test_the_data_quality_check_lists_the_unlinked_notes(
    session: AsyncSession, books: Books, g26_passed: None
) -> None:
    await _sale(books)
    linked = await _credit_note(books)
    unlinked = await _credit_note(books, ref="NO-SUCH-BILL")
    check = data_quality.CHECKS["unlinked_notes"]
    ctx = CompanyContext(books.company.company_id, books.company.company_id, frozenset())
    rows = (await session.execute(await check.query(session, ctx))).mappings().all()
    assert [(str(r["voucher_id"]), r["adjustment_type"]) for r in rows] == [
        (unlinked, "UNLINKED_CREDIT_NOTE")
    ]
    assert linked not in {str(r["voucher_id"]) for r in rows}
