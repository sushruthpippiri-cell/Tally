"""Sync Now and command status (SRS 19.2, D-006)."""

import uuid

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_session
from app.core.permissions import CompanyContext, Permission, require
from app.schemas.commands import CommandStatusOut, CompanySyncRequest, SyncRequest
from app.services import commands

router = APIRouter(prefix="/companies/{company_id}", tags=["sync commands"])
RUN_SYNC = Depends(require(Permission.RUN_SYNC))


@router.post("/sync", status_code=201, summary="Sync Now (routes to an Agent)")
async def sync_company(
    body: CompanySyncRequest,
    ctx: CompanyContext = RUN_SYNC,
    session: AsyncSession = Depends(get_session),
) -> CommandStatusOut:
    request = SyncRequest(sync_mode=body.sync_mode, date_from=body.date_from, date_to=body.date_to)
    return await commands.create_command(session, ctx, request, body.agent_id)


@router.post("/agents/{agent_id}/sync", status_code=201, summary="Sync Now on one Agent")
async def sync_agent(
    agent_id: uuid.UUID,
    body: SyncRequest,
    ctx: CompanyContext = RUN_SYNC,
    session: AsyncSession = Depends(get_session),
) -> CommandStatusOut:
    return await commands.create_command(session, ctx, body, agent_id)


@router.get("/commands/{command_id}", summary="Command status (AGT-1.6)")
async def get_command(
    command_id: uuid.UUID,
    ctx: CompanyContext = Depends(require(Permission.VIEW_FINANCIALS)),
    session: AsyncSession = Depends(get_session),
) -> CommandStatusOut:
    return await commands.get_command(session, ctx, command_id)
