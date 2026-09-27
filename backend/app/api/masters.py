from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_session
from app.core.permissions import CompanyContext, Permission, require
from app.schemas.masters import GroupOut, VoucherTypeOut
from app.services import masters

router = APIRouter(prefix="/companies/{company_id}/masters", tags=["masters"])
VIEW = Depends(require(Permission.VIEW_FINANCIALS))  # SRS 19.2: any signed-in member


@router.get("/groups")
async def groups(
    ctx: CompanyContext = VIEW, session: AsyncSession = Depends(get_session)
) -> list[GroupOut]:
    return await masters.groups(session, ctx)


@router.get("/voucher-types")
async def voucher_types(
    ctx: CompanyContext = VIEW, session: AsyncSession = Depends(get_session)
) -> list[VoucherTypeOut]:
    return await masters.voucher_types(session, ctx)
