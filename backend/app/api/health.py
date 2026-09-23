from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_session
from tally_contract.log import get_logger

router = APIRouter(tags=["health"])
log = get_logger(__name__)


@router.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/health/db")
async def health_db(session: AsyncSession = Depends(get_session)) -> dict[str, str]:
    try:
        await session.execute(text("SELECT 1"))
    except Exception as exc:
        log.error("health_db_failed", error=type(exc).__name__)
        raise HTTPException(status_code=503, detail="database unavailable") from exc
    return {"status": "ok"}
