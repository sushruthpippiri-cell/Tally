"""P15.2: the deterministic rules (FR-3.2 as amended by D-015/D-055 #1, FR-3.3 as amended by
D-055 #2). AC-56, AC-57."""

import uuid
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.anomaly import rules
from app.models.config import AnomalyFlag
from app.models.enums import (
    AnomalyRule,
    ExplanationStatus,
    SettingDataType,
    VoucherStatus,
)
from app.models.vouchers import Voucher, VoucherEntry
from tests.analytics.books import Books, make_books

NOW = datetime(2026, 3, 16, tzinfo=UTC)
START = date(2025, 6, 1)


@pytest.fixture
async def books(session: AsyncSession) -> Books:
    return await make_books(session)


async def sale(books: Books, day: date, amount: str, party: str = "Customer A") -> uuid.UUID:
    v = await books.voucher("Sales", day, [(party, "DEBIT", amount), ("Sales", "CREDIT", amount)])
    return v.voucher_id


async def receipt(books: Books, day: date, amount: str, party: str = "Customer A") -> uuid.UUID:
    v = await books.voucher("Receipt", day, [("Cash", "DEBIT", amount), (party, "CREDIT", amount)])
    return v.voucher_id


async def scan(books: Books, *candidates: uuid.UUID, earliest: date = START) -> list[AnomalyFlag]:
    company_id = books.company.company_id
    await rules.evaluate(books.session, company_id, set(candidates), earliest, NOW)
    # The rules write bulk SQL, so a flag loaded by an earlier scan is stale. populate_existing
    # overwrites it from this SELECT; expire_all() would also expire `books.company`, whose
    # company_id is then read outside the async attribute-loading context.
    rows = await books.session.execute(
        select(AnomalyFlag)
        .where(AnomalyFlag.cleared_at.is_(None))
        .order_by(AnomalyFlag.id)
        .execution_options(populate_existing=True)
    )
    return list(rows.scalars())


async def history(books: Books, amounts: list[str], party: str = "Customer A") -> None:
    """Prior transactions, one per day from START."""
    for i, amount in enumerate(amounts):
        await sale(books, START + timedelta(days=i), amount, party)


# --- FR-3.2: dispersion AND scale (D-055 #1), over the three cases the owner named -----------


@pytest.mark.req("FR-3.2")
@pytest.mark.parametrize(
    ("amount", "flagged"),
    [("70001", False), ("100000", False), ("450000", True)],
)
async def test_a_flat_history_only_flags_a_genuine_jump(
    books: Books, amount: str, flagged: bool
) -> None:
    """Five invoices of exactly 70,000 give SD = 0, so "mean + 3 SD" is just "above 70,000".
    The average-multiple term is what stops 70,001 and 100,000 flagging (D-055 #1)."""
    await history(books, ["70000"] * 5)
    candidate = await sale(books, START + timedelta(days=10), amount)
    found = await scan(books, candidate)
    assert [f.rule_triggered for f in found] == (
        [AnomalyRule.UNUSUALLY_LARGE_SD] if flagged else []
    )


@pytest.mark.req("FR-3.2")
async def test_a_near_flat_history_does_not_flag_a_small_step(books: Books) -> None:
    """Four 70,000 and one 70,010 give SD about 4.5, so mean + 3 SD is only 70,015 - a 70,050
    invoice clears it. The average-multiple term is what makes this sane."""
    await history(books, ["70000", "70000", "70000", "70000", "70010"])
    candidate = await sale(books, START + timedelta(days=10), "70050")
    assert await scan(books, candidate) == []


@pytest.mark.req("FR-3.2")
@pytest.mark.parametrize(("amount", "flagged"), [("350000", False), ("400000", True)])
async def test_where_amounts_vary_the_sd_term_stays_the_stricter_one(
    books: Books, amount: str, flagged: bool
) -> None:
    """Priors 50k..250k: mean 150,000, SD about 79,058, so mean + 3 SD is about 387,173 while
    twice the mean is only 300,000. 350,000 clears the scale term but not the SD term, so the
    extra condition has changed nothing for a party whose amounts genuinely vary."""
    await history(books, ["50000", "100000", "150000", "200000", "250000"])
    candidate = await sale(books, START + timedelta(days=10), amount)
    assert bool(await scan(books, candidate)) is flagged


