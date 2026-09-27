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
from app.schemas.sync import (
    FinishRequest,
    LeaseOut,
    LeaseRequest,
    ReleaseOut,
    ReleaseRequest,
    RunOut,
    RunPlan,
)
from app.services import agents, commands, sync_runs
from app.sync.ingest import BatchResult, ingest
from tally_contract.records import BatchEnvelope

router = APIRouter(prefix="/agent", tags=["agent protocol"])


@router.post("/register", status_code=201, summary="Register with a one-time token (SRS 4.2)")
async def register(
    body: RegisterRequest, session: AsyncSession = Depends(get_session)
) -> RegisterResponse:
    return await agents.register_agent(session, body)


@router.post("/heartbeat", summary="Heartbeat and poll for a command (AGT-1.1)")
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


@router.post("/commands/{command_id}/runs", status_code=201, summary="Start a sync run: the plan")
async def start_run(
    command_id: uuid.UUID,
    agent: AgentContext = Depends(current_agent),
    session: AsyncSession = Depends(get_session),
) -> RunPlan:
    return await sync_runs.start_run(session, agent, command_id)


@router.post("/commands/{command_id}/runs/{sync_run_id}/finish", summary="Finish a sync run")
async def finish_run(
    command_id: uuid.UUID,
    sync_run_id: uuid.UUID,
    body: FinishRequest,
    agent: AgentContext = Depends(current_agent),
    session: AsyncSession = Depends(get_session),
) -> RunOut:
    return await sync_runs.finish_run(session, agent, command_id, sync_run_id, body)


@router.post("/leases/acquire", summary="Acquire a collection's sync lease (SYNC-4.1)")
async def acquire_lease(
    body: LeaseRequest,
    agent: AgentContext = Depends(current_agent),
    session: AsyncSession = Depends(get_session),
) -> LeaseOut:
    return await sync_runs.acquire_lease(session, agent, body)


@router.post("/leases/renew", summary="Renew every live lease (progress also does this)")
async def renew_leases(
    agent: AgentContext = Depends(current_agent),
    session: AsyncSession = Depends(get_session),
) -> dict[str, int]:
    return {"renewed": await sync_runs.renew_leases(session, agent)}


@router.post("/leases/release", summary="Release a lease; report a completed full pull")
async def release_lease(
    body: ReleaseRequest,
    agent: AgentContext = Depends(current_agent),
    session: AsyncSession = Depends(get_session),
) -> ReleaseOut:
    return await sync_runs.release_lease(session, agent, body)


@router.post("/commands/{command_id}/batches", summary="Upload a batch of records (SRS 6.5)")
async def upload_batch(
    command_id: uuid.UUID,
    body: BatchEnvelope,
    agent: AgentContext = Depends(current_agent),
    session: AsyncSession = Depends(get_session),
) -> BatchResult:
    return await ingest(session, agent, command_id, body)
