import uuid
from datetime import date, datetime

from packaging.version import InvalidVersion, Version
from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.models.enums import AgentStatus, SyncMode, TallyStatus


def check_version(value: str) -> str:
    try:
        Version(value)
    except InvalidVersion as exc:
        raise ValueError(f"not a version number: {value!r}") from exc
    return value


class RegistrationTokenOut(BaseModel):
    token: str  # shown once; only its hash is stored
    expires_at: datetime


class AgentConfig(BaseModel):
    """Sent at registration and on every heartbeat (D-035 #9)."""

    poll_interval_seconds: int
    progress_interval_seconds: int  # the Agent's own timer, independent of Tally (D-035 #11)
    command_lease_seconds: int
    extraction_batch_size: int
    tally_host: str
    tally_port: int
    tally_company_name: str
    expected_tdl_version: str
    collection_sync_modes: dict[str, str]  # FULL_ONLY | INCREMENTAL per collection (gates)


class RegisterRequest(BaseModel):
    token: str = Field(max_length=200)
    agent_name: str = Field(min_length=1, max_length=100)
    tally_guid: str = Field(min_length=1, max_length=200)
    tally_company_name: str = Field(min_length=1, max_length=500)
    agent_version: str = Field(max_length=50)
    tdl_version: str = Field(max_length=50)
    tally_version: str | None = Field(default=None, max_length=50)
    tally_host: str = Field(default="localhost", max_length=255)

    _versions = field_validator("agent_version", "tdl_version")(check_version)
    tally_port: int = Field(default=9000, ge=1, le=65535)


class RegisterResponse(BaseModel):
    agent_id: uuid.UUID
    credential: str  # shown once; only a salted hash is stored (SEC-2.0b)
    config: AgentConfig


class QueueStatus(BaseModel):
    records: int = Field(ge=0)
    oldest_age_seconds: int | None = Field(default=None, ge=0)
    dead_letter_count: int = Field(ge=0)
    full: bool


class HeartbeatRequest(BaseModel):
    """AGT-1.1, VER-1.1. Send `confirmed_tally_guid` whenever Tally can be read."""

    agent_version: str = Field(max_length=50)
    tdl_version: str = Field(max_length=50)
    tally_version: str | None = Field(default=None, max_length=50)
    tally_uptime_seconds: int | None = Field(default=None, ge=0)
    queue_status: QueueStatus
    tally_status: TallyStatus
    confirmed_tally_guid: str | None = Field(default=None, max_length=200)

    _versions = field_validator("agent_version", "tdl_version")(check_version)


class CommandOut(BaseModel):
    command_id: uuid.UUID
    sync_mode: SyncMode
    date_from: date | None
    date_to: date | None
    created_at: datetime


class HeartbeatResponse(BaseModel):
    status: AgentStatus
    config: AgentConfig
    command: CommandOut | None  # only for an ACTIVE Agent with nothing in progress
    warnings: list[str]


class AgentOut(BaseModel):
    """FR-4.4: one row of the Agents view."""

    agent_id: uuid.UUID
    agent_name: str
    status: AgentStatus
    agent_version: str | None
    tdl_version: str | None
    tally_version: str | None
    tally_company_name: str | None
    tally_host: str | None
    tally_port: int | None
    extraction_batch_size: int | None
    last_heartbeat_at: datetime | None
    offline_since: datetime | None
    tally_uptime_seconds: int | None
    uptime_advisory: bool  # AGT-6.4: uptime above agent.tally_uptime_advisory_days
    queue_status: dict[str, object] | None
    last_tally_status: TallyStatus | None
    tally_status_since: datetime | None
    registered_at: datetime | None
    revoked_at: datetime | None
    warnings: list[str]


class AgentsView(BaseModel):
    agents: list[AgentOut]
    warnings: list[str]  # company-level, e.g. NO_ACTIVE_SCHEDULE (D-036 #6)


class RotatedCredential(BaseModel):
    agent_id: uuid.UUID
    credential: str  # shown once (SRS 4.4 step 3); never pushed to the Agent


class TallySettingsUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    tally_host: str | None = Field(default=None, min_length=1, max_length=255)
    tally_port: int | None = Field(default=None, ge=1, le=65535)
    tally_company_name: str | None = Field(default=None, min_length=1, max_length=500)
    extraction_batch_size: int | None = Field(default=None, ge=1, le=10_000)  # AGT-4.2
