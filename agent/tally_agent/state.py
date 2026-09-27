"""What registration established (not secret): the Agent's id, its company, and the last
configuration the backend sent (AGT-3.1)."""

import os
import uuid
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict

from tally_agent import security


class AgentState(BaseModel):
    model_config = ConfigDict(extra="forbid")
    agent_id: uuid.UUID
    company_guid: str  # the registered Tally company (AGT-3.1)
    company_name: str
    backend_config: dict[str, Any] = {}  # the latest AgentConfig from the backend


def _path(data_dir: Path) -> Path:
    return data_dir / "state.json"


def load(data_dir: Path) -> AgentState | None:
    path = _path(data_dir)
    if not path.exists():
        return None
    return AgentState.model_validate_json(path.read_text(encoding="utf-8"))


def save(data_dir: Path, state: AgentState, service_account: str) -> None:
    security.private_dir(data_dir, service_account)
    path, tmp = _path(data_dir), _path(data_dir).with_suffix(".tmp")
    tmp.write_text(state.model_dump_json(indent=2) + "\n", encoding="utf-8", newline="\n")
    security.restrict(tmp, service_account)
    os.replace(tmp, path)
