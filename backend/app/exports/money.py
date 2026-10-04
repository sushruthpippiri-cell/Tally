"""The one Python money formatter, for exports only (D-053 #6, #7).

`format_money` is a port of `frontend/src/lib/format.ts`'s `formatMoney`: two places, half away
from zero, grouped the Indian way, with the rupee sign. It is what the PDF shows, so the owner
reads the same digits on paper as on screen. `csv_amount` is the other form: the exact database
decimal, never rounded, so Excel can add a column up to the summary line.

The two implementations are held together by `fixtures/money-formatting.json`, which this
module's test and the frontend's both read.
"""

import re
from decimal import ROUND_HALF_UP, Decimal, localcontext

# The same shape `format.ts` accepts: optional sign, digits, optional fraction, optional
# exponent. Nothing else is money - a thousands separator, a currency sign or an underscore is a
# bug to see, never a figure to guess.
_DECIMAL = re.compile(r"([+-])?(\d*)(?:\.(\d*))?(?:[eE]([+-]?\d+))?")
_PAISE = Decimal("0.01")
RUPEE = "₹"


def _parse(value: Decimal | str) -> Decimal:
    text = str(value).strip()
    match = _DECIMAL.fullmatch(text)
    if match is None or not (match.group(2) or match.group(3)):
        raise ValueError(f"not a decimal amount: {text!r}")
    return Decimal(text)


def _group_indian(whole: str) -> str:
    """Turns "1234567" -> "12,34,567": the last three digits, then groups of two."""
    if len(whole) <= 3:
        return whole
    head, tail = whole[:-3], whole[-3:]
    pairs = [head[:1]] if len(head) % 2 else []
    pairs += [head[i : i + 2] for i in range(len(head) % 2, len(head), 2)]
    return f"{','.join(pairs)},{tail}"


def format_money(value: Decimal | str) -> str:
    """Formats "12345678.9000" as "₹1,23,45,678.90", "-1.005" as "-₹1.01", "-0.004" as "₹0.00"."""
    amount = _parse(value)
    with localcontext() as ctx:
        ctx.prec = len(amount.as_tuple().digits) + 10
        rounded = amount.quantize(_PAISE, rounding=ROUND_HALF_UP)
    whole, _, paise = f"{abs(rounded):f}".partition(".")
    sign = "-" if rounded < 0 else ""  # a rounded-to-zero amount is never "-₹0.00"
    return f"{sign}{RUPEE}{_group_indian(whole)}.{paise}"


def csv_amount(value: Decimal | str | None) -> str:
    """The exact decimal for a spreadsheet: no sign on zero, no grouping, no rupee sign, at
    least two decimal places and no trailing zeros past them. An unavailable figure is empty,
    never "0" (ACC-9.6)."""
    if value is None:
        return ""
    amount = _parse(value)
    whole, _, fraction = f"{amount:f}".partition(".")
    if not amount:
        whole = whole.lstrip("-")
    return f"{whole}.{fraction.rstrip('0').ljust(2, '0')}"


def format_quantity(value: Decimal | str | None) -> str:
    """A quantity or rate without trailing zeros ("400.000000" -> "400"), trimmed as text."""
    if value is None:
        return ""
    text = f"{_parse(value):f}"
    return re.sub(r"\.?0+$", "", text) if "." in text else text
