"""Reconciliation (SRS 9, 19.2, D-048)."""

import uuid

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_session
from app.core.permissions import CompanyContext, Permission, require
from app.schemas.commands import CommandStatusOut
from app.schemas.reconciliation import ReconciliationOut, ReconciliationRunRequest
from app.services import reconciliation

router = APIRouter(prefix="/companies/{company_id}/reconciliation", tags=["reconciliation"])


@router.post("/run", status_code=201, summary="Reconcile now (REC-1.4)")
async def run(
    body: ReconciliationRunRequest,
    ctx: CompanyContext = Depends(require(Permission.RUN_SYNC)),
    session: AsyncSession = Depends(get_session),
) -> CommandStatusOut:
    return await reconciliation.run(session, ctx, body.agent_id)


@router.get("", summary="The latest (or a chosen) reconciliation run (REC-1.2)")
async def get(
    run_id: uuid.UUID | None = None,
    only_failures: bool = False,
    offset: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=500),
    ctx: CompanyContext = Depends(require(Permission.VIEW_RECON_AND_DQ)),
    session: AsyncSession = Depends(get_session),
) -> ReconciliationOut:
    return await reconciliation.view(session, ctx, run_id, only_failures, offset, limit)