@pytest.mark.req("D-015")
@pytest.mark.parametrize(("priors", "flagged"), [(4, False), (5, True)])
async def test_the_rule_needs_a_minimum_number_of_prior_transactions(
    books: Books, priors: int, flagged: bool
) -> None:
    """D-015: mean + 3 SD means little with only a handful of earlier transactions."""
    await history(books, ["70000"] * priors)
    candidate = await sale(books, START + timedelta(days=10), "450000")
    assert bool(await scan(books, candidate)) is flagged


@pytest.mark.req("AC-56")
async def test_the_srs_worked_example(books: Books) -> None:
    """SRS 12.3: transaction 4,50,000; average 70,000; previous maximum 1,20,000;
    deviation +543%."""
    await history(books, ["70000", "70000", "70000", "70000", "120000"])
    candidate = await sale(books, START + timedelta(days=10), "450000")
    (flag,) = await scan(books, candidate)
    assert flag.rule_triggered == AnomalyRule.UNUSUALLY_LARGE_SD
    assert flag.transaction_amount == Decimal("450000")
    assert flag.historical_max == Decimal("120000")
    assert flag.historical_average == Decimal("80000")  # (70000 x 4 + 120000) / 5
    # (450000 - 80000) / 80000 x 100, exactly - no rounding, so no banker's-rounding surprise
    assert flag.deviation_percent == Decimal("462.500000")
    assert flag.explanation_status == ExplanationStatus.PENDING


@pytest.mark.req("AC-56")
async def test_the_srs_example_figures_exactly_when_the_average_is_seventy_thousand(
    books: Books,
) -> None:
    """With the SRS's own average of 70,000 the deviation is +543% to the nearest point."""
    await history(books, ["70000"] * 5)
    candidate = await sale(books, START + timedelta(days=10), "450000")
    (flag,) = await scan(books, candidate)
    assert flag.deviation_percent is not None
    assert round(flag.deviation_percent) == 543


async def test_the_max_multiplier_rule_is_inactive_until_it_is_configured(
    books: Books,
) -> None:
    """FR-3.2: default not set. These priors vary enough that the SD term does not fire, so
    without the multiplier nothing is flagged at all."""
    await history(books, ["50000", "100000", "150000", "200000", "250000"])
    candidate = await sale(books, START + timedelta(days=10), "350000")
    assert await scan(books, candidate) == []
    await books.setting("anomaly.max_multiplier", "1.2", SettingDataType.DECIMAL)
    (flag,) = await scan(books, candidate)
    assert flag.rule_triggered == AnomalyRule.UNUSUALLY_LARGE_MULTIPLE


# --- FR-3.3: the same base voucher type (D-055 #2) ------------------------------------------


@pytest.mark.req("FR-3.3")
async def test_a_sale_and_its_matching_receipt_are_not_a_duplicate(books: Books) -> None:
    """The rule as the SRS words it - same party, same amount, within 3 days - flags the most
    ordinary pattern in accounting. Requiring the same base voucher type removes it (D-055 #2)."""
    invoice = await sale(books, START, "25000")
    payment = await receipt(books, START + timedelta(days=2), "25000")
    assert await scan(books, invoice, payment) == []


@pytest.mark.req("AC-57")
async def test_two_sales_of_the_same_amount_within_the_window_are_flagged(books: Books) -> None:
    first = await sale(books, START, "25000")
    second = await sale(books, START + timedelta(days=2), "25000")
    (flag,) = await scan(books, first, second)
    assert flag.rule_triggered == AnomalyRule.POSSIBLE_DUPLICATE
    assert flag.voucher_id == second, "the later voucher carries the flag"
    assert flag.duplicate_of_voucher_id == first, "and references the earlier one (AC-57)"
    assert flag.transaction_amount == Decimal("25000")


async def test_outside_the_window_two_identical_sales_are_not_a_duplicate(books: Books) -> None:
    first = await sale(books, START, "25000")
    second = await sale(books, START + timedelta(days=4), "25000")  # window is 3 days
    assert await scan(books, first, second) == []


