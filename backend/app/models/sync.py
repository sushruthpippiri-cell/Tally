"""Synchronization control (SRS 5.9) and committed upload batches (D-024)."""

import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import BigInteger, Index, UniqueConstraint, text
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
from app.models.enums import (
    CollectionType,
    ReconResult,
    SyncMode,
    SyncRunStatus,
    WatermarkStatus,
)


class SyncWatermark(Base):
    """One per (company, collection). The lock columns are the sync lease (SRS 6.3)."""

    __tablename__ = "sync_watermarks"
    __table_args__ = (
        tenant_fk("locked_by_agent_id", "agents.agent_id"),
        enum_check("collection_type", CollectionType),
        enum_check("status", WatermarkStatus),
    )

    company_id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    collection_type: Mapped[str] = mapped_column(primary_key=True)
    last_alter_id: Mapped[int] = mapped_column(BigInteger, default=0, server_default=text("0"))
    last_successful_sync_at: Mapped[datetime | None]
    status: Mapped[str] = mapped_column(
        default=WatermarkStatus.NEVER_SYNCED, server_default=WatermarkStatus.NEVER_SYNCED.value
    )
    locked_by_agent_id: Mapped[uuid.UUID | None]
    lock_acquired_at: Mapped[datetime | None]
    lock_expires_at: Mapped[datetime | None]


class SyncRun(Base):
    __tablename__ = "sync_runs"
    __table_args__ = (
        UniqueConstraint("company_id", "sync_run_id"),  # target of tenant FKs
        tenant_fk("agent_id", "agents.agent_id"),
        tenant_fk("command_id", "agent_commands.command_id"),
        enum_check("sync_mode", SyncMode),
        enum_check("status", SyncRunStatus),
        Index(None, "company_id", "started_at"),
    )

    sync_run_id: Mapped[uuid.UUID] = uuid_pk()
    company_id: Mapped[uuid.UUID]
    agent_id: Mapped[uuid.UUID]
    command_id: Mapped[uuid.UUID | None]
    sync_mode: Mapped[str]
    started_at: Mapped[datetime]
    ended_at: Mapped[datetime | None]
    status: Mapped[str]
    records_fetched: Mapped[int] = mapped_column(default=0, server_default=text("0"))
    records_failed: Mapped[int] = mapped_column(default=0, server_default=text("0"))


class SyncError(Base):
    __tablename__ = "sync_errors"
    __table_args__ = (
        tenant_fk("sync_run_id", "sync_runs.sync_run_id"),
        Index(None, "sync_run_id"),
    )

    id: Mapped[int] = bigint_pk()
    company_id: Mapped[uuid.UUID]  # D-031 (SRS 5.1-1)
    sync_run_id: Mapped[uuid.UUID]
    entity_type: Mapped[str]
    tally_guid: Mapped[str | None]
    error_code: Mapped[str]  # tally_contract.errors.ErrorCode; no CHECK, the list grows
    message: Mapped[str]
    created_at: Mapped[datetime] = created_at()


class SyncBatch(Base):
    """A committed upload batch; a replay with the same batch_id returns the stored result."""

    __tablename__ = "sync_batches"
    __table_args__ = (
        tenant_fk("sync_run_id", "sync_runs.sync_run_id"),
        enum_check("collection_type", CollectionType),
    )

    batch_id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    company_id: Mapped[uuid.UUID]  # D-031
    sync_run_id: Mapped[uuid.UUID]
    collection_type: Mapped[str]
    batch_seq: Mapped[int]
    committed_at: Mapped[datetime]
    accepted: Mapped[int]
    rejected_stale: Mapped[int]
    error_count: Mapped[int]


class ReconciliationResult(Base):
    __tablename__ = "reconciliation_results"
    __table_args__ = (
        enum_check("result", ReconResult),
        Index(None, "company_id", "run_at"),
    )

    id: Mapped[int] = bigint_pk()
    company_id: Mapped[uuid.UUID] = company_id_col()
    run_at: Mapped[datetime]
    metric: Mapped[str]
    entity_id: Mapped[uuid.UUID | None]  # e.g. a ledger; the metric says which table
    period_start: Mapped[date]
    period_end: Mapped[date]
    tally_value: Mapped[Decimal] = mapped_column(Money)
    local_value: Mapped[Decimal] = mapped_column(Money)
    absolute_difference: Mapped[Decimal] = mapped_column(Money)
    percentage_difference: Mapped[Decimal | None] = mapped_column(Rate)
    result: Mapped[str]
