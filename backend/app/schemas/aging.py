"""Aging and payment behaviour (SRS 10, D-049). Money goes out as strings; nothing in a bucket
is ever negative: an over-settled bill is a credit, a positive amount marked as one."""

import uuid
from datetime import date
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel

from app.schemas.analytics import Figure

Side = Literal["receivable", "payable"]


class BucketLabel(BaseModel):
    key: str  # "0-30", ..., "NOT_YET_DUE", "NO_DUE_DATE"
    label: str  # "Overdue 0-30 days", "Not yet due", "Due date unavailable"


class AgingRow(BaseModel):
    """One party, or the side's total (ledger_id None)."""

    ledger_id: uuid.UUID | None
    ledger_name: str | None
    buckets: dict[str, Decimal]
    bucket_total: Decimal
    credit: Decimal  # over-settled bills, Cr (D-049 #1)
    unadjusted_advances: Decimal  # AGE-BILL-3
    on_account: Decimal  # "On-Account / Unallocated", AGE-BILL-3
    unmatched_settlements: Decimal  # D-049 #6
    net_exposure: Decimal  # every row of the party, signed toward the side (D-049 #6)


class NoBillDetails(BaseModel):
    """SRS 10.3: one balance, never bucketed."""

    ledger_id: uuid.UUID
    ledger_name: str
    balance: Figure
    note: str = "bill details not available"


class AgingOut(BaseModel):
    side: Side
    as_of: date
    company_timezone: str
    bucket_order: list[BucketLabel]
    total: AgingRow
    parties: list[AgingRow]
    no_bill_details: list[NoBillDetails]
    unverified_gates: list[str]  # G25, G31 while not PASSED (D-049 #8)


class BillOut(BaseModel):
    reference_name: str
    bill_date: date | None
    due_date: date | None
    days_overdue: int | None  # None when not yet due or no due date: never negative (AC-46)
    bucket: str  # a bucket key, or "CREDIT"
    outstanding: Decimal  # never negative; a credit is `is_credit`
    is_credit: bool
    unverified: bool  # a reused bill name (GATE-G31, D-049 #7)
    unverified_reason: str | None


class BillsOut(BaseModel):
    side: Side
    as_of: date
    ledger_id: uuid.UUID
    bills: list[BillOut]
    unverified_gates: list[str]


class AllocationOut(BaseModel):
    voucher_id: uuid.UUID | None  # None: an opening bill from the ledger master
    voucher_date: date | None
    voucher_number: str | None
    voucher_type_name: str
    allocation_type: str
    amount: Decimal  # signed toward the side: receivable debit +, payable credit +
    source: Literal["VOUCHER", "OPENING"]


class AllocationsOut(BaseModel):
    side: Side
    as_of: date
    ledger_id: uuid.UUID
    reference_name: str
    allocations: list[AllocationOut]
    unverified_gates: list[str]


class PaymentFigureOut(BaseModel):
    ledger_id: uuid.UUID | None  # None: all customers
    ledger_name: str | None
    settlements: int
    settled_amount: Decimal
    avg_days_to_pay: Decimal | None  # None when `insufficient_history` (FR-PAY-5)
    avg_days_past_due: Decimal | None
    insufficient_history: bool


class PaymentBehaviourOut(BaseModel):
    """FR-PAY-1-6, D-049 #5. Until gate G25 passes, `available` is false and nothing is
    computed (FR-PAY-6)."""

    available: bool
    reason: str | None = None
    window_from: date | None = None  # exclusive
    window_to: date | None = None  # inclusive: today in the company's time zone
    min_settlements: int | None = None
    overall: PaymentFigureOut | None = None
    customers: list[PaymentFigureOut] = []
    excluded_settlements: dict[str, int] = {}  # by voucher base type: not payments
    notes: list[str] = []
    unverified_gates: list[str]
