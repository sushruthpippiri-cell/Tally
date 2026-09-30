import uuid
from collections.abc import Awaitable, Callable
from datetime import date

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_session
from app.core.periods import Granularity
from app.core.permissions import CompanyContext, Permission, require
from app.schemas.aging import AgingOut, AllocationsOut, BillsOut, PaymentBehaviourOut, Side
from app.schemas.analytics import DrilldownOut, MetricOut, RankingOut
from app.schemas.stock import MovementClass, StockOut
from app.services import aging, analytics, stock
from app.services.analytics import MetricName, RankBy, RankingKind

router = APIRouter(prefix="/companies/{company_id}/analytics", tags=["analytics"])
VIEW = Depends(require(Permission.VIEW_FINANCIALS))
FROM = Query(None, alias="from")  # `from` is a Python keyword
TO = Query(None, alias="to")
CLASS = Query(None, alias="class")  # `class` is a Python keyword


TOP_N = Query(None, ge=1, le=100)  # default: the analytics.top_n_default setting (TOPN-1.1)


def _ranked(kind: RankingKind) -> Callable[..., Awaitable[RankingOut]]:
    async def endpoint(
        date_from: date | None = FROM,
        date_to: date | None = TO,
        top_n: int | None = TOP_N,
        view_all: bool = False,
        rank_by: RankBy = "revenue",
        ctx: CompanyContext = VIEW,
        session: AsyncSession = Depends(get_session),
    ) -> RankingOut:
        return await analytics.ranking(
            session,
            ctx,
            kind,
            date_from=date_from,
            date_to=date_to,
            top_n=top_n,
            view_all=view_all,
            rank_by=rank_by,
        )

    return endpoint


# Registered before /{metric}, which would otherwise take these paths.
for _kind in ("customers", "suppliers", "products"):
    router.add_api_route(f"/{_kind}", _ranked(_kind), methods=["GET"], name=f"rank_{_kind}")


@router.get("/aging", summary="Receivables or payables aged per bill (SRS 10)")
async def aging_summary(
    side: Side,
    as_of: date | None = None,
    ctx: CompanyContext = VIEW,
    session: AsyncSession = Depends(get_session),
) -> AgingOut:
    return await aging.summary(session, ctx, side, as_of)


@router.get("/aging/bills", summary="A party's bills (aging drill-down)")
async def aging_bills(
    side: Side,
    ledger_id: uuid.UUID,
    as_of: date | None = None,
    ctx: CompanyContext = VIEW,
    session: AsyncSession = Depends(get_session),
) -> BillsOut:
    return await aging.bills(session, ctx, side, ledger_id, as_of)


@router.get("/aging/allocations", summary="A bill's allocations and vouchers")
async def aging_allocations(
    side: Side,
    ledger_id: uuid.UUID,
    reference: str = Query(..., min_length=1, max_length=200),
    as_of: date | None = None,
    ctx: CompanyContext = VIEW,
    session: AsyncSession = Depends(get_session),
) -> AllocationsOut:
    return await aging.allocations(session, ctx, side, ledger_id, reference, as_of)


@router.get("/payment-behaviour", summary="Customer payment behaviour (SRS 10.4)")
async def payment_behaviour(
    ctx: CompanyContext = VIEW, session: AsyncSession = Depends(get_session)
) -> PaymentBehaviourOut:
    return await aging.payment_behaviour(session, ctx)


@router.get("/stock", summary="Stock movement classes (SRS 11)")
async def stock_movement(
    period_days: int | None = None,  # 30, 60, 90 or 180 (FR-STK-1)
    movement_class: MovementClass | None = CLASS,
    page: int = Query(1, ge=1),
    page_size: int = Query(100, ge=1, le=500),
    ctx: CompanyContext = VIEW,
    session: AsyncSession = Depends(get_session),
) -> StockOut:
    return await stock.view(session, ctx, period_days, movement_class, page, page_size)


@router.get("/{metric}")
async def metric(
    metric: MetricName,
    date_from: date | None = FROM,
    date_to: date | None = TO,
    granularity: Granularity = "month",
    group_by: str | None = None,
    include_cancelled: bool = False,
    include_missing: bool = False,
    ctx: CompanyContext = VIEW,
    session: AsyncSession = Depends(get_session),
) -> MetricOut:
    return await analytics.metric(
        session,
        ctx,
        metric,
        date_from=date_from,
        date_to=date_to,
        granularity=granularity,
        group_by=group_by,
        include_cancelled=include_cancelled,
        include_missing=include_missing,
    )


@router.get("/{metric}/drilldown")
async def drilldown(
    metric: MetricName,
    date_from: date | None = FROM,
    date_to: date | None = TO,
    include_cancelled: bool = False,
    include_missing: bool = False,
    page: int = Query(1, ge=1),
    page_size: int = Query(100, ge=1, le=500),
    ctx: CompanyContext = VIEW,
    session: AsyncSession = Depends(get_session),
) -> DrilldownOut:
    return await analytics.drilldown(
        session,
        ctx,
        metric,
        date_from=date_from,
        date_to=date_to,
        include_cancelled=include_cancelled,
        include_missing=include_missing,
        page=page,
        page_size=page_size,
    )
