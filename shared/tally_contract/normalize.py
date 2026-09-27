"""The ONE place Tally's raw amounts and indicators become the normalized fields (ACC-DATA-2,
SRS 5.8). Analytics read only the normalized fields (ACC-DATA-1).

The debit/credit rule is a draft until GATE-G23 passes (ACC-DATA-3). When two indicators are
present they must agree; a disagreement fails the record instead of guessing.
Also here: the voucher balance check and the cancellation rule.
"""

from decimal import Decimal

from tally_contract import tally_constants as tc
from tally_contract.enums import AccountingDirection, AllocationType
from tally_contract.errors import ErrorCode, RecordRejected
from tally_contract.records import Amount, LedgerEntry
from tally_contract.values import parse_decimal


def to_amount(raw: str, deemed_positive: bool | None = None) -> Amount:
    """GATE-G23: a signed amount (negative = debit), or an amount with a Dr/Cr suffix, plus
    ISDEEMEDPOSITIVE (Yes = debit) where the field carries it."""
    value, suffix = parse_decimal(raw)
    if suffix is not None:
        is_debit = suffix == tc.DEBIT_SUFFIX
        if value < 0:
            raise ValueError(f"both a sign and {suffix} on {raw!r}")
    elif value != 0:
        is_debit = (value < 0) == tc.DEBIT_IS_NEGATIVE
    else:
        is_debit = bool(deemed_positive)  # zero: only the indicator can say
    if deemed_positive is not None and value != 0 and deemed_positive != is_debit:
        raise ValueError(f"debit/credit indicators disagree on {raw!r} (GATE-G23)")
    absolute = abs(value)
    return Amount(
        amount_raw=raw,
        is_debit=is_debit,
        amount_absolute=absolute,
        amount_signed=absolute if is_debit else -absolute,
        accounting_direction=AccountingDirection.DEBIT if is_debit else AccountingDirection.CREDIT,
    )


def allocation_type(raw: str) -> AllocationType:
    """GATE-G25: the exact exported values; anything else is UNSUPPORTED (AGE-BILL-1)."""
    return AllocationType(tc.BILL_TYPE_VALUES.get(raw.strip(), AllocationType.UNSUPPORTED))


def absolute(raw: str) -> Decimal:
    return abs(parse_decimal(raw)[0])


def check_balance(entries: list[LedgerEntry]) -> None:
    """SRS 16: a voucher whose signed entries do not sum to zero is rejected, never stored.
    Exact by default (GATE-G23 BALANCE_TOLERANCE = 0)."""
    total = sum((e.amount.amount_signed for e in entries), Decimal(0))
    if abs(total) > tc.BALANCE_TOLERANCE:
        raise RecordRejected(
            ErrorCode.DEBIT_CREDIT_IMBALANCE,
            f"debits and credits differ by {total} (entries must sum to zero)",
        )


def is_cancelled(raw: str | None) -> bool:
    """GATE-G9: cancelled only on an explicit Yes; missing or anything else is not cancelled."""
    return (raw or "").strip().lower() == tc.CANCELLED_YES.lower()
