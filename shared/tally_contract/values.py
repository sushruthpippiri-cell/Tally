"""Scalar values in our report fields. Anything unexpected raises ValueError, which fails that
one record; nothing is guessed."""

import re
from datetime import date, datetime
from decimal import Decimal, InvalidOperation

from tally_contract import tally_constants as tc

_NUMBER = re.compile(r"^\s*(-?\s*[\d,]*\.?\d+)\s*(Dr|Cr)?\.?\s*$", re.I)
_QUANTITY = re.compile(r"^\s*(-?[\d,]*\.?\d+)\s*([^\d\s=/][^=/]*?)?\s*(=.*)?$")


def text(value: str | None) -> str | None:
    """Trimmed text; empty -> None."""
    if value is None:
        return None
    value = value.strip()
    return value or None


def parse_int(value: str | None) -> int:
    raw = text(value)
    if raw is None or not re.fullmatch(r"-?\d+", raw.replace(",", "")):
        raise ValueError(f"not an integer: {value!r}")
    return int(raw.replace(",", ""))


def parse_date(value: str | None) -> date:
    raw = text(value)
    try:
        return datetime.strptime(raw or "", tc.RESPONSE_DATE_FORMAT).date()
    except ValueError:
        raise ValueError(f"not a {tc.RESPONSE_DATE_FORMAT} date: {value!r}") from None


def parse_optional_date(value: str | None) -> date | None:
    return None if text(value) is None else parse_date(value)


def parse_bool(value: str | None) -> bool | None:
    raw = text(value)
    if raw is None:
        return None
    if raw.lower() == tc.YES.lower():
        return True
    if raw.lower() == tc.NO.lower():
        return False
    raise ValueError(f"not {tc.YES}/{tc.NO}: {value!r}")


def parse_decimal(value: str | None) -> tuple[Decimal, str | None]:
    """(number, "Dr"/"Cr"/None). Thousands separators and surrounding space are tolerated."""
    raw = text(value)
    match = _NUMBER.match(raw or "")
    if not match:
        raise ValueError(f"not a number: {value!r}")
    try:
        number = Decimal(match.group(1).replace(",", "").replace(" ", ""))
    except InvalidOperation:
        raise ValueError(f"not a number: {value!r}") from None
    suffix = match.group(2)
    return number, (suffix.capitalize() if suffix else None)


def parse_plain_decimal(value: str | None) -> Decimal | None:
    """A number with no Dr/Cr; empty -> None."""
    if text(value) is None:
        return None
    number, suffix = parse_decimal(value)
    if suffix:
        raise ValueError(f"unexpected {suffix} on {value!r}")
    return number


def parse_quantity(value: str | None) -> tuple[Decimal | None, str | None]:
    """GATE-G27: "12 Nos" -> (12, "Nos"); "2 Box = 24 Nos" -> (2, "Box"); empty -> (None, None)."""
    raw = text(value)
    if raw is None:
        return None, None
    match = _QUANTITY.match(raw)
    if not match:
        raise ValueError(f"not a quantity: {value!r}")
    unit = text(match.group(2))
    return Decimal(match.group(1).replace(",", "")), unit


def parse_rate(value: str | None) -> tuple[Decimal | None, str | None]:
    """GATE-G27: "100.00/Nos" -> (100.00, "Nos")."""
    raw = text(value)
    if raw is None:
        return None, None
    number, _, unit = raw.partition("/")
    return parse_decimal(number)[0], text(unit)
