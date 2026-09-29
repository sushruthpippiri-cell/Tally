"""Reconciliation API (SRS 9, REC-1.2, D-048)."""

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict

Overall = Literal["PASS", "FAIL", "INCOMPLETE"]


class ReconciliationRunRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    agent_id: uuid.UUID | None = None  # optional: routed like Sync Now (RTE-1.1, D-036 #5)


class ReconciliationRow(BaseModel):
    """REC-1.2: the Tally value, the local value, both differences and the result."""

    # SALES_CREDITS | PURCHASE_DEBITS | RECEIPTS | PAYMENTS | LEDGER_BALANCE | STOCK_QTY
    metric: str
    entity_id: uuid.UUID | None  # the ledger or stock item; None for the four totals
    entity_name: str | None
    period_start: date
    period_end: date
    tally_value: Decimal
    local_value: Decimal
    absolute_difference: Decimal
    percentage_difference: Decimal | None  # None when Tally's value is 0
    result: Literal["PASS", "FAIL"]


class NotCompared(BaseModel):
    metric: str
    entity_guid: str
    name: str | None
    reason: str
    fails: bool  # true: it makes the run FAIL (see docs/reconciliation-basis.md)


class RunOverview(BaseModel):
    sync_run_id: uuid.UUID
    run_at: datetime
    as_of: date
    overall: Overall
    compared: int
    failed: int


class ReconciliationOut(BaseModel):
    run: RunOverview | None  # None: no reconciliation has been compared yet
    rows: list[ReconciliationRow]  # failures first
    total_rows: int  # with the `only_failures` filter applied
    not_compared: list[NotCompared]
    unverified_gates: list[str]  # the Tally facts behind these figures not yet verified
    history: list[RunOverview]  # the latest runs, newest first


class ReconciliationStatus(BaseModel):
    """FR-4.1: the home view's reconciliation status."""

    sync_run_id: uuid.UUID
    run_at: datetime
    overall: Overall
