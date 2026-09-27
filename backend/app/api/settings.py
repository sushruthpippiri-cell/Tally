from fastapi import APIRouter, Depends
from fastapi.responses import PlainTextResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_session
from app.core.permissions import CompanyContext, Permission, require
from app.schemas.settings import CustomFieldsUpdate, SettingsOut, SettingsUpdate
from app.services import custom_fields, settings
from tally_contract.udf import UdfMapping

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


MANAGE_CUSTOM_FIELDS = Depends(require(Permission.MANAGE_CUSTOM_FIELDS))  # SRS 19.2: Owner/Admin


@router.get("/custom-fields")
async def read_custom_fields(
    ctx: CompanyContext = MANAGE_CUSTOM_FIELDS, session: AsyncSession = Depends(get_session)
) -> list[UdfMapping]:
    return await custom_fields.list_mappings(session, ctx)


@router.put("/custom-fields")
async def replace_custom_fields(
    body: CustomFieldsUpdate,
    ctx: CompanyContext = MANAGE_CUSTOM_FIELDS,
    session: AsyncSession = Depends(get_session),
) -> list[UdfMapping]:
    return await custom_fields.replace_mappings(session, ctx, body)


@router.get("/custom-fields/tdl", response_class=PlainTextResponse)
async def custom_fields_tdl(
    ctx: CompanyContext = MANAGE_CUSTOM_FIELDS, session: AsyncSession = Depends(get_session)
) -> PlainTextResponse:
    return PlainTextResponse(
        await custom_fields.tdl(session, ctx),
        headers={"Content-Disposition": 'attachment; filename="TallyAnalytics_UDF.tdl"'},
    )
