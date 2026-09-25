"""Agents, registration tokens, commands and schedules (SRS 5.4)."""

import uuid
from datetime import UTC, date, datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    ForeignKey,
    Identity,
    Index,
    LargeBinary,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, company_id_col, enum_check, tenant_fk, uuid_pk
from app.models.enums import AgentStatus, CommandStatus, CommandType, SyncMode, TallyStatus


class Agent(Base):
    __tablename__ = "agents"
    __table_args__ = (
        UniqueConstraint("company_id", "agent_name"),
        UniqueConstraint("company_id", "agent_id"),  # target of tenant FKs
        enum_check("status", AgentStatus),
        enum_check("last_tally_status", TallyStatus),
    )

    agent_id: Mapped[uuid.UUID] = uuid_pk()
    company_id: Mapped[uuid.UUID] = company_id_col(index=False)
    agent_name: Mapped[str]
    credential_hash: Mapped[str | None]  # set when registration completes (D-011)
    credential_salt: Mapped[bytes | None] = mapped_column(LargeBinary)  # D-011
    status: Mapped[str]
    tally_guid: Mapped[str | None]
    tally_company_name: Mapped[str | None]
    tally_host: Mapped[str | None]
    tally_port: Mapped[int | None]
    extraction_batch_size: Mapped[int | None]
    agent_version: Mapped[str | None]
    tdl_version: Mapped[str | None]
    tally_version: Mapped[str | None]
    tally_uptime_seconds: Mapped[int | None] = mapped_column(BigInteger)
    queue_status: Mapped[dict[str, Any] | None]
    last_heartbeat_at: Mapped[datetime | None]
    registered_at: Mapped[datetime | None]
    revoked_at: Mapped[datetime | None]
    last_tally_status: Mapped[str | None]  # D-025
    tally_status_since: Mapped[datetime | None]  # D-025


class AgentRegistrationToken(Base):
    __tablename__ = "agent_registration_tokens"

    token_id: Mapped[uuid.UUID] = uuid_pk()
    company_id: Mapped[uuid.UUID] = company_id_col()
    token_hash: Mapped[str] = mapped_column(unique=True)
    expires_at: Mapped[datetime]
    used_at: Mapped[datetime | None]
    created_by: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.user_id"))


class AgentCommand(Base):
    """`agent_id` is mandatory and immutable (RTE-1.4): a trigger rejects changing it."""

    __tablename__ = "agent_commands"
    __table_args__ = (
        UniqueConstraint("company_id", "command_id"),  # target of tenant FKs
        tenant_fk("agent_id", "agents.agent_id"),
        enum_check("command_type", CommandType),
        enum_check("sync_mode", SyncMode),
        enum_check("status", CommandStatus),
        CheckConstraint(
            "sync_mode <> 'DATE_RANGE' OR "
            "(date_from IS NOT NULL AND date_to IS NOT NULL AND date_from <= date_to)",
            name="date_range",
        ),
        Index(None, "agent_id", "status"),
        Index(None, "status", "created_at"),  # expiry job
        # D-035 #13: at most one command in progress per Agent, enforced by the database
        # (a NOT EXISTS check in the claim would not be race-proof).
        Index(
            "uq_agent_commands_one_active",
            "agent_id",
            unique=True,
            postgresql_where=text("status IN ('CLAIMED', 'RUNNING')"),
        ),
    )

    command_id: Mapped[uuid.UUID] = uuid_pk()
    company_id: Mapped[uuid.UUID] = company_id_col(index=False)
    agent_id: Mapped[uuid.UUID]
    command_type: Mapped[str]
    sync_mode: Mapped[str]
    date_from: Mapped[date | None]
    date_to: Mapped[date | None]
    status: Mapped[str]
    lease_expires_at: Mapped[datetime | None]
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.user_id")
    )  # null: scheduler
    # D-036 #1: the app clock sets created_at; seq breaks ties. Oldest = (created_at, seq).
    created_at: Mapped[datetime] = mapped_column(
        default=lambda: datetime.now(UTC), server_default=text("now()")
    )
    seq: Mapped[int] = mapped_column(BigInteger, Identity(always=True))
    claimed_at: Mapped[datetime | None]
    completed_at: Mapped[datetime | None]
    error_code: Mapped[str | None]  # D-035 #1; ErrorCode value, no CHECK (the list grows)
    error_message: Mapped[str | None]


class SyncSchedule(Base):
    __tablename__ = "sync_schedules"
    __table_args__ = (
        tenant_fk("agent_id", "agents.agent_id"),
        enum_check("sync_mode", SyncMode),
        Index(None, "next_fire_at", postgresql_where=text("is_active")),  # D-036 #2
    )

    schedule_id: Mapped[uuid.UUID] = uuid_pk()
    company_id: Mapped[uuid.UUID] = company_id_col()
    agent_id: Mapped[uuid.UUID]
    cron_expression: Mapped[str]
    sync_mode: Mapped[str]
    is_active: Mapped[bool] = mapped_column(default=True, server_default=text("true"))
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.user_id")
    )  # null: system
    next_fire_at: Mapped[datetime | None]  # D-036 #2: null while inactive
