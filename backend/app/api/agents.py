"""Company-side Agent management (Owner/Admin); the Agent's own endpoints are in
app/api/agent_protocol.py."""

import uuid

from fastapi import APIRouter, Depends, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_session
from app.core.permissions import CompanyContext, Permission, require
from app.schemas.agents import (
    AgentsView,
    RegistrationTokenOut,
    RotatedCredential,
    TallySettingsUpdate,
)
from app.services import agent_admin, agents

router = APIRouter(prefix="/companies/{company_id}/agents", tags=["agents"])
MANAGE_AGENTS = Depends(require(Permission.MANAGE_AGENTS))


@router.post("/register-token", status_code=201)
async def create_registration_token(
    ctx: CompanyContext = MANAGE_AGENTS, session: AsyncSession = Depends(get_session)
) -> RegistrationTokenOut:
    return await agents.create_registration_token(session, ctx)


@router.get("", summary="Agents view (FR-4.4)")
async def list_agents(
    ctx: CompanyContext = Depends(require(Permission.VIEW_FINANCIALS)),
    session: AsyncSession = Depends(get_session),
) -> AgentsView:
    return await agent_admin.list_agents(session, ctx)


@router.post("/{agent_id}/rotate-credential", summary="Rotate an Agent credential (SRS 4.4)")
async def rotate_credential(
    agent_id: uuid.UUID,
    ctx: CompanyContext = MANAGE_AGENTS,
    session: AsyncSession = Depends(get_session),
) -> RotatedCredential:
    return await agent_admin.rotate(session, ctx, agent_id)


@router.post("/{agent_id}/revoke", status_code=204, summary="Revoke an Agent, permanently")
async def revoke(
    agent_id: uuid.UUID,
    ctx: CompanyContext = MANAGE_AGENTS,
    session: AsyncSession = Depends(get_session),
) -> Response:
    await agent_admin.revoke(session, ctx, agent_id)
    return Response(status_code=204)


@router.put("/{agent_id}/tally-settings", summary="Tally host, port, company name, batch size")
async def update_tally_settings(
    agent_id: uuid.UUID,
    body: TallySettingsUpdate,
    ctx: CompanyContext = MANAGE_AGENTS,
    session: AsyncSession = Depends(get_session),
) -> AgentsView:
    return await agent_admin.update_tally_settings(session, ctx, agent_id, body)
