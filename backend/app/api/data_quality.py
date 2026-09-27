from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_session
from app.core.permissions import CompanyContext, Permission, require
from app.schemas.data_quality import CheckItems, CheckSummary
from app.services import data_quality

router = APIRouter(prefix="/companies/{company_id}/data-quality", tags=["data quality"])
VIEW = Depends(require(Permission.VIEW_RECON_AND_DQ))


@router.get("")
async def checks(
    ctx: CompanyContext = VIEW, session: AsyncSession = Depends(get_session)
) -> list[CheckSummary]:
    return await data_quality.summary(session, ctx)


@router.get("/{check_id}")
async def check_items(
    check_id: str,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    ctx: CompanyContext = VIEW,
    session: AsyncSession = Depends(get_session),
) -> CheckItems:
    return await data_quality.items(session, ctx, check_id, limit, offset)
