"""Analytics responses (P8.8). Money is Decimal, which Pydantic writes as a JSON string."""

import uuid
from datetime import date
from decimal import Decimal
from typing import Any, Literal

from pydantic import BaseModel

from app.core.periods import Granularity


class FiltersApplied(BaseModel):
    date_from: date
    date_to: date
    granularity: Granularity
    group_by: str | None
    include_cancelled: bool
    include_missing: bool
    customer: uuid.UUID | None = None  # FR-4.3 (D-053 #1)
    product: uuid.UUID | None = None
    cost_centre: uuid.UUID | None = None
    by: list[str] = []  # D-053 #2, as sent: "<group_by option>:<key>"
    not_applicable: list[str] = []  # chosen filters this figure cannot be narrowed by


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
    label: str | None = None  # the product difference's one label (ACC-VAL-1)
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
    custom_fields: dict[str, Any] | None = None  # the voucher's mapped UDF values (DR-UDF-2)


class DrilldownOut(BaseModel):
    """FR-DD-5: the rows, across all pages, sum to `total` exactly."""

    metric: str
    filters_applied: FiltersApplied
    total: Decimal | None
    total_rows: int
    page: int
    page_size: int
    rows: list[DrillRow]


class LabelledAmount(BaseModel):
    label: str
    amount: Decimal | None


class RankedRow(BaseModel):
    rank: int
    id: uuid.UUID
    name: str
    amount: Decimal | None = None  # ranked by revenue
    quantity: Decimal | None = None  # ranked by quantity: always with its unit
    unit: str | None = None
    multiple_units: bool | None = None  # the item was sold in more than one unit (FR-STK-10)


class RankingOut(BaseModel):
    """A ranked list (TOPN-1.x). There is deliberately no total of the listed rows: a Top-N
    list is never presented as adding up to the reference total (TOPN-1.4)."""

    ranking: Literal["customers", "suppliers", "products"]
    rank_by: Literal["revenue", "quantity"]
    label: str  # "Top 10", or "All" for View All
    is_top_n: bool
    n: int | None
    total_count: int
    filters_applied: FiltersApplied
    company_timezone: str
    rows: list[RankedRow]
    unattributed: LabelledAmount | None  # customers and suppliers: shown apart, never ranked
    product_attributed: LabelledAmount | None  # products
    difference: LabelledAmount | None  # products: exactly one label (ACC-VAL-1)
    reference_total: LabelledAmount
    notes: list[str]
