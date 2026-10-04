import uuid

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_session
from app.core.permissions import CompanyContext, Permission, require
from app.schemas.masters import GroupOut, OptionOut, VoucherTypeOut
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


SEARCH = Query(None, max_length=100)
OPTION_ID = Query(None, alias="id")


@router.get("/options", summary="Choices for the customer, product and cost-centre filters")
async def options(
    kind: masters.OptionKind,
    q: str | None = SEARCH,
    option_id: uuid.UUID | None = OPTION_ID,
    ctx: CompanyContext = VIEW,
    session: AsyncSession = Depends(get_session),
) -> list[OptionOut]:
    return await masters.options(session, ctx, kind, q, option_id)
