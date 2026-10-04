"""Aging of receivables and payables per bill (SRS 10, FR-AGE-1/2, AGE-BILL-1-5, D-049).

Everything here is summed from one detail query per side (`receivable_bills`, `payable_bills`:
one row per bill allocation, opening bills as New References), reached only through
`query.detail`, so the summary, the per-party rows and the drill-downs cannot disagree
(rule 9). Rows are signed toward the side (receivable debit +, payable credit +, D-049 #1).

Rows are grouped by (ledger, reference):
- with a New Reference: a **bill**; outstanding = its New and Against References;
- with an Advance and no New Reference: an **advance**; an Against Reference to it adjusts it
  (GATE-G25, D-049 #2);
- with Against References only: an **unmatched settlement** (D-049 #6).
On Account rows belong to no reference. Amounts that reduce the exposure (credits, advances,
on-account, unmatched) are reported as positive figures.
"""

import uuid
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal
from typing import Any, Literal

from sqlalchemy import (
    ColumnElement,
    Date,
    Integer,
    Select,
    Text,
    case,
    cast,
    distinct,
    func,
    literal,
    select,
    tuple_,
    type_coerce,
)
from sqlalchemy.ext.asyncio import AsyncSession

from app.analytics import query
from app.analytics.context import MetricContext
from app.core.gates import gate_passed
from app.models.enums import AllocationType

Side = Literal["receivable", "payable"]
METRIC: dict[str, str] = {"receivable": "receivable_bills", "payable": "payable_bills"}
BALANCE_METRIC: dict[str, str] = {"receivable": "receivables", "payable": "payables"}
GATES = ("G25", "G31")  # allocation types; bill details, opening bills, due dates

NEW, AGST = AllocationType.NEW_REF.value, AllocationType.AGST_REF.value
ADVANCE, ON_ACCOUNT = AllocationType.ADVANCE.value, AllocationType.ON_ACCOUNT.value
NOT_YET_DUE, NO_DUE_DATE, CREDIT = "NOT_YET_DUE", "NO_DUE_DATE", "CREDIT"


def unverified_gates() -> list[str]:
    return [g for g in GATES if not gate_passed(g)]


def bucket_labels(boundaries: list[int]) -> list[str]:
    """[30, 60, 90] -> ["0-30", "31-60", "61-90", "90+"] (SRS 10.1); any ascending list."""
    starts = [0, *(b + 1 for b in boundaries)]
    return [f"{s}-{b}" for s, b in zip(starts, boundaries, strict=False)] + [f"{boundaries[-1]}+"]


def _rows(ctx: MetricContext, side: str) -> Any:
    return query.detail(METRIC[side], ctx).subquery()


def bills(ctx: MetricContext, side: str, boundaries: list[int]) -> Select[Any]:
    """One row per bill with outstanding != 0 on `filter.date_to` (the as-of date): bill and due
    dates, `days_overdue` (None unless due on or before the as-of date: never negative, AC-46),
    `bucket`, and `reused` when New References from more than one voucher (or a voucher and an
    opening bill) share its name (D-049 #7)."""
    r = _rows(ctx, side)
    new = r.c.allocation_type == NEW
    raised_by = case((new, func.coalesce(cast(r.c.voucher_id, Text), "opening bill")))
    grouped = (
        select(
            r.c.ledger_id,
            r.c.ledger_name,
            r.c.reference_name,
            func.min(r.c.voucher_date).filter(new).label("bill_date"),
            func.max(r.c.due_date).filter(new).label("due_date"),
            func.sum(r.c.amount).filter(r.c.allocation_type.in_([NEW, AGST])).label("outstanding"),
            (func.count(distinct(raised_by)) > 1).label("reused"),
        )
        .where(r.c.reference_name.is_not(None))
        .group_by(r.c.ledger_id, r.c.ledger_name, r.c.reference_name)
        .having(func.bool_or(new))
    ).subquery()
    as_of = cast(literal(ctx.filter.date_to), Date)
    days = type_coerce(as_of - grouped.c.due_date, Integer)  # DATE - DATE: whole days
    labels = bucket_labels(boundaries)
    bucket = case(
        (grouped.c.outstanding < 0, CREDIT),  # over-settled: a credit, never bucketed
        (grouped.c.due_date.is_(None), NO_DUE_DATE),
        (grouped.c.due_date > as_of, NOT_YET_DUE),
        *((days <= limit, label) for limit, label in zip(boundaries, labels, strict=False)),
        else_=labels[-1],
    )
    return select(
        grouped,
        case((grouped.c.due_date <= as_of, days)).label("days_overdue"),
        bucket.label("bucket"),
    ).where(grouped.c.outstanding != 0)


