import uuid
from datetime import date, datetime
from typing import Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.models.enums import CommandStatus, SyncMode
from tally_contract.errors import ErrorCode


class SyncRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    sync_mode: SyncMode
    date_from: date | None = None
    date_to: date | None = None

    @model_validator(mode="after")
    def _dates(self) -> Self:
        if self.sync_mode == SyncMode.DATE_RANGE:
            if self.date_from is None or self.date_to is None:
                raise ValueError("DATE_RANGE needs date_from and date_to")
            if self.date_from > self.date_to:
                raise ValueError("date_from must not be after date_to")
        elif self.date_from is not None or self.date_to is not None:
            raise ValueError("dates are only allowed with DATE_RANGE")
        return self


class CompanySyncRequest(SyncRequest):
    agent_id: uuid.UUID | None = None  # optional: routed per RTE-1.1/1.2 and D-036 #5


class CommandStatusOut(BaseModel):
    command_id: uuid.UUID
    agent_id: uuid.UUID
    agent_name: str
    sync_mode: SyncMode
    date_from: date | None
    date_to: date | None
    status: CommandStatus
    created_at: datetime
    created_by: uuid.UUID | None  # null: a schedule
    claimed_at: datetime | None
    lease_expires_at: datetime | None
    completed_at: datetime | None
    error_code: str | None
    error_message: str | None
    waiting_label: str | None  # RTE-1.6


class ResultRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    status: CommandStatus
    error_code: ErrorCode | None = None
    error_message: str | None = Field(default=None, max_length=2000)

    @model_validator(mode="after")
    def _outcome(self) -> Self:
        if self.status == CommandStatus.FAILED:
            if self.error_code is None:
                raise ValueError("FAILED needs an error_code")
        elif self.status == CommandStatus.COMPLETED:
            if self.error_code is not None or self.error_message is not None:
                raise ValueError("COMPLETED carries no error")
        else:
            raise ValueError("status must be COMPLETED or FAILED")
        return self
