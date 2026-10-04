import uuid

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_session
from app.core.permissions import CompanyContext, Permission, require
from app.schemas.vouchers import AuditEntryOut, VoucherDetailOut
from app.services import vouchers

router = APIRouter(prefix="/companies/{company_id}", tags=["vouchers"])


@router.get("/vouchers/{voucher_id}", summary="One voucher, as synced (FR-DD-1, DR-UDF-2)")
async def voucher(
    voucher_id: uuid.UUID,
    ctx: CompanyContext = Depends(require(Permission.VIEW_FINANCIALS)),
    session: AsyncSession = Depends(get_session),
) -> VoucherDetailOut:
    return await vouchers.detail(session, ctx, voucher_id)


@router.get("/audit", summary="An entity's audit history, newest first (LOG-1.2)")
async def audit_history(
    entity_type: str = Query(..., min_length=1, max_length=50),
    entity_id: str = Query(..., min_length=1, max_length=200),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    ctx: CompanyContext = Depends(require(Permission.VIEW_LOGS)),
    session: AsyncSession = Depends(get_session),
) -> list[AuditEntryOut]:
    return await vouchers.history(session, ctx, entity_type, entity_id, limit, offset)
