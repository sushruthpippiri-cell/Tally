"""Aging for the API (SRS 10, D-049). "Today" is the company's local date (TZ-1.1); the sums
are all in `app.analytics.aging`."""

import uuid
from datetime import date

from sqlalchemy.ext.asyncio import AsyncSession

from app.analytics import aging
from app.analytics.context import AnalyticsFilter, MetricContext, load
from app.core.errors import AppError
from app.core.gates import gate_passed
from app.core.periods import financial_year_of, today
from app.core.permissions import CompanyContext
from app.models.company import Company
from app.schemas.aging import (
    AgingOut,
    AgingRow,
    AllocationOut,
    AllocationsOut,
    BillOut,
    BillsOut,
    BucketLabel,
    NoBillDetails,
    PaymentBehaviourOut,
    PaymentFigureOut,
)
from app.schemas.analytics import Figure
from app.services.settings import get_setting
from tally_contract.errors import ErrorCode

REUSED = "Bill name used by more than one voucher; aged from the earliest (GATE-G31)"


async def context(
    session: AsyncSession, ctx: CompanyContext, as_of: date | None
) -> tuple[MetricContext, Company]:
    company = await session.get(Company, ctx.company_id)
    if company is None:
        raise AppError(ErrorCode.NOT_FOUND, "Company not found", 404)
    day = as_of or today(company.company_timezone)  # TZ-1.1, D-049 #4
    since = company.books_from or financial_year_of(day, company.financial_year_start).start
    return await load(session, ctx, AnalyticsFilter(min(since, day), day)), company


def _labels(keys: list[str]) -> list[BucketLabel]:
    names = {aging.NOT_YET_DUE: "Not yet due", aging.NO_DUE_DATE: "Due date unavailable"}
    return [BucketLabel(key=k, label=names.get(k, f"Overdue {k} days")) for k in keys]


def _row(p: aging.Party) -> AgingRow:
    return AgingRow(
        ledger_id=p.ledger_id,
        ledger_name=p.ledger_name,
        buckets=p.buckets,
        bucket_total=p.bucket_total,
        credit=p.credit,
        unadjusted_advances=p.advances,
        on_account=p.on_account,
        unmatched_settlements=p.unmatched,
        net_exposure=p.net_exposure,
    )


async def summary(
    session: AsyncSession, ctx: CompanyContext, side: str, as_of: date | None
) -> AgingOut:
    mctx, company = await context(session, ctx, as_of)
    boundaries = await get_setting(session, ctx.company_id, "aging.bucket_boundaries")
    result = await aging.aging(session, mctx, side, list(boundaries))
    return AgingOut(
        side=side,
        as_of=result.as_of,
        company_timezone=company.company_timezone,
        bucket_order=_labels([aging.NOT_YET_DUE, *result.labels, aging.NO_DUE_DATE]),
        total=_row(result.total),
        parties=[_row(p) for p in result.parties],
        no_bill_details=[
            NoBillDetails(
                ledger_id=lid,
                ledger_name=name,
                balance=Figure(amount=None, available=False)
                if amount is None
                else Figure(amount=abs(amount), direction="Dr" if amount >= 0 else "Cr"),
            )
            for lid, name, amount in result.no_bill_details
        ],
        unverified_gates=result.unverified_gates,
    )


async def bills(
    session: AsyncSession, ctx: CompanyContext, side: str, ledger_id: uuid.UUID, as_of: date | None
) -> BillsOut:
    mctx, _ = await context(session, ctx, as_of)
    boundaries = await get_setting(session, ctx.company_id, "aging.bucket_boundaries")
    b = aging.bills(mctx, side, list(boundaries)).subquery()
    rows = await session.execute(
        b.select()
        .where(b.c.ledger_id == ledger_id)
        .order_by(b.c.due_date.nulls_last(), b.c.bill_date, b.c.reference_name)
    )
    return BillsOut(
        side=side,
        as_of=mctx.filter.date_to,
        ledger_id=ledger_id,
        bills=[
            BillOut(
                reference_name=r.reference_name,
                bill_date=r.bill_date,
                due_date=r.due_date,
                days_overdue=r.days_overdue,
                bucket=r.bucket,
                outstanding=abs(r.outstanding),
                is_credit=r.bucket == aging.CREDIT,
                unverified=r.reused,
                unverified_reason=REUSED if r.reused else None,
            )
            for r in rows
        ],
        unverified_gates=aging.unverified_gates(),
    )


async def allocations(
    session: AsyncSession,
    ctx: CompanyContext,
    side: str,
    ledger_id: uuid.UUID,
    reference: str,
    as_of: date | None,
) -> AllocationsOut:
    mctx, _ = await context(session, ctx, as_of)
    rows = await session.execute(aging.allocations(mctx, side, ledger_id, reference))
    return AllocationsOut(
        side=side,
        as_of=mctx.filter.date_to,
        ledger_id=ledger_id,
        reference_name=reference,
        allocations=[
            AllocationOut(
                voucher_id=r.voucher_id,
                voucher_date=r.voucher_date,
                voucher_number=r.voucher_number,
                voucher_type_name=r.voucher_type_name,
                allocation_type=r.allocation_type,
                amount=r.amount,
                source=r.source,
            )
            for r in rows
        ],
        unverified_gates=aging.unverified_gates(),
    )


HIDDEN = "Awaiting Tally validation (G25)"
KINDS = {"CREDIT_NOTE": "credit notes (returns and discounts)", "JOURNAL": "journals"}


def _figure(f: aging.PaymentFigure) -> PaymentFigureOut:
    return PaymentFigureOut(**f.__dict__)


async def payment_behaviour(session: AsyncSession, ctx: CompanyContext) -> PaymentBehaviourOut:
    """FR-PAY-6: hidden, and not computed, until G25 passes."""
    if not gate_passed("G25"):
        return PaymentBehaviourOut(
            available=False, reason=HIDDEN, unverified_gates=aging.unverified_gates()
        )
    mctx, _ = await context(session, ctx, None)
    window = int(await get_setting(session, ctx.company_id, "payment.window_days"))
    minimum = int(await get_setting(session, ctx.company_id, "payment.min_settlements"))
    result = await aging.payment_behaviour(session, mctx, window, minimum)
    notes: list[str] = []
    if result.excluded_by_type:
        left_out = "; ".join(
            f"{n} on {KINDS.get(kind, kind.lower().replace('_', ' ') + ' vouchers')}"
            for kind, n in sorted(result.excluded_by_type.items())
        )
        notes.append(f"Only settlements on Receipt vouchers are payments: {left_out} left out.")
    if result.without_bill_date:
        notes.append(
            f"{result.without_bill_date} settlement(s) of bills with no bill date left out."
        )
    if result.without_due_date:
        notes.append(
            f"{result.without_due_date} settlement(s) of bills with no due date left out of "
            "average days past due."
        )
    return PaymentBehaviourOut(
        available=True,
        window_from=result.window_from,
        window_to=result.window_to,
        min_settlements=minimum,
        overall=_figure(result.overall),
        customers=[_figure(c) for c in result.customers],
        excluded_settlements=result.excluded_by_type,
        notes=notes,
        unverified_gates=aging.unverified_gates(),
    )
