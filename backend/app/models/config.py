"""Configuration, audit and optional anomaly tables (SRS 5.10, 5.11)."""

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import ForeignKey, Index, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import (
    Base,
    Money,
    Rate,
    bigint_pk,
    company_id_col,
    created_at,
    enum_check,
    tenant_fk,
    uuid_pk,
)
from app.models.enums import CollectionType, ExplanationStatus, SettingDataType, ToolCallStatus


class FeatureConfig(Base):
    __tablename__ = "feature_config"

    company_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("companies.company_id"), primary_key=True
    )
    feature_name: Mapped[str] = mapped_column(primary_key=True)
    enabled: Mapped[bool]  # boolean only (SRS 18.1)
    updated_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.user_id"))
    updated_at: Mapped[datetime] = created_at()


class CompanySetting(Base):
    """Overrides only; defaults come from the settings registry (D-031). Classification
    allow-lists hold tagged entries, never display names (D-001)."""

    __tablename__ = "company_settings"
    __table_args__ = (enum_check("data_type", SettingDataType),)

    company_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("companies.company_id"), primary_key=True
    )
    setting_key: Mapped[str] = mapped_column(primary_key=True)
    setting_value: Mapped[Any] = mapped_column(JSONB)
    data_type: Mapped[str]
    updated_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.user_id"))
    updated_at: Mapped[datetime] = created_at()


class CustomFieldMapping(Base):
    """UDF mappings (DR-UDF-1..4). mapping_id and the unique key are D-031 additions."""

    __tablename__ = "custom_field_mappings"
    __table_args__ = (
        UniqueConstraint("company_id", "collection_type", "field_key"),
        enum_check("collection_type", CollectionType),
    )

    mapping_id: Mapped[uuid.UUID] = uuid_pk()
    company_id: Mapped[uuid.UUID] = company_id_col()
    collection_type: Mapped[str]
    tally_field: Mapped[str]
    field_key: Mapped[str]
    data_type: Mapped[str]
    is_active: Mapped[bool] = mapped_column(default=True, server_default=text("true"))
    updated_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.user_id"))
    updated_at: Mapped[datetime] = created_at()


class AuditLog(Base):
    """Append-only (SEC-1.13): the app role has INSERT/SELECT only, and a trigger rejects
    UPDATE and DELETE for everyone. Written only through app/core/audit.py."""

    __tablename__ = "audit_logs"
    __table_args__ = (Index(None, "company_id", "created_at"),)

    id: Mapped[int] = bigint_pk()
    company_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("companies.company_id"))
    user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.user_id"))  # null: system
    action: Mapped[str]
    entity_type: Mapped[str]
    entity_id: Mapped[str | None]
    before_value: Mapped[dict[str, Any] | None]
    after_value: Mapped[dict[str, Any] | None]
    data_range: Mapped[dict[str, Any] | None]
    result: Mapped[str]
    created_at: Mapped[datetime] = created_at()


class AnomalyFlag(Base):
    __tablename__ = "anomaly_flags"
    __table_args__ = (
        UniqueConstraint("voucher_id", "rule_triggered"),
        tenant_fk("voucher_id", "vouchers.voucher_id"),
        tenant_fk("duplicate_of_voucher_id", "vouchers.voucher_id"),
        enum_check("explanation_status", ExplanationStatus),
    )

    id: Mapped[int] = bigint_pk()
    company_id: Mapped[uuid.UUID]
    voucher_id: Mapped[uuid.UUID]
    rule_triggered: Mapped[str]
    transaction_amount: Mapped[Decimal | None] = mapped_column(Money)
    historical_average: Mapped[Decimal | None] = mapped_column(Money)
    historical_max: Mapped[Decimal | None] = mapped_column(Money)
    deviation_percent: Mapped[Decimal | None] = mapped_column(Rate)
    duplicate_of_voucher_id: Mapped[uuid.UUID | None]
    flagged_at: Mapped[datetime] = created_at()
    explanation_text: Mapped[str | None]
    explanation_status: Mapped[str]
    reviewed: Mapped[bool] = mapped_column(default=False, server_default=text("false"))
    not_an_issue: Mapped[bool] = mapped_column(default=False, server_default=text("false"))
    reviewed_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.user_id"))
    reviewed_at: Mapped[datetime | None]


class AiToolLog(Base):
    __tablename__ = "ai_tool_log"
    __table_args__ = (enum_check("status", ToolCallStatus),)

    id: Mapped[int] = bigint_pk()
    company_id: Mapped[uuid.UUID] = company_id_col()
    tool_name: Mapped[str]
    parameters: Mapped[dict[str, Any] | None]
    result_summary: Mapped[str | None]
    status: Mapped[str]
    created_at: Mapped[datetime] = created_at()
