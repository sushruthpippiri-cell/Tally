"""The reconciliation tolerance rule (SRS 9.2), on Decimals only.

absolute_difference   = |tally − local|
percentage_difference = absolute_difference / |tally| × 100      (tally ≠ 0)
tally = 0:  PASS only when local = 0
otherwise:  PASS when absolute ≤ its tolerance OR percentage ≤ its tolerance (inclusive)
"""

from dataclasses import dataclass
from decimal import Decimal
from typing import Literal

Result = Literal["PASS", "FAIL"]


@dataclass(frozen=True)
class Comparison:
    absolute_difference: Decimal
    percentage_difference: Decimal | None  # None when Tally's value is 0
    result: Result


def evaluate(
    tally: Decimal, local: Decimal, absolute_tolerance: Decimal, percentage_tolerance: Decimal
) -> Comparison:
    absolute = abs(tally - local)
    if tally == 0:
        return Comparison(absolute, None, "PASS" if local == 0 else "FAIL")
    percentage = absolute / abs(tally) * 100
    ok = absolute <= absolute_tolerance or percentage <= percentage_tolerance
    return Comparison(absolute, percentage, "PASS" if ok else "FAIL")