def _references(ctx: MetricContext, side: str) -> Select[Any]:
    """Per (ledger, reference): what kind of reference it is and its parts."""
    r = _rows(ctx, side)
    kind = r.c.allocation_type
    return select(
        r.c.ledger_id,
        r.c.ledger_name,
        r.c.reference_name,
        func.bool_or(kind == NEW).label("is_bill"),
        func.bool_or(kind == ADVANCE).label("is_advance"),
        func.coalesce(func.sum(r.c.amount).filter(kind.in_([ADVANCE, AGST])), 0).label("advance"),
        func.coalesce(func.sum(r.c.amount).filter(kind == ADVANCE), 0).label("advance_only"),
        func.coalesce(func.sum(r.c.amount).filter(kind == ON_ACCOUNT), 0).label("on_account"),
        func.coalesce(func.sum(r.c.amount).filter(kind == AGST), 0).label("settled"),
        func.sum(r.c.amount).label("net"),
    ).group_by(r.c.ledger_id, r.c.ledger_name, r.c.reference_name)


@dataclass
class Party:
    ledger_id: uuid.UUID | None  # None: the side's total
    ledger_name: str | None
    buckets: dict[str, Decimal]  # every bucket label, NOT_YET_DUE and NO_DUE_DATE
    credit: Decimal = Decimal(0)  # over-settled bills, as a positive (Cr) amount
    advances: Decimal = Decimal(0)  # Unadjusted Advances, positive
    on_account: Decimal = Decimal(0)  # On-Account / Unallocated, positive
    unmatched: Decimal = Decimal(0)  # unmatched settlements, positive
    net_exposure: Decimal = Decimal(0)  # every row of the party, signed toward the side

    @property
    def bucket_total(self) -> Decimal:
        return sum(self.buckets.values(), Decimal(0))


@dataclass
class Aging:
    side: str
    as_of: date
    labels: list[str]
    total: Party
    parties: list[Party]
    no_bill_details: list[tuple[uuid.UUID, str, Decimal | None]]  # ledger, name, balance
    unverified_gates: list[str]


async def aging(
    session: AsyncSession, ctx: MetricContext, side: str, boundaries: list[int]
) -> Aging:
    """The side's aging on `filter.date_to`, per party and in total, summed in SQL with
    GROUPING SETS: the party rows and the total are one statement each (rule 10)."""
    labels = bucket_labels(boundaries)
    keys = [*labels, NOT_YET_DUE, NO_DUE_DATE]
    b = bills(ctx, side, boundaries).subquery()
    by_bucket = await session.execute(
        select(b.c.ledger_id, b.c.ledger_name, b.c.bucket, func.sum(b.c.outstanding)).group_by(
            func.grouping_sets(tuple_(b.c.ledger_id, b.c.ledger_name, b.c.bucket), b.c.bucket)
        )
    )
    refs = _references(ctx, side).subquery()
    advance = case((~refs.c.is_bill & refs.c.is_advance, refs.c.advance), else_=refs.c.advance_only)
    unmatched = case((~refs.c.is_bill & ~refs.c.is_advance, refs.c.settled), else_=0)
    # GROUPING SETS still emits one row per set when the input is empty, and SUM() over no rows
    # is NULL - so a side with no bills at all would hand the schema a NULL where it wants a
    # figure. These are counts of money that exist: nothing is zero.

    def summed(column: Any) -> ColumnElement[Decimal]:
        return func.coalesce(func.sum(column), 0)

    others = await session.execute(
        select(
            refs.c.ledger_id,
            refs.c.ledger_name,
            summed(-advance),
            summed(-refs.c.on_account),
            summed(-unmatched),
            summed(refs.c.net),
        ).group_by(func.grouping_sets(tuple_(refs.c.ledger_id, refs.c.ledger_name), tuple_()))
    )
    parties: dict[Any, Party] = {}

    def party(ledger_id: Any, name: Any) -> Party:
        if ledger_id not in parties:
            parties[ledger_id] = Party(ledger_id, name, dict.fromkeys(keys, Decimal(0)))
        return parties[ledger_id]

    for ledger_id, name, bucket, amount in by_bucket.tuples():
        if bucket is None:
            continue  # the same empty-input artefact: every bill row has a bucket
        p = party(ledger_id, name)
        if bucket == CREDIT:
            p.credit = -amount
        else:
            p.buckets[bucket] = amount
    for ledger_id, name, adv, on_acc, unm, net in others.tuples():
        p = party(ledger_id, name)
        p.advances, p.on_account, p.unmatched, p.net_exposure = adv, on_acc, unm, net
    total = parties.pop(None, None) or Party(None, None, dict.fromkeys(keys, Decimal(0)))
    return Aging(
        side=side,
        as_of=ctx.filter.date_to,
        labels=labels,
        total=total,
        parties=sorted(parties.values(), key=lambda p: (p.ledger_name or "", str(p.ledger_id))),
        no_bill_details=await no_bill_details(session, ctx, side),
        unverified_gates=unverified_gates(),
    )


