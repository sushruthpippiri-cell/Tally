"""P10.4: the SRS 9.2 tolerance rule on Decimals, with every SRS 9.3 worked example."""

from decimal import Decimal

import pytest

from app.reconciliation.tolerance import Comparison, evaluate

D = Decimal
MONEY = (D("1.00"), D("0.01"))  # ₹1 absolute, 0.01 %
QUANTITY = (D("0"), D("0.5"))  # 0 units, 0.5 %

# SRS 9.3, row by row: tally, local, absolute difference, percentage difference, result.
WORKED_EXAMPLES = [
    ("100000", "100000.50", "0.50", "0.0005", "PASS"),  # within the absolute tolerance
    ("100000", "100010", "10", "0.01", "PASS"),  # AC-42: equal to the percentage tolerance
    ("100000", "100012", "12", "0.012", "FAIL"),  # AC-41: both exceeded
    ("100000", "100500", "500", "0.5", "FAIL"),  # both exceeded
    ("0", "0", "0", None, "PASS"),  # AC-43: zero matches zero
    ("0", "50", "50", None, "FAIL"),  # AC-43: non-zero against zero
]


@pytest.mark.req("AC-41", "AC-42", "AC-43")
@pytest.mark.req_partial("TEST-2.1")  # the reconciliation examples; the ACC rules: P8, P9
@pytest.mark.parametrize(("tally", "local", "absolute", "percentage", "result"), WORKED_EXAMPLES)
def test_the_srs_worked_examples(
    tally: str, local: str, absolute: str, percentage: str | None, result: str
) -> None:
    got = evaluate(D(tally), D(local), *MONEY)
    assert got == Comparison(
        absolute_difference=D(absolute),
        percentage_difference=None if percentage is None else D(percentage),
        result=result,
    )


@pytest.mark.req("AC-44")
def test_quantity_tolerance_100_units_against_98_fails() -> None:
    """2 units is 2 %: over 0 units and over 0.5 %."""
    got = evaluate(D("100"), D("98"), *QUANTITY)
    assert (got.absolute_difference, got.percentage_difference, got.result) == (
        D("2"),
        D("2"),
        "FAIL",
    )


def test_quantity_within_half_a_percent_passes() -> None:
    assert evaluate(D("1000"), D("995"), *QUANTITY).result == "PASS"  # 0.5 %, inclusive
    assert evaluate(D("1000"), D("994"), *QUANTITY).result == "FAIL"


def test_a_credit_balance_is_measured_against_its_size() -> None:
    """Ledger balances are signed (Dr +): a Cr ₹100,000 balance off by ₹10 is 0.01 %."""
    got = evaluate(D("-100000"), D("-100010"), *MONEY)
    assert (got.absolute_difference, got.percentage_difference, got.result) == (
        D("10"),
        D("0.01"),
        "PASS",
    )
    assert evaluate(D("-100000"), D("100000"), *MONEY).result == "FAIL"  # wrong side


def test_zero_in_tally_passes_only_on_an_exact_zero() -> None:
    """Even a difference inside the absolute tolerance fails against a Tally zero (SRS 9.2)."""
    assert evaluate(D("0"), D("0.0001"), *MONEY).result == "FAIL"
    assert evaluate(D("0"), D("-0.00"), *MONEY).result == "PASS"


def test_the_boundaries_are_inclusive_and_nothing_is_rounded_first() -> None:
    assert evaluate(D("50"), D("51.00"), *MONEY).result == "PASS"  # ₹1 exactly
    assert evaluate(D("50"), D("51.0001"), *MONEY).result == "FAIL"  # 2 % and over ₹1
    assert evaluate(D("100000"), D("100010.0001"), *MONEY).result == "FAIL"
