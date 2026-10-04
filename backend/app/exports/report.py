"""The one shape every export renders (EXP-1.1).

An adapter in `reports.py` fills a `Report` from the same service calls the screen makes, and
`csv.py` / `pdf.py` render it. Nothing here computes a figure: an amount is whatever the
analytics layer returned (EXP-1.3, CLAUDE.md rule 9).
"""

from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any, Literal

# How a cell is written, not what it means: `amount` is a figure, `signed_amount` a balance's
# Dr-positive figure, `quantity` a quantity (never summed across units, FR-STK-10).
CellKind = Literal["text", "amount", "signed_amount", "quantity", "date", "integer"]


@dataclass(frozen=True)
class Column:
    key: str
    heading: str
    kind: CellKind = "text"


@dataclass(frozen=True)
class SummaryLine:
    """A figure of the report, as the screen shows it beside the title (EXP-1.1, EXP-1.4)."""

    label: str
    amount: Decimal | None
    direction: str | None = None  # "Dr" / "Cr" on a balance
    note: str | None = None  # e.g. why it is unavailable (ACC-9.6)


@dataclass(frozen=True)
class Bar:
    label: str
    amount: Decimal | None


@dataclass(frozen=True)
class Chart:
    """A chart the screen draws (EXP-1.2). No value axis: the labels carry the figures, exactly
    as `components/Chart.tsx` does (D-053 #5)."""

    title: str
    bars: list[Bar]


@dataclass(frozen=True)
class Report:
    title: str
    company_name: str
    company_timezone: str
    meta: list[tuple[str, str]]  # date range, each active filter, generated at (EXP-1.1)
    summary: list[SummaryLine]
    columns: list[Column]
    rows: AsyncIterator[dict[str, Any]]
    total_rows: int | None = None
    notes: list[str] = field(default_factory=list)
    charts: list[Chart] = field(default_factory=list)
    slug: str = "report"  # the download's file name stem


def humanize(key: str) -> str:
    """A column key as a heading: "stock_item_name" -> "Stock item name" (as `format.ts` does)."""
    words = key.replace("_", " ").replace("-", " ")
    return words[:1].upper() + words[1:]
