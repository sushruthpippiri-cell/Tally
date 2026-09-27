import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_session
from app.core.permissions import CompanyContext, Permission, require
from app.schemas.sync import KeyListOut, LeaseStatus, RunSummary, SyncErrorOut, SyncStatusOut
from app.services import sync_status
from app.sync import keylists

router = APIRouter(prefix="/companies/{company_id}/sync", tags=["sync status"])
VIEW = Depends(require(Permission.VIEW_FINANCIALS))  # SRS 19.2: any signed-in member
LIMIT = Query(50, ge=1, le=200)


@router.get("/status")
async def status(
    ctx: CompanyContext = VIEW, session: AsyncSession = Depends(get_session)
) -> SyncStatusOut:
    return await sync_status.status(session, ctx)


@router.get("/lease-status")
async def lease_status(
    ctx: CompanyContext = VIEW, session: AsyncSession = Depends(get_session)
) -> list[LeaseStatus]:
    return await sync_status.leases(session, ctx)


@router.get("/runs")
async def runs(
    limit: int = LIMIT,
    before: datetime | None = None,
    ctx: CompanyContext = VIEW,
    session: AsyncSession = Depends(get_session),
) -> list[RunSummary]:
    return await sync_status.runs(session, ctx, limit, before)


@router.get("/errors")
async def errors(
    sync_run_id: uuid.UUID | None = None,
    code: str | None = Query(None, max_length=64),
    limit: int = LIMIT,
    before: int | None = None,
    ctx: CompanyContext = Depends(require(Permission.VIEW_LOGS)),  # SRS 19.2: Owner/Admin
    session: AsyncSession = Depends(get_session),
) -> list[SyncErrorOut]:
    return await sync_status.errors(
        session, ctx, sync_run_id=sync_run_id, code=code, limit=limit, before=before
    )


@router.post("/key-lists/{list_id}/confirm")
async def confirm_key_list(
    list_id: uuid.UUID,
    ctx: CompanyContext = Depends(require(Permission.MANAGE_SETTINGS)),  # Owner/Admin (D-041)
    session: AsyncSession = Depends(get_session),
) -> KeyListOut:
    return await keylists.confirm(session, ctx, list_id)