async def test_a_different_party_is_not_a_duplicate(books: Books) -> None:
    first = await sale(books, START, "25000", party="Customer A")
    second = await sale(books, START + timedelta(days=1), "25000", party="Customer B")
    assert await scan(books, first, second) == []


# --- which vouchers count at all -------------------------------------------------------------


async def test_a_voucher_touching_two_parties_is_skipped(books: Books) -> None:
    """The table's key is (voucher_id, rule), so a second flag would be dropped silently, and
    "unusual for which party" has no single answer."""
    await history(books, ["70000"] * 5)
    both = await books.voucher(
        "Journal",
        START + timedelta(days=10),
        [("Customer A", "DEBIT", "450000"), ("Customer B", "CREDIT", "450000")],
    )
    assert await scan(books, both.voucher_id) == []


async def test_a_cancelled_voucher_is_not_flagged(books: Books) -> None:
    await history(books, ["70000"] * 5)
    v = await books.voucher(
        "Sales",
        START + timedelta(days=10),
        [("Customer A", "DEBIT", "450000"), ("Sales", "CREDIT", "450000")],
        status=VoucherStatus.CANCELLED,
    )
    assert await scan(books, v.voucher_id) == []


# --- D-055 #10: a flag follows its voucher ---------------------------------------------------


async def test_a_rescan_leaves_an_unchanged_flag_and_its_explanation_alone(
    books: Books,
) -> None:
    await history(books, ["70000"] * 5)
    candidate = await sale(books, START + timedelta(days=10), "450000")
    (flag,) = await scan(books, candidate)
    flag.explanation_status = ExplanationStatus.AVAILABLE
    flag.explanation_text = "An explanation worth keeping."
    await books.session.flush()
    (again,) = await scan(books, candidate)
    assert again.id == flag.id, "idempotent on (voucher_id, rule)"
    assert again.explanation_status == ExplanationStatus.AVAILABLE
    assert again.explanation_text == "An explanation worth keeping."


async def test_a_modified_voucher_gets_fresh_evidence_and_loses_its_explanation(
    books: Books,
) -> None:
    """D-055 #10: stale evidence and a stale explanation are worse than none."""
    await history(books, ["70000"] * 5)
    candidate = await sale(books, START + timedelta(days=10), "450000")
    (flag,) = await scan(books, candidate)
    flag.explanation_status = ExplanationStatus.AVAILABLE
    flag.explanation_text = "About 4,50,000."
    await books.session.flush()

    rows = await books.session.execute(
        select(VoucherEntry).where(VoucherEntry.voucher_id == candidate)
    )
    for entry in rows.scalars():
        entry.amount_absolute = Decimal("900000")
        entry.amount_signed = Decimal("900000") if entry.is_debit else Decimal("-900000")
    await books.session.flush()

    (again,) = await scan(books, candidate)
    assert again.transaction_amount == Decimal("900000")
    assert again.explanation_status == ExplanationStatus.PENDING
    assert again.explanation_text is None


async def test_a_flag_that_stops_triggering_is_cleared_not_deleted(books: Books) -> None:
    """Keeping the row is what preserves the audit trail for a reviewed flag, and lets a
    re-trigger simply un-clear it."""
    first = await sale(books, START, "25000")
    second = await sale(books, START + timedelta(days=2), "25000")
    (flag,) = await scan(books, first, second)
    flag_id = flag.id

    # The earlier voucher is cancelled, so the pair is no longer a duplicate.
    earlier = await books.session.get(Voucher, first)
    assert earlier is not None
    earlier.status = VoucherStatus.CANCELLED
    await books.session.flush()

    assert await scan(books, first, second) == [], "it leaves the list"
    kept = await books.session.get(AnomalyFlag, flag_id)
    assert kept is not None, "but the row survives for the audit trail"
    assert kept.cleared_at == NOW

    # And re-instating the voucher un-clears it rather than inserting a second row.
    earlier.status = VoucherStatus.ACTIVE
    await books.session.flush()
    (again,) = await scan(books, first, second)
    assert again.id == flag_id
    assert again.cleared_at is None
