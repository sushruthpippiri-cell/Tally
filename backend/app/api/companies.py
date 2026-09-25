from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_session
from app.core.permissions import CompanyContext, Permission, require
from app.core.security import current_user
from app.models.company import User
from app.schemas.companies import CompanyCreate, CompanyOut, CompanyUpdate
from app.services import companies

router = APIRouter(prefix="/companies", tags=["companies"])


@router.post("", status_code=201)
async def create_company(
    body: CompanyCreate,
    user: User = Depends(current_user),
    session: AsyncSession = Depends(get_session),
) -> CompanyOut:
    return await companies.create_company(session, user, body)


@router.get("")
async def list_companies(
    user: User = Depends(current_user), session: AsyncSession = Depends(get_session)
) -> list[CompanyOut]:
    return await companies.list_companies(session, user.user_id)


@router.get("/{company_id}")
async def get_company(
    ctx: CompanyContext = Depends(require(Permission.VIEW_FINANCIALS)),
    session: AsyncSession = Depends(get_session),
) -> CompanyOut:
    return await companies.get_company(session, ctx)


@router.put("/{company_id}")
async def update_company(
    body: CompanyUpdate,
    ctx: CompanyContext = Depends(require(Permission.MANAGE_SETTINGS)),
    session: AsyncSession = Depends(get_session),
) -> CompanyOut:
    return await companies.update_company(session, ctx, body)
