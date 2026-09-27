"""What a writer needs to know about the batch it is writing (P5.2)."""

import uuid
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Literal

from app.models.enums import CollectionType
from app.models.sync import SyncError
from tally_contract.errors import ErrorCode

# D-040 #1: every code that can be written to sync_errors, classified. NOT_STORED means data was
# not stored or a collection was not synced, and makes the run PARTIAL; INFO does not. A code
# missing here cannot be written (`error_row`), and tests/sync/test_error_kinds.py finds
# every code the code base can write.
SYNC_ERROR_KIND: dict[ErrorCode, Literal["NOT_STORED", "INFO"]] = {
    ErrorCode.UNKNOWN_MASTER_REFERENCE: "NOT_STORED",
    ErrorCode.DEBIT_CREDIT_IMBALANCE: "NOT_STORED",
    ErrorCode.PARSE_ERROR: "NOT_STORED",
    ErrorCode.COMPANY_MISMATCH: "NOT_STORED",
    ErrorCode.CHUNK_FAILED: "NOT_STORED",
    ErrorCode.SYNC_LOCKED: "NOT_STORED",  # a collection skipped
    ErrorCode.TALLY_EXPORT_TIMEOUT: "NOT_STORED",  # a segment not pulled
    ErrorCode.TALLY_UNREACHABLE: "NOT_STORED",
    ErrorCode.AGENT_LOST: "NOT_STORED",
    ErrorCode.STALE_ALTERID: "INFO",  # SYNC-3.2: the stored record is newer
    ErrorCode.UDF_NOT_FOUND: "INFO",  # DR-UDF-3: stored with the field null
    ErrorCode.UNSUPPORTED_ALLOCATION_TYPE: "INFO",  # stored; listed in Data Quality (P11)
}
NOT_STORED = [code.value for code, kind in SYNC_ERROR_KIND.items() if kind == "NOT_STORED"]


def not_stored(code: ErrorCode) -> bool:
    return SYNC_ERROR_KIND[code] == "NOT_STORED"


def error_row(
    *,
    company_id: uuid.UUID,
    sync_run_id: uuid.UUID,
    entity_type: str,
    code: ErrorCode,
    message: str,
    guid: str | None = None,
    alter_id: int | None = None,
    hold: int | None = None,
) -> SyncError:
    """The only way a sync_errors row is built: its code must be classified (D-040 #1)."""
    if code not in SYNC_ERROR_KIND:
        raise ValueError(f"{code} is not classified in SYNC_ERROR_KIND")
    return SyncError(
        company_id=company_id,
        sync_run_id=sync_run_id,
        entity_type=entity_type,
        tally_guid=guid,
        alter_id=alter_id,
        error_code=code.value,
        message=message[:1000],
        watermark_hold=hold,
    )


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
