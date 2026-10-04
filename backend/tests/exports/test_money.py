"""app/exports/money.py against the fixture the frontend's own test reads, so the two
formatters cannot drift (D-053 #6, #7)."""

import json
from decimal import Decimal
from pathlib import Path

import pytest

from app.exports.money import csv_amount, format_money, format_quantity

FIXTURE = json.loads(
    (Path(__file__).resolve().parents[3] / "fixtures" / "money-formatting.json").read_text(
        encoding="utf-8"
    )
)
CASES = [(c["value"], c["money"], c["csv"]) for c in FIXTURE["cases"]]


@pytest.mark.req("EXP-1.1")
@pytest.mark.parametrize(("value", "money", "csv"), CASES)
def test_the_shared_fixture_holds_for_python(value: str, money: str, csv: str) -> None:
    assert format_money(value) == money
    assert csv_amount(value) == csv


@pytest.mark.parametrize(("value", "money", "csv"), CASES)
def test_a_decimal_formats_like_its_string(value: str, money: str, csv: str) -> None:
    # Figures arrive from the database as Decimal, from a query string as text: same answer.
    assert format_money(Decimal(value.strip())) == money


@pytest.mark.parametrize("value", FIXTURE["refused"])
def test_anything_that_is_not_a_decimal_is_refused(value: str) -> None:
    # A malformed amount is a bug to see, never a figure to guess.
    for fn in (format_money, csv_amount, format_quantity):
        with pytest.raises(ValueError, match="not a decimal amount"):
            fn(value)


def test_an_unavailable_figure_is_empty_never_zero() -> None:
    # ACC-9.6 / D-045 #3: a ledger with no opening has no balance, and "0" would be a lie.
    assert csv_amount(None) == ""
    assert format_quantity(None) == ""


@pytest.mark.parametrize(
    ("value", "shown"),
    [("400.000000", "400"), ("2.500", "2.5"), ("2.000", "2"), ("0", "0"), ("100.10", "100.1")],
)
def test_quantities_are_trimmed_as_text(value: str, shown: str) -> None:
    assert format_quantity(value) == shown


def test_no_float_is_ever_involved() -> None:
    # 2**53 + 1 and a 25-digit amount survive; a float would not.
    assert format_money("9007199254740993") == "₹9,00,71,99,25,47,40,993.00"
    assert csv_amount("0.30000000000000004") == "0.30000000000000004"
