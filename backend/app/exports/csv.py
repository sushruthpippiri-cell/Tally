"""CSV export (EXP-1.1, EXP-1.3-1.5; D-053 #6).

Written for Excel: UTF-8 with a BOM, amounts as the exact database decimal so a column adds up
to the summary line, and every text cell defused against formula injection - a Tally ledger may
well be named `=cmd|...`.

`render` is a generator, so the endpoint streams a large report instead of building it in
memory.
"""

import csv as _csv
import io
from collections.abc import AsyncIterator
from typing import Any

from app.exports.money import csv_amount, format_quantity
from app.exports.report import Report

BOM = "﻿"
# Excel and LibreOffice treat a cell starting with one of these as a formula.
_RISKY = ("=", "+", "-", "@", "\t", "\r")


def _text(value: Any) -> str:
    """A text cell, with a formula-injection guard. Names come from Tally, not from us."""
    if value is None:
        return ""
    text = str(value)
    return f"'{text}" if text.startswith(_RISKY) else text


def _cell(value: Any, kind: str) -> str:
    if kind in ("amount", "signed_amount"):
        return csv_amount(value)  # never prefixed: Excel must read it as a number
    if kind == "quantity":
        return format_quantity(value)
    if kind in ("date", "integer"):
        return "" if value is None else str(value)
    return _text(value)


class _Lines:
    """`csv.writer` over a buffer that is drained after every row."""

    def __init__(self) -> None:
        self._buffer = io.StringIO()
        self._writer = _csv.writer(self._buffer, lineterminator="\r\n")

    def row(self, *values: Any) -> str:
        self._writer.writerow(values)
        text = self._buffer.getvalue()
        self._buffer.seek(0)
        self._buffer.truncate(0)
        return text


async def render(report: Report) -> AsyncIterator[str]:
    """The header block, the summary figures, the notes, then the detail rows (EXP-1.1)."""
    out = _Lines()
    yield BOM + out.row("Report", _text(report.title))
    yield out.row("Company", _text(report.company_name))
    for label, value in report.meta:
        yield out.row(_text(label), _text(value))

    yield out.row()
    yield out.row("Summary")
    for line in report.summary:
        # EXP-1.4: on a sales export these are three separate lines.
        yield out.row(
            _text(line.label),
            _cell(line.amount, line.kind),
            line.direction or "",
            _text(line.note),
        )

    if report.notes:
        yield out.row()
        for note in report.notes:
            yield out.row("Note", _text(note))

    yield out.row()
    if report.total_rows is not None:
        yield out.row("Rows", str(report.total_rows))
    yield out.row(*(c.heading for c in report.columns))
    async for row in report.rows:
        yield out.row(*(_cell(row.get(c.key), c.kind) for c in report.columns))
