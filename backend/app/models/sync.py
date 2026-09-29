"""Synchronization control (SRS 5.9) and committed upload batches (D-024)."""

import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    BigInteger,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import (
    Base,
    Money,
    Quantity,
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
    KeyListStatus,
    ReconResult,
    SyncMode,
    SyncRunStatus,
    TallyValueKind,
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
    # RECONCILIATION runs: when the comparison job recorded its results (D-048 #6)
    reconciled_at: Mapped[datetime | None]


class SyncError(Base):
    __tablename__ = "sync_errors"
    __table_args__ = (
        tenant_fk("sync_run_id", "sync_runs.sync_run_id"),
        Index(None, "sync_run_id"),
        Index(None, "company_id", "entity_type", "watermark_hold"),  # held-back check
    )

    id: Mapped[int] = bigint_pk()
    company_id: Mapped[uuid.UUID]  # D-031 (SRS 5.1-1)
    sync_run_id: Mapped[uuid.UUID]
    entity_type: Mapped[str]  # the collection for record errors
    tally_guid: Mapped[str | None]
    alter_id: Mapped[int | None] = mapped_column(BigInteger)  # of the failing record, if known
    # D-039 #7: the highest the watermark may be while this record keeps failing (its ALTERID
    # - 1, or the pre-batch watermark when unknown). Null: the error does not hold it back.
    watermark_hold: Mapped[int | None] = mapped_column(BigInteger)
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


class ReconciliationTallyValue(Base):
    """A figure Tally computed, uploaded by a RECONCILIATION run (D-048). Only the
    comparison reads it; no local figure is ever computed from it (SRS 9.1)."""

    __tablename__ = "reconciliation_tally_values"
    __table_args__ = (
        tenant_fk("sync_run_id", "sync_runs.sync_run_id"),
        enum_check("kind", TallyValueKind),
        UniqueConstraint(  # a replayed batch changes nothing; named: the default is > 63 chars
            "sync_run_id",
            "kind",
            "entity_guid",
            "voucher_type_guid",
            "period_start",
            "period_end",
            name="uq_reconciliation_tally_values_key",
        ),
    )

    id: Mapped[int] = bigint_pk()
    company_id: Mapped[uuid.UUID] = company_id_col(index=False)
    sync_run_id: Mapped[uuid.UUID]
    kind: Mapped[str]
    entity_guid: Mapped[str]  # the ledger or stock item
    voucher_type_guid: Mapped[str] = mapped_column(default="", server_default="")  # TOTAL only
    name: Mapped[str | None]
    period_start: Mapped[date]  # closings: the as-of date
    period_end: Mapped[date]
    debit: Mapped[Decimal | None] = mapped_column(Money)  # TOTAL
    credit: Mapped[Decimal | None] = mapped_column(Money)  # TOTAL
    value: Mapped[Decimal | None] = mapped_column(Quantity)  # a closing: Dr + balance, or qty
    unit: Mapped[str | None]


class ReconciliationResult(Base):
    __tablename__ = "reconciliation_results"
    __table_args__ = (
        enum_check("result", ReconResult),
        tenant_fk("sync_run_id", "sync_runs.sync_run_id"),
        Index(None, "company_id", "run_at"),
        Index(None, "sync_run_id"),
    )

    id: Mapped[int] = bigint_pk()
    company_id: Mapped[uuid.UUID] = company_id_col(index=False)
    sync_run_id: Mapped[uuid.UUID | None]  # the RECONCILIATION run compared (D-048 #8)
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


class SyncKeyList(Base):
    """A key list (GUID, ALTERID) for deletion detection, staged in chunks and evaluated once
    (SYNC-5.x, D-007, D-041). The row stays as history; its keys are deleted after evaluation."""

    __tablename__ = "sync_key_lists"
    __table_args__ = (
        UniqueConstraint("company_id", "list_id"),  # target of the keys' tenant FK
        tenant_fk("sync_run_id", "sync_runs.sync_run_id"),
        enum_check("collection_type", CollectionType),
        enum_check("status", KeyListStatus),
        Index(None, "company_id", "collection_type", "evaluated_at"),
    )

    list_id: Mapped[uuid.UUID] = mapped_column(primary_key=True)  # chosen by the Agent
    company_id: Mapped[uuid.UUID] = company_id_col(index=False)
    sync_run_id: Mapped[uuid.UUID]
    collection_type: Mapped[str]
    date_from: Mapped[date | None]  # the window; null: the whole collection
    date_to: Mapped[date | None]
    received_chunks: Mapped[list[int]] = mapped_column(
        ARRAY(Integer), default=list, server_default=text("'{}'")
    )
    final_seq: Mapped[int | None]
    status: Mapped[str] = mapped_column(
        default=KeyListStatus.RECEIVING, server_default=KeyListStatus.RECEIVING.value
    )
    keys_count: Mapped[int] = mapped_column(default=0, server_default=text("0"))
    candidates: Mapped[int] = mapped_column(default=0, server_default=text("0"))
    marked_missing: Mapped[int] = mapped_column(default=0, server_default=text("0"))
    reappeared: Mapped[int] = mapped_column(default=0, server_default=text("0"))
    missed_changes: Mapped[int] = mapped_column(default=0, server_default=text("0"))
    guard_waived: Mapped[bool] = mapped_column(default=False, server_default=text("false"))
    confirmed_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.user_id"))
    confirmed_at: Mapped[datetime | None]
    created_at: Mapped[datetime] = created_at()
    evaluated_at: Mapped[datetime | None]


class SyncKeyListKey(Base):
    __tablename__ = "sync_key_list_keys"
    __table_args__ = (
        ForeignKeyConstraint(
            ["company_id", "list_id"],
            ["sync_key_lists.company_id", "sync_key_lists.list_id"],
            ondelete="CASCADE",
        ),
    )

    list_id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    tally_guid: Mapped[str] = mapped_column(primary_key=True)
    company_id: Mapped[uuid.UUID] = company_id_col(index=False)
    alter_id: Mapped[int] = mapped_column(BigInteger)
