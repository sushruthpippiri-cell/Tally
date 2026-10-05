"""FR-3.6: Claude is asked to explain the evidence, never to calculate. This checks it.

Every number in the explanation must be one the evidence already contained. The model writes
money the way a person does — `₹4,50,000` where the evidence holds `450000.0000`, `+543%` where
it holds `542.857143` — so both sides are normalised and each evidence figure is allowed in its
rounded forms as well as its exact one.

A number outside that set means the model computed something, and the explanation is discarded
(D-055 #12: with the reason recorded, so the discards are counted rather than silent). The check
is deliberately strict in both directions: an invented `₹2,00,000` is rejected, and so is a ratio
the model worked out for itself like `6.4 times`. `UNAVAILABLE` is a first-class state, so being
strict degrades gracefully — but it is only safe because a *good* explanation is tested too.
"""

import re
from decimal import Decimal, InvalidOperation
from typing import Any

#: Digit runs, with an optional decimal part. Grouping separators are removed first.
_NUMBER = re.compile(r"\d+(?:\.\d+)?")
#: Everything a person writes around a figure that is not part of the figure.
_NOISE = str.maketrans({"₹": None, ",": None, "+": None, "%": None, " ": None, " ": None})


def _variants(text: str) -> set[str]:
    """One evidence figure, in every form an explanation may legitimately write it."""
    try:
        value = Decimal(text)
    except (InvalidOperation, ValueError):
        return set()
    out = {text, format(value, "f")}
    normalised = format(value.normalize(), "f")
    out.add(normalised)
    if normalised.startswith("-"):
        out.add(normalised[1:])
    for places in (0, 1, 2):
        rounded = round(value, places)
        out.add(format(rounded, "f"))
        out.add(format(rounded.normalize(), "f"))
    return {v.lstrip("-") for v in out}


def allowed(evidence: dict[str, Any]) -> set[str]:
    """Every number the explanation may use: the evidence's own figures and their rounded forms.

    Nothing else is in the prompt, so nothing else can legitimately appear in the answer.
    """
    found: set[str] = set()
    for value in evidence.values():
        if isinstance(value, (int, float)):  # noqa: UP038 - isinstance tuple is clearer here
            found |= _variants(str(value))
        elif isinstance(value, str):
            # A field like the rule label is text; only the figures parse as numbers.
            found |= _variants(value.translate(_NOISE))
    return found


def invented(explanation: str, evidence: dict[str, Any]) -> list[str]:
    """The numbers in `explanation` that the evidence does not contain, in the order written."""
    permitted = allowed(evidence)
    out: list[str] = []
    for match in _NUMBER.finditer(explanation.translate(_NOISE)):
        written = match.group(0)
        if written in permitted:
            continue
        # "450000.00" against an evidence "450000.0000", and the reverse.
        if _variants(written) & permitted:
            continue
        out.append(written)
    return out
