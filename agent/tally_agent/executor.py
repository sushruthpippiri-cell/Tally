"""Runs one sync command (P7.5, SRS 4, D-039..D-042).

preflight -> run plan -> for each collection, in dependency order: lease -> pull -> key list
(when due) -> stock snapshot (STOCK_ITEM) -> wait for its uploads -> release; then finish.

- Pulls stream from Tally into the local queue one window at a time (D-042 #2): ALTERID
  windows of `extraction_batch_size` for incremental collections (D-013; a full pull starts at
  0), date pages for full-only vouchers and DATE_RANGE commands.
- Every voucher request names its dates (D-048 #2, GATE-G37): books-beginning to
  `FULL_PULL_DATE_TO`, so post-dated vouchers come too and nothing depends on the period
  selected in Tally. A date-paged full pull goes a month at a time to today, then one page for
  everything after it.
- A window that times out is retried once as two halves (AGT-4.3); a second timeout fails
  that collection's segment, reported to the backend as TALLY_EXPORT_TIMEOUT.
- Every date comes from the backend's plan or command, in company time, never from this PC's
  clock (D-042 #5).
- While the queue is full, nothing new is pulled; uploads continue (AGT-2.4).
- The command lease is kept by the progress thread; if it is lost, the run stops and its queued
  items are dropped: the next run re-pulls them (D-042 #6).
"""

import threading
import time
import uuid
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any

from tally_agent.backend_client import BackendClient, BackendError, BackendUnavailable
from tally_agent.config import AgentSettings
from tally_agent.preflight import preflight
from tally_agent.protocol import AgentConfig
from tally_agent.queue import BATCH, KEY_LIST_CHUNK, Queue
from tally_agent.tally_client import TallyClient, TallyError, TallyTimeout
from tally_contract import requests
from tally_contract import tally_constants as tc
from tally_contract.enums import CollectionType as C
from tally_contract.errors import ErrorCode
from tally_contract.log import get_logger
from tally_contract.parser import DocumentFailure, iter_collection, iter_keys, iter_stock_closing
from tally_contract.records import (
    AlterIdWindow,
    BatchEnvelope,
    CompanyRecord,
    DateWindow,
    KeyListChunk,
    KeyRecord,
    ParseError,
)

log = get_logger(__name__)

ORDER = [C.COMPANY, C.GROUP, C.VOUCHER_TYPE, C.LEDGER, C.COST_CENTRE, C.STOCK_ITEM, C.VOUCHER]
NO_UPPER_BOUND = 2**62  # when Tally does not report the last ALTERID (G33)
KEYS_PER_CHUNK = 10_000
FIRST_PAGE_DAYS = 31


class CommandLost(Exception):
    """The command is no longer RUNNING (its lease lapsed, D-039): stop, upload nothing more."""


class SegmentTimeout(Exception):
    """AGT-4.3: a window timed out, and so did its retry at half size."""


@dataclass(frozen=True)
class Outcome:
    status: str | None  # COMPLETED | FAILED; None when the command was lost (no result is sent)
    error_code: str | None = None
    message: str | None = None


