"""Stock movement (SRS 11, D-050). Money and quantities go out as strings."""

import uuid
from datetime import date
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel

MovementClass = Literal[
    "FAST", "NORMAL", "SLOW", "DEAD", "NEVER_SOLD", "STOCK_UNKNOWN", "NOT_CLASSIFIED"
]


class ClassCount(BaseModel):
    key: MovementClass
    label: str  # NEVER_SOLD reads "No sale since <books_from>" (D-050 #6)
    count: int


class UnitQuantity(BaseModel):
    unit: str | None
    quantity: Decimal


class StockItemOut(BaseModel):
    stock_item_id: uuid.UUID
    name: str
    movement_class: MovementClass
    label: str
    note: str | None  # "no sale in selected period" (the D-009 gap)
    stock: Decimal | None  # None: no snapshot, stock unknown (never zero)
    stock_unit: str | None
    snapshot_date: date | None  # the snapshot this classification used (FR-STK-16)
    last_sale_date: date | None
    days_since_last_sale: int | None
    period_sales_value: Decimal
    period_quantities: list[UnitQuantity]  # per unit, never added across units (FR-STK-10)
    multi_unit: bool


class SnapshotDates(BaseModel):
    oldest: date | None
    newest: date | None


class StockOut(BaseModel):
    today: date  # in the company's time zone
    books_from: date | None  # the synced history starts here (D-050 #6)
    period_days: int
    period_from: date
    period_to: date
    basis: Literal["value"] = "value"  # FR-STK-20
    fast_percentile: int
    fast_threshold: Decimal | None  # None when nothing was sold in the period
    classes: list[ClassCount]
    total_items: int  # listed items, after the class filter
    items: list[StockItemOut]
    snapshot_dates: SnapshotDates
    warnings: list[str]  # e.g. a stale snapshot (D-050 #10)
    notes: list[str]
    limitations: list[str]  # FR-STK-10
    unverified_gates: list[str]  # G18, G27 while not PASSED
