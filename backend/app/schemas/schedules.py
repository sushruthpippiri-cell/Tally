import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.models.enums import SyncMode


def _no_date_range(mode: SyncMode | None) -> SyncMode | None:
    if mode == SyncMode.DATE_RANGE:
        raise ValueError("a schedule has no dates, so it cannot be DATE_RANGE")
    return mode


class ScheduleCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    agent_id: uuid.UUID  # fixed at creation (RTE-1.3)
    cron_expression: str = Field(max_length=100)
    sync_mode: SyncMode
    is_active: bool = True

    _mode = field_validator("sync_mode")(_no_date_range)


class ScheduleUpdate(BaseModel):
    """agent_id cannot change (RTE-1.3): sending it is a 422."""

    model_config = ConfigDict(extra="forbid")
    cron_expression: str | None = Field(default=None, max_length=100)
    sync_mode: SyncMode | None = None
    is_active: bool | None = None

    _mode = field_validator("sync_mode")(_no_date_range)


class ScheduleOut(BaseModel):
    schedule_id: uuid.UUID
    agent_id: uuid.UUID
    agent_name: str
    cron_expression: str
    sync_mode: SyncMode
    is_active: bool
    next_fire_at: datetime | None
    created_by: uuid.UUID | None  # null: created by the system (D-023 defaults)
