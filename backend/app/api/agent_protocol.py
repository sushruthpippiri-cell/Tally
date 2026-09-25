"""Endpoints the Agent calls. The backend never calls the Agent (CLAUDE.md rule 12)."""

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_session
from app.schemas.agents import RegisterRequest, RegisterResponse
from app.services import agents

router = APIRouter(prefix="/agent", tags=["agent protocol"])


@router.post("/register", status_code=201)
async def register(
    body: RegisterRequest, session: AsyncSession = Depends(get_session)
) -> RegisterResponse:
    return await agents.register_agent(session, body)