async def no_bill_details(
    session: AsyncSession, ctx: MetricContext, side: str
) -> list[tuple[uuid.UUID, str, Decimal | None]]:
    """SRS 10.3: the side's ledgers with no bill rows at all, as one balance each (ACC-9.4),
    never in a bucket. Zero balances are left out; an unavailable one is kept (ACC-9.6)."""
    r = _rows(ctx, side)
    with_bills = {lid for (lid,) in (await session.execute(select(r.c.ledger_id).distinct()))}
    balances = await query.breakdown(session, ctx, BALANCE_METRIC[side], "ledger_id", "ledger_name")
    return sorted(
        (
            (lid, name, amount)
            for lid, name, amount in balances
            if lid not in with_bills and amount != 0
        ),
        key=lambda x: x[1],
    )


def allocations(ctx: MetricContext, side: str, ledger_id: uuid.UUID, reference: str) -> Select[Any]:
    """The drill-down below a bill: its rows (allocations and any opening bill) with their
    vouchers, oldest first."""
    r = _rows(ctx, side)
    return (
        select(r)
        .where(r.c.ledger_id == ledger_id, r.c.reference_name == reference)
        .order_by(r.c.voucher_date.nulls_first(), r.c.voucher_number, r.c.voucher_id)
    )


def unmatched_settlements(ctx: MetricContext, side: str) -> Select[Any]:
    """Against References whose reference has neither a New Reference nor an Advance."""
    refs = _references(ctx, side).subquery()
    return (
        select(refs.c.ledger_name, refs.c.reference_name, (-refs.c.settled).label("amount"))
        .where(~refs.c.is_bill, ~refs.c.is_advance, refs.c.settled != 0)
        .order_by(refs.c.ledger_name, refs.c.reference_name)
    )


# --- payment behaviour (SRS 10.4, FR-PAY-1-6, D-049 #5) ----------------------------------------

PAYMENT_BASE = "RECEIPT"


@dataclass
class PaymentFigure:
    ledger_id: uuid.UUID | None  # None: all customers
    ledger_name: str | None
    settlements: int
    settled_amount: Decimal
    avg_days_to_pay: Decimal | None  # None: insufficient history
    avg_days_past_due: Decimal | None  # None: insufficient history, or no bill had a due date
    insufficient_history: bool


@dataclass
class PaymentBehaviour:
    window_from: date  # exclusive
    window_to: date  # inclusive: the as-of date
    overall: PaymentFigure
    customers: list[PaymentFigure]
    excluded_by_type: dict[str, int]  # settlements that are not payments (credit notes, ...)
    without_bill_date: int
    without_due_date: int


