"""What a metric query needs, loaded once per request (D-044 #1). The company always comes
from the authorised `CompanyContext`, never from the request's filters (SEC-1.7)."""

import uuid
from dataclasses import dataclass
from datetime import date

from sqlalchemy.ext.asyncio import AsyncSession

from app.analytics.classification import Classes, load_classes
from app.core.errors import AppError
from app.core.gates import gate_passed
from app.core.periods import QuarterMode
from app.core.permissions import CompanyContext
from app.models.company import Company
from app.models.enums import VoucherStatus
from app.services.settings import get_setting
from tally_contract.errors import ErrorCode


@dataclass(frozen=True)
class AnalyticsFilter:
    """FR-4.3. Standard figures count ACTIVE vouchers only; the include flags widen that on
    request (ACC-4.5)."""

    date_from: date
    date_to: date
    include_cancelled: bool = False
    include_missing: bool = False

    def __post_init__(self) -> None:
        if self.date_from > self.date_to:
            raise AppError(ErrorCode.VALIDATION_ERROR, "'from' is after 'to'", 422)

    @property
    def statuses(self) -> list[str]:
        return [
            VoucherStatus.ACTIVE,
            *([VoucherStatus.CANCELLED] if self.include_cancelled else []),
            *([VoucherStatus.MISSING_IN_TALLY] if self.include_missing else []),
        ]


@dataclass(frozen=True)
class MetricContext:
    company_id: uuid.UUID
    filter: AnalyticsFilter
    classes: Classes
    fy_start: date
    books_from: date | None  # openings are as at this date (D-039 #5)
    company_timezone: str
    quarter_mode: QuarterMode
    taxable_value_mode: bool  # ACC-2.2
    include_journal: bool  # D-021 #2
    returns_linkable: bool  # GATE-G26: until it passes every note is unlinked (ACC-5.5)


async def load(session: AsyncSession, ctx: CompanyContext, flt: AnalyticsFilter) -> MetricContext:
    company = await session.get(Company, ctx.company_id)
    if company is None:
        raise AppError(ErrorCode.NOT_FOUND, "Company not found", 404)
    return MetricContext(
        company_id=company.company_id,
        filter=flt,
        classes=await load_classes(session, company.company_id),
        fy_start=company.financial_year_start,
        books_from=company.books_from,
        company_timezone=company.company_timezone,
        quarter_mode=await get_setting(session, company.company_id, "analytics.quarter_mode"),
        taxable_value_mode=await get_setting(
            session, company.company_id, "analytics.taxable_value_mode"
        ),
        include_journal=await get_setting(session, company.company_id, "cashflow.include_journal"),
        returns_linkable=gate_passed("G26"),
    )
