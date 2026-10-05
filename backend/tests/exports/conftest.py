"""Helpers for the export tests."""

import csv as _csv
from collections.abc import AsyncIterator, Iterable
from typing import Any

from app.exports import csv as csv_export
from app.exports.report import Report


async def rows_of(items: Iterable[dict[str, Any]]) -> AsyncIterator[dict[str, Any]]:
    for item in items:
        yield item


async def to_csv(report: Report) -> str:
    return "".join([chunk async for chunk in csv_export.render(report)])


def parse(text: str) -> list[list[str]]:
    """The rendered CSV as the rows a spreadsheet would read (BOM stripped)."""
    return list(_csv.reader(text.lstrip("﻿").splitlines()))


def table(text: str, headings: list[str]) -> list[dict[str, str]]:
    """The detail rows under `headings`, as dicts."""
    rows = parse(text)
    start = next(i for i, r in enumerate(rows) if r == headings) + 1
    return [dict(zip(headings, r, strict=True)) for r in rows[start:] if r]