class Executor:
    def __init__(
        self,
        *,
        settings: AgentSettings,
        config: AgentConfig,
        registered_guid: str,
        backend: BackendClient,
        tally: TallyClient,
        queue: Queue,
        lost: threading.Event,
        wait: Callable[[float], None] = time.sleep,
    ) -> None:
        self.settings, self.config, self.guid = settings, config, registered_guid
        self.backend, self.tally, self.queue, self.lost, self.wait = (
            backend,
            tally,
            queue,
            lost,
            wait,
        )
        self.company_name = config.tally_company_name or settings.company_name
        self.company: CompanyRecord | None = None
        self.problems: list[dict[str, str]] = []
        self.tally_info: Any = None

    # --- the command ------------------------------------------------------------------------

    def execute(self, command: dict[str, Any]) -> Outcome:
        self.command = command
        try:  # AGT-3.2, 3.3, 5.3: before anything is pulled
            self.tally_info = preflight(self.tally, self.company_name, self.guid)
        except TallyError as exc:
            return Outcome("FAILED", exc.code.value, exc.message)
        try:
            self.plan = self.backend.call(
                "POST", f"/agent/commands/{command['command_id']}/runs", patience=5
            )
        except (BackendError, BackendUnavailable) as exc:
            log.warning("run_not_started", error=str(exc))
            return Outcome(None)
        self.run_id = self.plan["sync_run_id"]
        self.batch_seq = 0
        failure: TallyError | None = None
        try:
            for collection in ORDER:
                self._check()
                try:
                    self._collection(collection)
                except SegmentTimeout as exc:
                    self.problems.append(
                        {
                            "collection_type": collection.value,
                            "code": ErrorCode.TALLY_EXPORT_TIMEOUT.value,
                            "message": str(exc),
                        }
                    )
                except TallyError as exc:
                    failure = exc
                    if exc.code in (ErrorCode.TALLY_UNREACHABLE, ErrorCode.TALLY_SERVER_DISABLED):
                        self.problems.append(
                            {"code": ErrorCode.TALLY_UNREACHABLE.value, "message": exc.message}
                        )
                    break
            self._drain(None)
        except CommandLost:
            self.queue.drop_run(self.run_id, "command lost")
            return Outcome(None)
        except BackendUnavailable as exc:  # longer than our patience: the lease will lapse
            log.warning("backend_unreachable_mid_run", error=str(exc))
            return Outcome(None)
        status = "FAILED" if failure else "COMPLETED"
        try:
            self.backend.call(
                "POST",
                f"/agent/commands/{command['command_id']}/runs/{self.run_id}/finish",
                {"status": status, "problems": self.problems},
                patience=5,
            )
        except (BackendError, BackendUnavailable) as exc:
            log.warning("run_finish_refused", error=str(exc))
            return Outcome(None)
        if failure is not None:
            return Outcome("FAILED", failure.code.value, failure.message)
        return Outcome("COMPLETED")

    def _check(self) -> None:
        if self.lost.is_set():
            raise CommandLost()

    # --- one collection -----------------------------------------------------------------------

    def _collection(self, collection: C) -> None:
        plan = self.plan["collections"][collection.value]
        try:
            self.backend.call(
                "POST",
                "/agent/leases/acquire",
                {"sync_run_id": self.run_id, "collection_type": collection.value},
                patience=5,
            )
        except BackendError as exc:
            if exc.code == "SYNC_LOCKED":  # SYNC-4.2: skip it, note it, carry on
                log.warning("collection_locked", collection=collection.value, message=exc.message)
                self.problems.append(
                    {
                        "collection_type": collection.value,
                        "code": "SYNC_LOCKED",
                        "message": exc.message,
                    }
                )
                return
            raise CommandLost() from exc
        dated = collection == C.VOUCHER and (
            plan["mode"] == "FULL_ONLY" or self.command["sync_mode"] == "DATE_RANGE"
        )
        if collection == C.COMPANY or (plan["mode"] == "FULL_ONLY" and not dated):
            self._window(collection)  # one request: masters are small
        elif dated:
            self._date_pages(collection, *self._date_range())
            if self.command["sync_mode"] != "DATE_RANGE":  # post-dated vouchers (D-048 #2)
                self._date_page(collection, self._as_of() + timedelta(days=1), tc.FULL_PULL_DATE_TO)
        else:
            self._alter_windows(collection, 0 if plan["full"] else plan["watermark"])
        if plan.get("key_list_due") and collection != C.COMPANY:
            self._key_list(collection)
        if collection == C.STOCK_ITEM:
            self._snapshots()
        self._drain(collection)
        self.backend.call(
            "POST",
            "/agent/leases/release",
            {"sync_run_id": self.run_id, "collection_type": collection.value},
            patience=5,
        )

    def _as_of(self) -> date:
        return date.fromisoformat(self.plan["as_of"])

    def _date_range(self) -> tuple[date, date]:
        """D-042 #5: the command's window, or books-beginning to the backend's today."""
        if self.command["sync_mode"] == "DATE_RANGE":
            return date.fromisoformat(self.command["date_from"]), date.fromisoformat(
                self.command["date_to"]
            )
        return self._books_from(), self._as_of()

    def _voucher_span(self) -> tuple[date, date]:
        """D-048 #2: every voucher, post-dated ones included, whatever period Tally has
        selected: books-beginning to FULL_PULL_DATE_TO."""
        return self._books_from(), tc.FULL_PULL_DATE_TO

    def _books_from(self) -> date:
        start = self.plan.get("full_pull_from") or (
            self.company.books_from.isoformat()
            if self.company and self.company.books_from
            else None
        )
        if start is None:
            raise TallyError(
                ErrorCode.PARSE_ERROR, "Books-beginning date unknown; sync the company first"
            )
        return date.fromisoformat(start)

    def _last_alter_id(self, collection: C) -> int:
        if self.company is None:
            return NO_UPPER_BOUND
        last = (
            self.company.last_voucher_alter_id
            if collection == C.VOUCHER
            else self.company.last_master_alter_id
        )
        return NO_UPPER_BOUND if last is None else last

    def _alter_windows(self, collection: C, low: int) -> None:
        """D-013: (from, to] windows up to the last ALTERID Tally reported; each timeout is
        retried once as two halves (AGT-4.3)."""
        high, size = self._last_alter_id(collection), self.config.extraction_batch_size
        start = low
        while start < high:
            end = min(start + size, high)
            try:
                self._window(collection, alter=(start, end))
            except TallyTimeout:
                middle = start + max(1, (end - start) // 2)
                log.warning(
                    "tally_retry_half_size", collection=collection.value, window=[start, end]
                )
                try:
                    self._window(collection, alter=(start, middle))
                    if middle < end:
                        self._window(collection, alter=(middle, end))
                except TallyTimeout as exc:
                    raise SegmentTimeout(
                        f"{collection.value} ALTERID {start}-{end} timed out twice"
                    ) from exc
            start = end

    def _date_pages(self, collection: C, first: date, last: date) -> None:
        """Month-sized pages, halved when a page returns more than `extraction_batch_size`
        records."""
        days, day = FIRST_PAGE_DAYS, first
        while day <= last:
            end = min(day + timedelta(days=days - 1), last)
            count = self._date_page(collection, day, end)
            if count > self.config.extraction_batch_size and days > 1:
                days = max(1, days // 2)
            day = end + timedelta(days=1)

    def _date_page(self, collection: C, day: date, end: date) -> int:
        """One date page; a timeout is retried once as two halves (AGT-4.3)."""
        try:
            return self._window(collection, dates=(day, end))
        except TallyTimeout:
            middle = day + timedelta(days=max(0, (end - day).days // 2))
            log.warning(
                "tally_retry_half_size", collection=collection.value, dates=[str(day), str(end)]
            )
            try:
                count = self._window(collection, dates=(day, middle))
                if middle < end:
                    count += self._window(collection, dates=(middle + timedelta(days=1), end))
                return count
            except TallyTimeout as exc:
                raise SegmentTimeout(f"{collection.value} {day}..{end} timed out twice") from exc

    # --- one Tally response --------------------------------------------------------------------

    def _window(
        self,
        collection: C,
        *,
        alter: tuple[int, int] | None = None,
        dates: tuple[date, date] | None = None,
    ) -> int:
        self._wait_for_room()
        span = dates or (self._voucher_span() if collection == C.VOUCHER else None)
        raw = self.tally.export(
            requests.collection(
                collection,
                self.company_name,
                from_alter_id=alter[0] if alter else 0,
                to_alter_id=alter[1] if alter else 0,
                date_from=span[0] if span else None,
                date_to=span[1] if span else None,
            )
        )
        window: AlterIdWindow | DateWindow | None = None
        if alter is not None:
            window = AlterIdWindow(from_alter_id=alter[0], to_alter_id=alter[1])
        elif dates is not None:
            window = DateWindow(date_from=dates[0], date_to=dates[1])
        return self._stage(iter_collection(raw, collection), collection, window)

    def _snapshots(self) -> None:
        """Tally's closing stock as of the backend's today in company time (D-042 #5)."""
        self._wait_for_room()
        raw = self.tally.export(requests.stock_closing(self.company_name, self._as_of()))
        self._stage(iter_stock_closing(raw), None, None, queue_collection=C.STOCK_ITEM.value)

    def _stage(
        self,
        items: Iterator[Any],
        collection: C | None,
        window: AlterIdWindow | DateWindow | None,
        queue_collection: str | None = None,
    ) -> int:
        """Stream one response into the queue: staged on disk, committed only when the whole
        document parsed, sent in ALTERID order (D-026, D-042 #2)."""
        try:
            with self.queue.window() as staged:
                for item in items:
                    if isinstance(item, ParseError):
                        staged.error(item)
                        continue
                    if collection == C.COMPANY:
                        self.company = item
                    staged.add(getattr(item, "alter_id", 0), item.model_dump_json())
                self._envelopes(staged, collection, window, queue_collection)
                return staged.count
        except DocumentFailure as exc:
            raise TallyError(exc.error.code, exc.error.message) from exc

    def _envelopes(
        self,
        staged: Any,
        collection: C | None,
        window: AlterIdWindow | DateWindow | None,
        queue_collection: str | None,
    ) -> None:
        chunk: list[str] = []
        errors = list(staged.errors)
        size = self.settings.upload_batch_records

        def flush() -> None:
            nonlocal errors
            batch_id = uuid.uuid4()
            head = BatchEnvelope(
                collection_type=collection,
                command_id=self.command["command_id"],
                sync_run_id=self.run_id,
                batch_seq=self.batch_seq,
                batch_id=batch_id,
                window=window,
                parse_errors=errors,
            ).model_dump_json()
            body = head.replace('"records":[]', '"records":[' + ",".join(chunk) + "]", 1)
            self.queue.add(
                kind=BATCH,
                item_id=str(batch_id),
                command_id=self.command["command_id"],
                sync_run_id=self.run_id,
                collection=queue_collection or (collection.value if collection else None),
                body_json=body,
                record_count=len(chunk),
            )
            self.batch_seq += 1
            chunk.clear()
            errors = []

        for record in staged.sorted_records():
            chunk.append(record)
            if len(chunk) >= size:
                flush()
        if chunk or errors:
            flush()

    def _key_list(self, collection: C) -> None:
        """SYNC-5.1: the collection's keys from the same Collection as the pull (D-041 #2)."""
        self._wait_for_room()
        # D-048 #2: a voucher key list names its dates, and its window says so, so only
        # vouchers dated inside it can be marked missing (D-041 #3).
        span = self._voucher_span() if collection == C.VOUCHER else None
        raw = self.tally.export(
            requests.collection(
                collection,
                self.company_name,
                keys_only=True,
                date_from=span[0] if span else None,
                date_to=span[1] if span else None,
            )
        )
        window = DateWindow(date_from=span[0], date_to=span[1]) if span else None
        list_id = str(uuid.uuid4())
        try:
            with self.queue.window():
                pending: list[KeyRecord] = []
                seq = 0
                for item in iter_keys(raw):
                    if isinstance(item, ParseError):
                        continue
                    pending.append(item)
                    if len(pending) == KEYS_PER_CHUNK:
                        self._key_chunk(collection, list_id, seq, pending, window, final=False)
                        seq, pending = seq + 1, []
                self._key_chunk(collection, list_id, seq, pending, window, final=True)
        except DocumentFailure as exc:
            raise TallyError(exc.error.code, exc.error.message) from exc

    def _key_chunk(
        self,
        collection: C,
        list_id: str,
        seq: int,
        keys: list[KeyRecord],
        window: DateWindow | None,
        *,
        final: bool,
    ) -> None:
        chunk = KeyListChunk(
            collection_type=collection,
            command_id=self.command["command_id"],
            sync_run_id=self.run_id,
            list_id=list_id,
            chunk_seq=seq,
            is_final=final,
            keys=keys,
            window=window,
        )
        self.queue.add(
            kind=KEY_LIST_CHUNK,
            item_id=f"{list_id}:{seq}",
            command_id=self.command["command_id"],
            sync_run_id=self.run_id,
            collection=collection.value,
            body_json=chunk.model_dump_json(),
            record_count=len(keys),
        )

    # --- waiting ------------------------------------------------------------------------------

    def _wait_for_room(self) -> None:
        """AGT-2.4: while the queue is full, pull nothing new; the uploader keeps going."""
        reported = False
        while self.queue.status().full:
            self._check()
            if not reported:
                log.warning("queue_full", code=ErrorCode.QUEUE_FULL.value)
                reported = True
            self.wait(0.5)
        self._check()

    def _drain(self, collection: C | None) -> None:
        """A collection's lease is released, and the run finished, only once its uploads are
        in: releasing earlier would let the backend refuse them (D-039)."""
        while self.queue.pending(self.run_id, collection.value if collection else None):
            self._check()
            self.wait(0.2)
