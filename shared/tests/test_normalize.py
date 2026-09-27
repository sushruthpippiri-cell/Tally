"""P4.5: the one normalisation module (ACC-DATA-2, SRS 5.8). The G23 rule is a draft until
live captures verify it (ACC-DATA-3)."""

import re
from decimal import Decimal
from pathlib import Path

import pytest

from tally_contract import normalize
from tally_contract.enums import AccountingDirection
from tally_contract.errors import ErrorCode, RecordRejected
from tally_contract.records import LedgerEntry

ROOT = Path(__file__).parents[2]
D, C = AccountingDirection.DEBIT, AccountingDirection.CREDIT


# A sale, a purchase, a receipt, a payment and tax lines, as Tally signs them (draft G23):
# negative = debit, ISDEEMEDPOSITIVE Yes = debit.
@pytest.mark.req("ACC-DATA-2")
@pytest.mark.req_partial("AC-34")  # "no analytics query reads amount_raw": P8
@pytest.mark.parametrize(
    ("case", "raw", "deemed_positive", "direction", "signed"),
    [
        ("sale: customer debited", "-1180.00", True, D, "1180.00"),
        ("sale: sales ledger credited", "1000.00", False, C, "-1000.00"),
        ("sale: output tax credited", "180.00", False, C, "-180.00"),
        ("purchase: purchases debited", "-500.00", True, D, "500.00"),
        ("purchase: input tax debited", "-90.00", True, D, "90.00"),
        ("purchase: supplier credited", "590.00", False, C, "-590.00"),
        ("receipt: bank debited", "-2000", True, D, "2000"),
        ("receipt: customer credited", "2000", False, C, "-2000"),
        ("payment: expense debited", "-750.50", True, D, "750.50"),
        ("payment: cash credited", "750.50", False, C, "-750.50"),
        ("opening: Dr suffix", "5,000.00 Dr", None, D, "5000.00"),
        ("opening: Cr suffix", "25000 Cr", None, C, "-25000"),
    ],
)
def test_debit_and_credit_by_ledger_kind(
    case: str, raw: str, deemed_positive: bool | None, direction: AccountingDirection, signed: str
) -> None:
    amount = normalize.to_amount(raw, deemed_positive)
    assert amount.accounting_direction == direction, case
    assert amount.is_debit == (direction == D)
    assert amount.amount_signed == Decimal(signed)
    assert amount.amount_absolute == abs(Decimal(signed)) >= 0
    assert amount.amount_raw == raw  # kept exactly, for audit only


@pytest.mark.parametrize(
    ("raw", "deemed_positive"),
    [("-100", False), ("100", True), ("-100 Dr", None), ("100 Dr", False)],
)
def test_contradictions_fail_the_record_instead_of_being_guessed(
    raw: str, deemed_positive: bool | None
) -> None:
    with pytest.raises(ValueError):
        normalize.to_amount(raw, deemed_positive)


def test_zero_takes_its_direction_from_the_indicator() -> None:
    assert normalize.to_amount("0", True).accounting_direction == D
    assert normalize.to_amount("0.00", False).amount_signed == 0


@pytest.mark.parametrize(
    "raw",
    [
        "$100.00",
        "₹1,180.00",
        "USD 100",
        "100 USD",
        "100.00 @ ₹83.20/$ = ₹8,320.00",
        "$100 = ₹8320",
        "100 Dollars",
        "1,00,000.00 (Foreign)",
        "12 Nos",
    ],
)
def test_amounts_not_fully_understood_are_rejected_never_partly_read(raw: str) -> None:
    """Multi-currency exports may carry symbols or a conversion; never take the leading number."""
    with pytest.raises(ValueError):
        normalize.to_amount(raw, True)


def _entry(raw: str, deemed_positive: bool, seq: int) -> LedgerEntry:
    return LedgerEntry(
        ledger_name=f"L{seq}", line_sequence=seq, amount=normalize.to_amount(raw, deemed_positive)
    )


def test_a_balanced_voucher_passes_exactly() -> None:
    normalize.check_balance(
        [_entry("-1180.00", True, 1), _entry("1000.00", False, 2), _entry("180.00", False, 3)]
    )
    normalize.check_balance([])  # a cancelled voucher may have no entries


@pytest.mark.parametrize("off", ["0.01", "0.001", "1"])
def test_even_a_paisa_of_imbalance_is_rejected(off: str) -> None:
    """GATE-G23: exact by default; Tally only saves balanced vouchers."""
    credit = str(Decimal("1000.00") - Decimal(off))
    with pytest.raises(RecordRejected) as caught:
        normalize.check_balance([_entry("-1000.00", True, 1), _entry(credit, False, 2)])
    assert caught.value.code == ErrorCode.DEBIT_CREDIT_IMBALANCE


@pytest.mark.parametrize(
    ("raw", "cancelled"),
    [
        ("Yes", True),
        ("yes", True),
        (" Yes ", True),
        ("No", False),
        ("", False),
        (None, False),
        ("Y", False),
        ("Cancelled", False),
    ],
)
def test_cancelled_only_on_an_explicit_yes(raw: str | None, cancelled: bool) -> None:
    """GATE-G9: the safe default is 'not cancelled'."""
    assert normalize.is_cancelled(raw) is cancelled


@pytest.mark.req("ACC-DATA-2")
def test_normalized_amounts_are_built_only_in_normalize() -> None:
    """ACC-DATA-2: the conversion lives in one module."""
    builders = []
    for folder in ("shared/tally_contract", "backend/app", "agent"):
        for path in (ROOT / folder).rglob("*.py"):
            if re.search(r"(?<!class )\bAmount\(", path.read_text(encoding="utf-8")):
                builders.append(path.relative_to(ROOT).as_posix())
    assert sorted(builders) == ["shared/tally_contract/normalize.py"]
