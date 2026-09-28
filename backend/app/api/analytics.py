from datetime import date

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_session
from app.core.periods import Granularity
from app.core.permissions import CompanyContext, Permission, require
from app.schemas.analytics import DrilldownOut, MetricOut
from app.services import analytics
from app.services.analytics import MetricName

router = APIRouter(prefix="/companies/{company_id}/analytics", tags=["analytics"])
VIEW = Depends(require(Permission.VIEW_FINANCIALS))
FROM = Query(None, alias="from")  # `from` is a Python keyword
TO = Query(None, alias="to")


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
