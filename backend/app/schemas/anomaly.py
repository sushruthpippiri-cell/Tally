"""Anomaly responses (P15.5). Money goes out as strings (CLAUDE.md rule 10)."""

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Any, Literal

from pydantic import BaseModel

ReviewAction = Literal["reviewed", "not_an_issue"]


class ReviewRequest(BaseModel):
    """CLAUDE.md rule 14: every request body is a Pydantic model."""

    action: ReviewAction


class AnomalyOut(BaseModel):
    """One flag: the evidence the application computed, and separately whatever Claude wrote
    about it (FR-3.7 - the UI must keep the two apart)."""

    anomaly_id: int
    rule: str
    rule_label: str
    voucher_id: uuid.UUID
    voucher_date: date | None
    voucher_number: str | None
    party_name: str | None
    duplicate_of_voucher_id: uuid.UUID | None
    duplicate_of_voucher_number: str | None
    duplicate_of_voucher_date: date | None
    transaction_amount: Decimal | None
    historical_average: Decimal | None
    historical_max: Decimal | None
    deviation_percent: Decimal | None
    flagged_at: datetime
    explanation_status: str
    explanation_text: str | None
    explanation_unavailable_reason: str | None
    reviewed: bool
    not_an_issue: bool
    reviewed_at: datetime | None


class AnomaliesOut(BaseModel):
    """`available` is false while the feature flag is off, with a reason - the same shape
    payment behaviour uses for its gate, rather than a second disabled-section convention."""

    available: bool
    reason: str | None = None
    company_timezone: str
    anomalies: list[AnomalyOut] = []
    total_count: int = 0


class DisclosureOut(BaseModel):
    """What enabling the feature will send to Anthropic (D-055 #7). Generated from the same
    `redact()` the explainer uses, so it cannot drift from the truth."""

    model: str | None
    api_key_configured: bool
    fields_sent: list[str]
    example: dict[str, Any]
    system_prompt: str
    never_sent: list[str]


class ReasonCount(BaseModel):
    reason: str
    count: int


class ExplanationHealthOut(BaseModel):
    """D-055 #3: how often an explanation is discarded, so the model choice can be revisited
    with data rather than opinion."""

    available: int
    pending: int
    unavailable: int
    by_reason: list[ReasonCount]
