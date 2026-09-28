"""Analytics responses (P8.8). Money is Decimal, which Pydantic writes as a JSON string."""

import uuid
from datetime import date
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel

from app.core.periods import Granularity


class FiltersApplied(BaseModel):
    date_from: date
    date_to: date
    granularity: Granularity
    group_by: str | None
    include_cancelled: bool
    include_missing: bool


class Figure(BaseModel):
    """A flow is signed as the metric defines it. A balance is its size with Dr/Cr. When a
    balance is unavailable (a ledger with no opening, ACC-9.6) `amount` is null and the
    ledgers are named (D-045 #3)."""

    amount: Decimal | None
    direction: Literal["Dr", "Cr"] | None = None
    available: bool = True
    unavailable_count: int = 0
    unavailable_ledgers: list[str] = []


class SeriesPoint(BaseModel):
    period: str
    start: date
    amount: Decimal | None


class BreakdownRow(BaseModel):
    key: str | None
    label: str | None
    figure: Figure


class MetricOut(BaseModel):
    metric: str
    filters_applied: FiltersApplied
    company_timezone: str
    summary: Figure
    series: list[SeriesPoint]
    breakdown: list[BreakdownRow]
    notes: list[str]


class DrillRow(BaseModel):
    voucher_id: uuid.UUID | None  # null on a balance's opening row
    voucher_date: date | None
    voucher_number: str | None
    voucher_type_name: str | None
    base_voucher_type: str | None
    ledger_id: uuid.UUID | None  # null on a cash-flow row (one per voucher)
    ledger_name: str | None
    amount: Decimal | None
    dimensions: dict[str, str | None]  # the metric's own columns (group, cost centre, flow...)


class DrilldownOut(BaseModel):
    """FR-DD-5: the rows, across all pages, sum to `total` exactly."""

    metric: str
    filters_applied: FiltersApplied
    total: Decimal | None
    total_rows: int
    page: int
    page_size: int
    rows: list[DrillRow]
