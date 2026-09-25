"""Company-side Agent management (Owner/Admin); the Agent's own endpoints are in
app/api/agent_protocol.py."""

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_session
from app.core.permissions import CompanyContext, Permission, require
from app.schemas.agents import RegistrationTokenOut
from app.services import agents

router = APIRouter(prefix="/companies/{company_id}/agents", tags=["agents"])
MANAGE_AGENTS = Depends(require(Permission.MANAGE_AGENTS))


@router.post("/register-token", status_code=201)
async def create_registration_token(
    ctx: CompanyContext = MANAGE_AGENTS, session: AsyncSession = Depends(get_session)
) -> RegistrationTokenOut:
    return await agents.create_registration_token(session, ctx)
