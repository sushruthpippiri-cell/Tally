"""The anomaly section: the flag, the list, the review, and what the jobs do (P15.5).

Nothing here runs while `FEATURE_ANOMALY_DETECTION` is off (FR-3.1, AC-55): the list reports the
section as unavailable without computing anything, and the jobs skip the company before they
import the explainer - so neither `anthropic` nor `mcp` is loaded either.
"""

import uuid
from datetime import date, datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from sqlalchemy import Select, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from app.anomaly import redact, rules
from app.core import audit
from app.core.errors import AppError
from app.core.periods import local_day_bounds, today
from app.core.permissions import CompanyContext
from app.models.company import Company
from app.models.config import AnomalyFlag, AnomalyScanState
from app.models.enums import AnomalyRule, ExplanationStatus, ExplanationUnavailableReason
from app.models.masters import Ledger
from app.models.vouchers import Voucher
from app.schemas.anomaly import (
    AnomaliesOut,
    AnomalyOut,
    DisclosureOut,
    ExplanationHealthOut,
    ReasonCount,
    ReviewAction,
)
from app.services.settings import get_flag, get_setting
from tally_contract.errors import ErrorCode
from tally_contract.log import get_logger

FEATURE = "FEATURE_ANOMALY_DETECTION"
DISABLED = "Anomaly detection is off for this company."
#: The cursor's overlap (D-055 #9): two sync transactions can commit out of order, so the scan
#: looks a little further back than the cursor. Re-scanning is free - the insert is idempotent.
OVERLAP = timedelta(minutes=5)
#: Never sent, listed for the disclosure the Owner confirms.
NEVER_SENT = [
    "party, ledger and company names",
    "voucher numbers and voucher type names",
    "narration",
    "dates",
    "Tally GUIDs and internal ids",
    "anything about the signed-in user",
    "any other voucher or any other anomaly",
]

log = get_logger(__name__)
V2 = aliased(Voucher, name="other_voucher")


async def enabled(session: AsyncSession, company_id: uuid.UUID) -> bool:
    return await get_flag(session, company_id, FEATURE)


# --- the list (FR-4.2, FR-3.7) ---------------------------------------------------------------


def _rows(company_id: uuid.UUID) -> Select[Any]:
    """A flag with the names its evidence panel shows. A cleared flag, or one whose voucher is
    no longer ACTIVE, leaves the list but stays in the table (D-055 #10)."""
    return (
        select(
            AnomalyFlag,
            Voucher.voucher_date,
            Voucher.voucher_number,
            Ledger.name.label("party_name"),
            V2.voucher_number.label("other_number"),
            V2.voucher_date.label("other_date"),
        )
        .join(
            Voucher,
            (Voucher.company_id == AnomalyFlag.company_id)
            & (Voucher.voucher_id == AnomalyFlag.voucher_id),
        )
        .outerjoin(
            Ledger,
            (Ledger.company_id == AnomalyFlag.company_id)
            & (Ledger.ledger_id == AnomalyFlag.party_ledger_id),
        )
        .outerjoin(
            V2,
            (V2.company_id == AnomalyFlag.company_id)
            & (V2.voucher_id == AnomalyFlag.duplicate_of_voucher_id),
        )
        .where(
            AnomalyFlag.company_id == company_id,
            AnomalyFlag.cleared_at.is_(None),
            Voucher.status == "ACTIVE",
        )
    )


def _deviation(value: Decimal | None) -> str | None:
    """ "+543%" from 542.857143. Rounded here, in Decimal, because the frontend may never turn a
    decimal string into a number (D-051 #5)."""
    if value is None:
        return None
    rounded = value.quantize(Decimal("1"), rounding=ROUND_HALF_UP)
    return f"{'+' if rounded > 0 else ''}{rounded}%"


def _out(row: Any) -> AnomalyOut:
    flag: AnomalyFlag = row[0]
    return AnomalyOut(
        anomaly_id=flag.id,
        rule=flag.rule_triggered,
        rule_label=redact.RULE_LABELS[flag.rule_triggered],
        voucher_id=flag.voucher_id,
        voucher_date=row.voucher_date,
        voucher_number=row.voucher_number,
        party_name=row.party_name,
        duplicate_of_voucher_id=flag.duplicate_of_voucher_id,
        duplicate_of_voucher_number=row.other_number,
        duplicate_of_voucher_date=row.other_date,
        transaction_amount=flag.transaction_amount,
        historical_average=flag.historical_average,
        historical_max=flag.historical_max,
        deviation_percent=flag.deviation_percent,
        deviation_display=_deviation(flag.deviation_percent),
        flagged_at=flag.flagged_at,
        explanation_status=flag.explanation_status,
        explanation_text=flag.explanation_text,
        explanation_unavailable_reason=flag.explanation_unavailable_reason,
        reviewed=flag.reviewed,
        not_an_issue=flag.not_an_issue,
        reviewed_at=flag.reviewed_at,
    )


