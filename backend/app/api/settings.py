from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_session
from app.core.permissions import CompanyContext, Permission, require
from app.schemas.settings import SettingsOut, SettingsUpdate
from app.services import settings

router = APIRouter(prefix="/companies/{company_id}/settings", tags=["settings"])


@router.get("")
async def read_settings(
    ctx: CompanyContext = Depends(require(Permission.VIEW_FINANCIALS)),
    session: AsyncSession = Depends(get_session),
) -> SettingsOut:
    return await settings.read_settings(session, ctx)


@router.put("")
async def update_settings(
    body: SettingsUpdate,
    ctx: CompanyContext = Depends(require(Permission.MANAGE_SETTINGS)),
    session: AsyncSession = Depends(get_session),
) -> SettingsOut:
    return await settings.update_settings(session, ctx, body)
