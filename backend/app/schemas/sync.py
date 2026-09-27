import uuid
from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.models.enums import CollectionType, SyncMode, SyncRunStatus


class CollectionPlan(BaseModel):
    mode: Literal["INCREMENTAL", "FULL_ONLY"]  # from the validation gate (VAL-1.1/1.2)
    watermark: int  # pull ALTERID > this when not full
    full: bool  # pull everything (FULL command, FULL_ONLY collection, or never synced)


class RunPlan(BaseModel):
    sync_run_id: uuid.UUID
    sync_mode: SyncMode
    date_from: date | None
    date_to: date | None
    collections: dict[CollectionType, CollectionPlan]


class LeaseRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    sync_run_id: uuid.UUID
    collection_type: CollectionType


class LeaseOut(BaseModel):
    collection_type: CollectionType
    last_alter_id: int
    lock_expires_at: datetime


class ReleaseRequest(BaseModel):
    """`complete` + `start_max_alter_id`: a FULL pull of this collection finished; the
    watermark may move to the max ALTERID read BEFORE the pull began (D-039 #2)."""

    model_config = ConfigDict(extra="forbid")
    sync_run_id: uuid.UUID
    collection_type: CollectionType
    complete: bool = False
    start_max_alter_id: int | None = Field(default=None, ge=0)


class ReleaseOut(BaseModel):
    collection_type: CollectionType
    last_alter_id: int


class FinishRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    status: Literal["COMPLETED", "FAILED"]
    notes: str | None = Field(default=None, max_length=2000)


class RunOut(BaseModel):
    sync_run_id: uuid.UUID
    status: SyncRunStatus
    records_fetched: int
    records_failed: int
    started_at: datetime
    ended_at: datetime | None