async def listing(
    session: AsyncSession,
    ctx: CompanyContext,
    *,
    rule: str | None = None,
    reviewed: bool | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    limit: int = 50,
    offset: int = 0,
) -> AnomaliesOut:
    company = await session.get(Company, ctx.company_id)
    if company is None:
        raise AppError(ErrorCode.NOT_FOUND, "Company not found", 404)
    if not await enabled(session, ctx.company_id):
        # FR-3.1: nothing is computed, and the section reports itself unavailable.
        return AnomaliesOut(
            available=False, reason=DISABLED, company_timezone=company.company_timezone
        )
    query = _rows(ctx.company_id)
    if rule is not None:
        query = query.where(AnomalyFlag.rule_triggered == rule)
    if reviewed is not None:
        query = query.where(AnomalyFlag.reviewed == reviewed)
    if date_from is not None:
        query = query.where(Voucher.voucher_date >= date_from)
    if date_to is not None:
        query = query.where(Voucher.voucher_date <= date_to)
    total = await session.scalar(select(func.count()).select_from(query.subquery())) or 0
    rows = await session.execute(
        query.order_by(AnomalyFlag.flagged_at.desc(), AnomalyFlag.id.desc())
        .limit(limit)
        .offset(offset)
    )
    return AnomaliesOut(
        available=True,
        company_timezone=company.company_timezone,
        anomalies=[_out(r) for r in rows],
        total_count=total,
    )


# --- review (FR-3.8) --------------------------------------------------------------------------


async def review(
    session: AsyncSession,
    ctx: CompanyContext,
    anomaly_id: int,
    action: ReviewAction,
    now: datetime,
) -> AnomalyOut:
    if not await enabled(session, ctx.company_id):
        raise AppError(ErrorCode.NOT_FOUND, DISABLED, 404)
    flag = (
        await session.execute(
            select(AnomalyFlag).where(
                AnomalyFlag.id == anomaly_id, AnomalyFlag.company_id == ctx.company_id
            )
        )
    ).scalar_one_or_none()
    if flag is None:
        raise AppError(ErrorCode.NOT_FOUND, "Anomaly not found", 404)
    before = {"reviewed": flag.reviewed, "not_an_issue": flag.not_an_issue}
    flag.reviewed = True
    flag.not_an_issue = action == "not_an_issue"
    flag.reviewed_by = ctx.user_id
    flag.reviewed_at = now
    await audit.record(
        session,
        company_id=ctx.company_id,
        user_id=ctx.user_id,
        action="ANOMALY_REVIEWED",
        entity_type="anomaly_flags",
        entity_id=str(flag.id),
        before=before,
        after={"reviewed": True, "not_an_issue": flag.not_an_issue},
    )
    row = (await session.execute(_rows(ctx.company_id).where(AnomalyFlag.id == flag.id))).one()
    return _out(row)


# --- the disclosure the Owner confirms (D-055 #7) --------------------------------------------


def disclosure(model: str | None, api_key_configured: bool, system_prompt: str) -> DisclosureOut:
    """Built from the real `redact.evidence()`, so what is shown is what is sent."""
    example = redact.evidence(
        rule=AnomalyRule.UNUSUALLY_LARGE_SD,
        transaction_amount=Decimal("450000.0000"),
        historical_average=Decimal("70000.0000"),
        historical_max=Decimal("120000.0000"),
        deviation_percent=Decimal("542.857143"),
    )
    return DisclosureOut(
        model=model,
        api_key_configured=api_key_configured,
        fields_sent=list(redact.FIELDS),
        example=example,
        system_prompt=system_prompt,
        never_sent=NEVER_SENT,
    )


async def explanation_health(session: AsyncSession, ctx: CompanyContext) -> ExplanationHealthOut:
    rows = await session.execute(
        select(
            AnomalyFlag.explanation_status,
            AnomalyFlag.explanation_unavailable_reason,
            func.count(),
        )
        .where(AnomalyFlag.company_id == ctx.company_id, AnomalyFlag.cleared_at.is_(None))
        .group_by(AnomalyFlag.explanation_status, AnomalyFlag.explanation_unavailable_reason)
    )
    counts = {"AVAILABLE": 0, "PENDING": 0, "UNAVAILABLE": 0}
    by_reason: dict[str, int] = {}
    for status, reason, count in rows.tuples():
        counts[status] = counts.get(status, 0) + count
        if reason is not None:
            by_reason[reason] = by_reason.get(reason, 0) + count
    return ExplanationHealthOut(
        available=counts["AVAILABLE"],
        pending=counts["PENDING"],
        unavailable=counts["UNAVAILABLE"],
        by_reason=[
            ReasonCount(reason=r, count=c)
            for r, c in sorted(by_reason.items(), key=lambda kv: -kv[1])
        ],
    )


# --- what the rule job does (D-055 #4, #9, #11) ----------------------------------------------


