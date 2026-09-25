import uuid

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_session
from app.core.permissions import CompanyContext, Permission, require
from app.schemas.schedules import ScheduleCreate, ScheduleOut, ScheduleUpdate
from app.services import schedules

router = APIRouter(prefix="/companies/{company_id}/sync-schedules", tags=["sync schedules"])
MANAGE_SCHEDULES = Depends(require(Permission.MANAGE_SCHEDULES))


@router.get("")
async def list_schedules(
    ctx: CompanyContext = MANAGE_SCHEDULES, session: AsyncSession = Depends(get_session)
) -> list[ScheduleOut]:
    return await schedules.list_schedules(session, ctx)


@router.post("", status_code=201)
async def create_schedule(
    body: ScheduleCreate,
    ctx: CompanyContext = MANAGE_SCHEDULES,
    session: AsyncSession = Depends(get_session),
) -> ScheduleOut:
    return await schedules.create_schedule(session, ctx, body)


@router.put("/{schedule_id}")
async def update_schedule(
    schedule_id: uuid.UUID,
    body: ScheduleUpdate,
    ctx: CompanyContext = MANAGE_SCHEDULES,
    session: AsyncSession = Depends(get_session),
) -> ScheduleOut:
    return await schedules.update_schedule(session, ctx, schedule_id, body)
