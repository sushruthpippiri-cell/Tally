import uuid
from datetime import datetime

from pydantic import BaseModel, Field


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
    tally_port: int = Field(default=9000, ge=1, le=65535)


class RegisterResponse(BaseModel):
    agent_id: uuid.UUID
    credential: str  # shown once; only a salted hash is stored (SEC-2.0b)
    config: AgentConfig
