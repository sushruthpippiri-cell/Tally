"""Endpoints the Agent calls. The backend never calls the Agent (CLAUDE.md rule 12)."""

import uuid

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.agent_credentials import AgentContext, current_agent
from app.core.db import get_session
from app.schemas.agents import (
    HeartbeatRequest,
    HeartbeatResponse,
    RegisterRequest,
    RegisterResponse,
)
from app.schemas.commands import AgentCommandOut, ResultRequest
from app.services import agents, commands

router = APIRouter(prefix="/agent", tags=["agent protocol"])


@router.post("/register", status_code=201)
async def register(
    body: RegisterRequest, session: AsyncSession = Depends(get_session)
) -> RegisterResponse:
    return await agents.register_agent(session, body)


@router.post("/heartbeat")
async def heartbeat(
    body: HeartbeatRequest,
    agent: AgentContext = Depends(current_agent),
    session: AsyncSession = Depends(get_session),
) -> HeartbeatResponse:
    return await agents.heartbeat(session, agent, body)


@router.post("/commands/{command_id}/claim", summary="Claim a PENDING command (AGT-1.3)")
async def claim(
    command_id: uuid.UUID,
    agent: AgentContext = Depends(current_agent),
    session: AsyncSession = Depends(get_session),
) -> AgentCommandOut:
    return await commands.claim(session, agent, command_id)


@router.post(
    "/commands/{command_id}/progress",
    summary="Renew the lease (AGT-1.7); send on a timer, independent of Tally",
)
async def progress(
    command_id: uuid.UUID,
    agent: AgentContext = Depends(current_agent),
    session: AsyncSession = Depends(get_session),
) -> AgentCommandOut:
    return await commands.progress(session, agent, command_id)


@router.post("/commands/{command_id}/result", summary="Finish: COMPLETED or FAILED")
async def result(
    command_id: uuid.UUID,
    body: ResultRequest,
    agent: AgentContext = Depends(current_agent),
    session: AsyncSession = Depends(get_session),
) -> AgentCommandOut:
    return await commands.result(session, agent, command_id, body)
