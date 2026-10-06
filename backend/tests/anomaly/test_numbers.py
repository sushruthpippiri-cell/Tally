"""FR-3.6, both directions. A one-sided test would let an over-strict checker through, and an
over-strict checker would discard every explanation and look like "the feature does not work"."""

import pytest

from app.anomaly import numbers, redact

EVIDENCE = {
    "rule": redact.RULE_LABELS["UNUSUALLY_LARGE_SD"],
    "currency": "INR",
    "party": redact.PARTY,
    "voucher": redact.VOUCHER,
    "transaction_amount": "450000.0000",
    "historical_average": "70000.0000",
    "historical_maximum": "120000.0000",
    "deviation_percent": "542.857143",
}


@pytest.mark.req("FR-3.6")
@pytest.mark.parametrize(
    "explanation",
    [
        # The figures as a person writes them: Indian grouping, a rupee sign, a rounded percent.
        "Party A was invoiced ₹4,50,000, against an average of ₹70,000 and a previous high of "
        "₹1,20,000 — about 543% above average.",
        # Exact forms, as the evidence holds them.
        "Amount 450000.0000, average 70000.0000, maximum 120000.0000, deviation 542.857143%.",
        # Two decimal places on the percentage.
        "This is 542.86% above the average of ₹70,000.",
        # No figures at all is always safe.
        "This invoice is far larger than this party's usual amounts.",
        # Nought is written plainly.
        "Voucher A for ₹4,50,000.00 is the largest so far.",
    ],
)
def test_a_good_explanation_passes(explanation: str) -> None:
    assert numbers.invented(explanation, EVIDENCE) == []


@pytest.mark.req("FR-3.6")
@pytest.mark.parametrize(
    ("explanation", "caught"),
    [
        # The realistic failure: a figure nobody supplied.
        ("The party usually invoices about ₹2,00,000.", ["200000"]),
        # A ratio the model worked out for itself - FR-3.6 says it is never asked to calculate.
        ("At ₹4,50,000 this is 6.4 times the average of ₹70,000.", ["6.4"]),
        # A difference, likewise computed.
        ("That is ₹3,80,000 more than usual.", ["380000"]),
        # The rule's own parameter, which is deliberately not in the evidence: the prompt tells
        # the model not to mention thresholds, and if it does the explanation is discarded.
        ("It exceeds the mean by more than 3 standard deviations.", ["3"]),
        # A plausible-looking but wrong restatement of a figure that IS in the evidence.
        ("The average is ₹70,500.", ["70500"]),
    ],
)
def test_an_invented_number_is_caught(explanation: str, caught: list[str]) -> None:
    assert numbers.invented(explanation, EVIDENCE) == caught


@pytest.mark.req("FR-3.6")
def test_a_duplicate_explanation_naming_both_vouchers_passes() -> None:
    """D-055 #8: the placeholders carry no digits, so naming both vouchers cannot trip the
    check. With "Voucher 1" and "Voucher 2" this explanation would have been discarded."""
    evidence = {
        "rule": redact.RULE_LABELS["POSSIBLE_DUPLICATE"],
        "currency": "INR",
        "party": redact.PARTY,
        "voucher": redact.VOUCHER,
        "other_voucher": redact.OTHER_VOUCHER,
        "transaction_amount": "25000.0000",
    }
    explanation = (
        "Voucher A and Voucher B both record ₹25,000 for Party A with the same voucher type, "
        "so one may have been entered twice."
    )
    assert numbers.invented(explanation, evidence) == []


def test_every_figure_in_the_evidence_is_permitted_in_its_own_exact_form() -> None:
    permitted = numbers.allowed(EVIDENCE)
    for figure in ("450000.0000", "70000.0000", "120000.0000", "542.857143"):
        assert figure in permitted


def test_a_percentage_may_be_rounded_but_not_changed() -> None:
    assert numbers.invented("543%", EVIDENCE) == []
    assert numbers.invented("542.9%", EVIDENCE) == []
    assert numbers.invented("544%", EVIDENCE) == ["544"]
