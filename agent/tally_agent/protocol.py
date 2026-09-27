"""The backend's answers, as the Agent reads them. Lenient on extra fields so a newer backend
does not break an older Agent (the backend's own schemas are the source of truth)."""

import uuid

from pydantic import BaseModel, ConfigDict


class _Lenient(BaseModel):
    model_config = ConfigDict(extra="ignore")


class AgentConfig(_Lenient):
    poll_interval_seconds: int
    progress_interval_seconds: int
    command_lease_seconds: int
    extraction_batch_size: int
    tally_host: str
    tally_port: int
    tally_company_name: str
    expected_tdl_version: str
    collection_sync_modes: dict[str, str]


class RegisterResponse(_Lenient):
    agent_id: uuid.UUID
    credential: str
    config: AgentConfig