async def scan(session: AsyncSession, company_id: uuid.UUID, now: datetime) -> tuple[int, int]:
    """Evaluate the vouchers stored since the cursor. Returns (written, cleared).

    Candidates include vouchers that are no longer ACTIVE: the rules will not flag them, so a
    flag on a cancelled or missing voucher is cleared rather than left behind (D-055 #10).
    """
    if not await enabled(session, company_id):
        return 0, 0
    company = await session.get(Company, company_id)
    if company is None:
        return 0, 0
    state = await session.get(AnomalyScanState, company_id)
    query = select(Voucher.voucher_id, Voucher.voucher_date, Voucher.last_synced_at).where(
        Voucher.company_id == company_id
    )
    if state is None:
        # First enable: bounded history, so switching the flag on cannot flag years at once.
        days = int(await get_setting(session, company_id, "anomaly.initial_scan_days"))
        floor = today(company.company_timezone) - timedelta(days=days)
        query = query.where(Voucher.voucher_date >= floor)
        state = AnomalyScanState(company_id=company_id)
        session.add(state)
        log.info("anomaly_first_scan", company_id=str(company_id), since=floor.isoformat())
    elif state.synced_through is not None:
        query = query.where(Voucher.last_synced_at > state.synced_through - OVERLAP)
    rows = (await session.execute(query)).all()
    state.last_scanned_at = now
    if not rows:
        return 0, 0
    written, cleared = await rules.evaluate(
        session,
        company_id,
        {r.voucher_id for r in rows},
        min(r.voucher_date for r in rows),
        now,
    )
    stamps = [r.last_synced_at for r in rows if r.last_synced_at is not None]
    state.synced_through = max(stamps) if stamps else now
    await session.flush()
    return written, cleared


# --- what the explanation job does (D-055 #11) -----------------------------------------------

#: Worth another attempt: the explanation was not available, not wrong. A discarded or refused
#: explanation is about the content, so retrying it is just spending money twice.
RETRYABLE = (
    ExplanationUnavailableReason.CLAUDE_UNREACHABLE.value,
    ExplanationUnavailableReason.TIMEOUT.value,
)
MAX_ATTEMPTS = 3


async def due_for_explanation(
    session: AsyncSession, company_id: uuid.UUID, now: datetime, timezone: str
) -> list[AnomalyFlag]:
    """The newest anomalies still wanting an explanation, within today's budget."""
    cap = int(await get_setting(session, company_id, "anomaly.max_explanations_per_day"))
    start, _end = local_day_bounds(today(timezone), timezone)
    used = (
        await session.scalar(
            select(func.count())
            .select_from(AnomalyFlag)
            .where(
                AnomalyFlag.company_id == company_id,
                AnomalyFlag.explanation_last_attempt_at >= start,
            )
        )
    ) or 0
    budget = cap - used
    if budget <= 0:
        log.info("anomaly_explanation_cap_reached", company_id=str(company_id), cap=cap)
        return []
    rows = await session.execute(
        select(AnomalyFlag)
        .join(
            Voucher,
            (Voucher.company_id == AnomalyFlag.company_id)
            & (Voucher.voucher_id == AnomalyFlag.voucher_id),
        )
        .where(
            AnomalyFlag.company_id == company_id,
            AnomalyFlag.cleared_at.is_(None),
            Voucher.status == "ACTIVE",
            (AnomalyFlag.explanation_status == ExplanationStatus.PENDING.value)
            | (
                (AnomalyFlag.explanation_status == ExplanationStatus.UNAVAILABLE.value)
                & AnomalyFlag.explanation_unavailable_reason.in_(RETRYABLE)
                & (AnomalyFlag.explanation_attempts < MAX_ATTEMPTS)
            ),
        )
        # Newest first by the transaction's own date: every flag from one scan shares
        # flagged_at, so ordering by that could not discriminate within a run (D-055 #11).
        .order_by(Voucher.voucher_date.desc(), AnomalyFlag.id.desc())
        .limit(budget)
    )
    return list(rows.scalars())


async def substitutions(session: AsyncSession, flag: AnomalyFlag) -> dict[str, str]:
    """The placeholders mapped back to what the owner should read. Display only - these names
    never went out (SEC-1.12)."""
    out: dict[str, str] = {}
    if flag.party_ledger_id is not None:
        name = await session.scalar(
            select(Ledger.name).where(
                Ledger.company_id == flag.company_id, Ledger.ledger_id == flag.party_ledger_id
            )
        )
        if name:
            out[redact.PARTY] = name
    for placeholder, voucher_id in (
        (redact.VOUCHER, flag.voucher_id),
        (redact.OTHER_VOUCHER, flag.duplicate_of_voucher_id),
    ):
        if voucher_id is None:
            continue
        row = (
            await session.execute(
                select(Voucher.voucher_number, Voucher.voucher_date).where(
                    Voucher.company_id == flag.company_id, Voucher.voucher_id == voucher_id
                )
            )
        ).one_or_none()
        if row is not None:
            out[placeholder] = row.voucher_number or f"the voucher dated {row.voucher_date}"
    return out
