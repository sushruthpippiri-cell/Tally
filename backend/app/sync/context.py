"""What a writer needs to know about the batch it is writing (P5.2)."""

import uuid
from dataclasses import dataclass, field
from datetime import date, datetime

from app.models.enums import CollectionType
from tally_contract.errors import ErrorCode


@dataclass(frozen=True)
class IngestContext:
    company_id: uuid.UUID
    agent_id: uuid.UUID
    sync_run_id: uuid.UUID
    collection: CollectionType
    now: datetime
    company_guid: str | None
    books_from: date | None  # openings are stored as at this date (D-039 #5)
    snapshots: bool = False  # a stock snapshot batch: no watermark, no holds (D-040 #8)

    @property
    def entity_type(self) -> str:
        return "STOCK_SNAPSHOT" if self.snapshots else self.collection.value


@dataclass(frozen=True)
class RecordFailure:
    """A record that was not stored. It holds the watermark back (D-039 #7)."""

    guid: str | None
    alter_id: int | None
    code: ErrorCode
    message: str


@dataclass
class ChunkOutcome:
    written: int = 0  # new or updated
    unchanged: int = 0  # equal ALTERID (SYNC-3.3)
    stale: list[tuple[str, int, int]] = field(default_factory=list)  # guid, stored, incoming
    failures: list[RecordFailure] = field(default_factory=list)
