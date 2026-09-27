import uuid
from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.models.enums import CollectionType, KeyListStatus, SyncMode, SyncRunStatus


class CollectionPlan(BaseModel):
    mode: Literal["INCREMENTAL", "FULL_ONLY"]  # from the validation gate (VAL-1.1/1.2)
    watermark: int  # pull ALTERID > this when not full
    full: bool  # pull everything (FULL command, FULL_ONLY collection, or never synced)
    key_list_due: bool = False  # send a key list after this collection (SYNC-5.4, D-041 #6)


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


class RunProblem(BaseModel):
    """Something the Agent could not sync (D-040 #2); recorded in sync_errors."""

    model_config = ConfigDict(extra="forbid")
    collection_type: CollectionType | None = None  # None: the whole run
    code: Literal["SYNC_LOCKED", "TALLY_EXPORT_TIMEOUT", "TALLY_UNREACHABLE"]
    message: str = Field(max_length=1000)


class FinishRequest(BaseModel):
    """How the Agent saw the run end; `close_run` decides the stored status (D-040 #1)."""

    model_config = ConfigDict(extra="forbid")
    status: Literal["COMPLETED", "FAILED"]
    problems: list[RunProblem] = Field(default_factory=list, max_length=200)
    notes: str | None = Field(default=None, max_length=2000)


class RunOut(BaseModel):
    sync_run_id: uuid.UUID
    status: SyncRunStatus
    records_fetched: int
    records_failed: int
    started_at: datetime
    ended_at: datetime | None


# --- sync status for the dashboard (P5.8, SRS 19.2) -----------------------------------------


class CollectionStatus(BaseModel):
    collection_type: CollectionType
    mode: Literal["INCREMENTAL", "FULL_ONLY"]
    label: Literal["Incremental", "Full sync only"]  # AC-12
    watermark: int
    status: str  # NEVER_SYNCED | OK | ...
    last_successful_sync_at: datetime | None
    lease_holder: str | None  # the Agent holding a live lease
    lease_expires_at: datetime | None
    held_back: int  # "sync held back by N failing records" (D-039 #7)


class RunSummary(RunOut):
    agent_id: uuid.UUID
    command_id: uuid.UUID | None
    sync_mode: SyncMode


class SyncStatusOut(BaseModel):
    collections: list[CollectionStatus]
    last_run: RunSummary | None
    warnings: list[str]


class LeaseStatus(BaseModel):
    collection_type: CollectionType
    holder_agent_id: uuid.UUID
    holder_name: str
    acquired_at: datetime | None
    expires_at: datetime | None
    live: bool  # false: expired, reclaimable by any Agent (SYNC-4.3)


class SyncErrorOut(BaseModel):
    id: int
    sync_run_id: uuid.UUID
    entity_type: str
    tally_guid: str | None
    alter_id: int | None
    error_code: str
    message: str
    watermark_hold: int | None
    created_at: datetime


class KeyListOut(BaseModel):
    """Where a key list stands (D-041 #1); `waiting_for` lists chunks still missing."""

    list_id: uuid.UUID
    collection_type: CollectionType
    status: KeyListStatus
    received_chunks: list[int]
    waiting_for: list[int]
    keys_count: int
    candidates: int
    marked_missing: int
    reappeared: int
    missed_changes: int
