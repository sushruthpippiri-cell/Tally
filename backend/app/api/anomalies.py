"""Anomalies (FR-3.7, FR-3.8, SRS 12). Nothing here computes a figure: the rules did that, and
the explanation - if there is one - is shown separately from the evidence.
"""

from datetime import UTC, date, datetime

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.anomaly.prompt import SYSTEM_PROMPT
from app.core.config import get_settings
from app.core.db import get_session
from app.core.permissions import CompanyContext, Permission, require
from app.models.enums import AnomalyRule
from app.schemas.anomaly import (
    AnomaliesOut,
    AnomalyOut,
    DisclosureOut,
    ExplanationHealthOut,
    ReviewRequest,
)
from app.services import anomaly

router = APIRouter(prefix="/companies/{company_id}/anomalies", tags=["anomalies"])
VIEW = Depends(require(Permission.VIEW_FINANCIALS))
REVIEW = Depends(require(Permission.REVIEW_ANOMALIES))
SETTINGS = Depends(require(Permission.MANAGE_SETTINGS))
LOGS = Depends(require(Permission.VIEW_LOGS))
FROM = Query(None, alias="from")
TO = Query(None, alias="to")


@router.get("/disclosure", summary="Exactly what enabling this will send to Anthropic")
async def disclosure(ctx: CompanyContext = SETTINGS) -> DisclosureOut:
    """Generated from the same redaction the explainer uses, so it cannot drift from the truth
    (D-055 #7). Shown to the Owner before the feature can be turned on."""
    settings = get_settings()
    assert ctx.company_id is not None
    return anomaly.disclosure(
        settings.anomaly_explainer_model,
        settings.anthropic_api_key is not None,
        SYSTEM_PROMPT,
    )


@router.get("/explanation-health", summary="How often an explanation is discarded, and why")
async def explanation_health(
    ctx: CompanyContext = LOGS, session: AsyncSession = Depends(get_session)
) -> ExplanationHealthOut:
    return await anomaly.explanation_health(session, ctx)


@router.get("", summary="Flagged transactions with their evidence (SRS 12)")
async def anomalies(
    rule: AnomalyRule | None = None,
    reviewed: bool | None = None,
    date_from: date | None = FROM,
    date_to: date | None = TO,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    ctx: CompanyContext = VIEW,
    session: AsyncSession = Depends(get_session),
) -> AnomaliesOut:
    return await anomaly.listing(
        session,
        ctx,
        rule=None if rule is None else rule.value,
        reviewed=reviewed,
        date_from=date_from,
        date_to=date_to,
        limit=limit,
        offset=offset,
    )


@router.post("/{anomaly_id}/review", summary="Mark a flag reviewed or not an issue (FR-3.8)")
async def review(
    anomaly_id: int,
    body: ReviewRequest,
    ctx: CompanyContext = REVIEW,
    session: AsyncSession = Depends(get_session),
) -> AnomalyOut:
    return await anomaly.review(session, ctx, anomaly_id, body.action, datetime.now(UTC))