def settlements(ctx: MetricContext, window_days: int) -> Select[Any]:
    """Each Against Reference that lowers a customer's bill (FR-PAY-2: part settlements
    separately), dated in (as-of − window, as-of], with its bill's date and due date. Refunds
    raise a bill and are never settlements; Advance and On Account are not settlements
    (FR-PAY-4)."""
    r = _rows(ctx, "receivable")
    new = r.c.allocation_type == NEW
    bill = (
        select(
            r.c.ledger_id,
            r.c.reference_name,
            func.min(r.c.voucher_date).filter(new).label("bill_date"),
            func.max(r.c.due_date).filter(new).label("due_date"),
        )
        .where(r.c.reference_name.is_not(None))
        .group_by(r.c.ledger_id, r.c.reference_name)
        .having(func.bool_or(new))
    ).subquery()
    as_of = ctx.filter.date_to
    return (
        select(
            r.c.ledger_id,
            r.c.ledger_name,
            r.c.base_voucher_type,
            r.c.voucher_date,
            (-r.c.amount).label("settled"),
            bill.c.bill_date,
            bill.c.due_date,
        )
        .join(
            bill,
            (bill.c.ledger_id == r.c.ledger_id) & (bill.c.reference_name == r.c.reference_name),
        )
        .where(
            r.c.allocation_type == AGST,
            r.c.amount < 0,
            r.c.voucher_date > cast(literal(as_of), Date) - window_days,
            r.c.voucher_date <= cast(literal(as_of), Date),
        )
    )


async def payment_behaviour(
    session: AsyncSession, ctx: MetricContext, window_days: int, min_settlements: int
) -> PaymentBehaviour:
    """FR-PAY-1: Σ(amount × (settled − bill date)) ÷ Σ amount; FR-PAY-3: the same from the due
    date, early payments as 0, bills without a due date left out. Only settlements on Receipt
    vouchers are payments (D-049 #5). Summed in SQL, per customer and over all customers."""
    s = settlements(ctx, window_days).subquery()
    paid = (s.c.base_voucher_type == PAYMENT_BASE) & s.c.bill_date.is_not(None)
    with_due = paid & s.c.due_date.is_not(None)
    to_pay = type_coerce(s.c.voucher_date - s.c.bill_date, Integer)
    past_due = func.greatest(0, type_coerce(s.c.voucher_date - s.c.due_date, Integer))
    amount = func.sum(s.c.settled)
    figures = await session.execute(
        select(
            s.c.ledger_id,
            s.c.ledger_name,
            func.count().filter(paid),
            func.coalesce(amount.filter(paid), 0),
            func.sum(s.c.settled * to_pay).filter(paid) / amount.filter(paid),
            func.sum(s.c.settled * past_due).filter(with_due) / amount.filter(with_due),
        )
        .where(paid)
        .group_by(func.grouping_sets(tuple_(s.c.ledger_id, s.c.ledger_name), tuple_()))
    )
    two = Decimal("0.01")
    rows: dict[Any, PaymentFigure] = {}
    for ledger_id, name, count, settled, days, due_days in figures.tuples():
        short = count < min_settlements  # FR-PAY-5
        rows[ledger_id] = PaymentFigure(
            ledger_id=ledger_id,
            ledger_name=name,
            settlements=count,
            settled_amount=settled,
            avg_days_to_pay=None if short or days is None else days.quantize(two),
            avg_days_past_due=None if short or due_days is None else due_days.quantize(two),
            insufficient_history=short,
        )
    counts = await session.execute(
        select(
            func.coalesce(s.c.base_voucher_type, "OPENING"),
            func.count(),
            func.count().filter(s.c.bill_date.is_(None)),
            func.count().filter(s.c.bill_date.is_not(None) & s.c.due_date.is_(None)),
        ).group_by(s.c.base_voucher_type)
    )
    excluded: dict[str, int] = {}
    without_bill_date = without_due_date = 0
    for base, count, no_bill_date, no_due in counts.tuples():
        if base != PAYMENT_BASE:
            excluded[base] = count
        else:
            without_bill_date, without_due_date = no_bill_date, no_due
    overall = rows.pop(None, None) or PaymentFigure(None, None, 0, Decimal(0), None, None, True)
    return PaymentBehaviour(
        window_from=ctx.filter.date_to - timedelta(days=window_days),
        window_to=ctx.filter.date_to,
        overall=overall,
        customers=sorted(rows.values(), key=lambda f: (f.ledger_name or "", str(f.ledger_id))),
        excluded_by_type=excluded,
        without_bill_date=without_bill_date,
        without_due_date=without_due_date,
    )
