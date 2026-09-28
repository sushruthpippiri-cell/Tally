"""The local upload queue (AGT-2.x, D-042 #2, #6): a SQLite file in the Agent's restricted data
directory.

- A Tally response is streamed into a *window*: its records are staged on disk, then, only when
  the whole document parsed, read back in ALTERID order (D-026) as upload envelopes of
  `upload_batch_records` and committed in one transaction. Nothing is held in memory per record,
  and a document that fails leaves nothing behind.
- Items upload strictly first in, first out, so the backend's watermark never passes a gap.
- A failing item backs off from 30 s, doubling to 15 minutes, with jitter (AGT-2.3). After
  `max_attempts` it goes to `deadletter.jsonl` together with the later items of its run and
  collection: reported, never dropped (AGT-2.5), and re-pulled next run.
- When the backend says a run's command is no longer running (D-039), the run's items are
  obsolete: removed, counted and logged; the next run re-pulls them.
"""

import json
import random
import sqlite3
import threading
import time
import uuid
import zlib
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from tally_agent import security
from tally_contract.log import get_logger
from tally_contract.records import ParseError

log = get_logger(__name__)

BATCH, KEY_LIST_CHUNK = "BATCH", "KEY_LIST_CHUNK"


@dataclass(frozen=True)
class Limits:
    max_records: int = 50_000  # AGT-2.2
    max_age_seconds: float = 7 * 86_400
    max_attempts: int = 20  # AGT-2.5
    first_backoff: float = 30  # AGT-2.3
    max_backoff: float = 900


def backoff_seconds(
    attempts: int, limits: Limits, rng: Callable[[], float] = random.random
) -> float:
    """30 s, 60 s, 120 s ... capped at 15 minutes, each within ±20% so Agents do not align."""
    base: float = min(limits.max_backoff, limits.first_backoff * 2.0 ** (attempts - 1))
    return base * (0.8 + 0.4 * rng())


@dataclass(frozen=True)
class Item:
    id: int
    kind: str
    command_id: str
    sync_run_id: str
    collection: str | None
    body: dict[str, Any]
    record_count: int
    attempts: int


@dataclass(frozen=True)
class Status:
    records: int
    oldest_age_seconds: int | None  # a duration: the PC's clock is never sent (D-042 #5)
    dead_letter_count: int
    obsolete_dropped: int
    full: bool

    def payload(self) -> dict[str, Any]:
        return {
            "records": self.records,
            "oldest_age_seconds": self.oldest_age_seconds,
            "dead_letter_count": self.dead_letter_count,
            "full": self.full,
        }


_SCHEMA = """
CREATE TABLE IF NOT EXISTS items (
    id INTEGER PRIMARY KEY,
    kind TEXT NOT NULL,
    item_id TEXT NOT NULL UNIQUE,
    command_id TEXT NOT NULL,
    sync_run_id TEXT NOT NULL,
    collection TEXT,
    payload BLOB NOT NULL,
    record_count INTEGER NOT NULL,
    created_at REAL NOT NULL,
    attempts INTEGER NOT NULL DEFAULT 0,
    next_attempt_at REAL NOT NULL DEFAULT 0,
    last_error TEXT
);
CREATE TABLE IF NOT EXISTS staging (
    window TEXT NOT NULL,
    seq INTEGER NOT NULL,
    alter_id INTEGER NOT NULL,
    record TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_staging ON staging (window, alter_id, seq);
CREATE TABLE IF NOT EXISTS counters (name TEXT PRIMARY KEY, value INTEGER NOT NULL);
"""


class Window:
    """Records of one Tally response, staged on disk until the document is known to be whole."""

    def __init__(self, conn: sqlite3.Connection, name: str) -> None:
        self._conn, self.name = conn, name
        self.count = 0
        self.errors: list[ParseError] = []

    def add(self, alter_id: int, record_json: str) -> None:
        self._conn.execute(
            "INSERT INTO staging (window, seq, alter_id, record) VALUES (?, ?, ?, ?)",
            (self.name, self.count, alter_id, record_json),
        )
        self.count += 1

    def error(self, error: ParseError) -> None:
        self.errors.append(error)

    def sorted_records(self) -> Iterator[str]:
        cursor = self._conn.execute(
            "SELECT record FROM staging WHERE window = ? ORDER BY alter_id, seq", (self.name,)
        )
        for (record,) in cursor:
            yield record


class Queue:
    def __init__(
        self,
        data_dir: Path,
        service_account: str,
        limits: Limits | None = None,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self.limits = limits or Limits()
        self._clock = clock
        self._account = service_account
        security.private_dir(data_dir, service_account)
        self.path = data_dir / "queue.db"
        self.deadletter_path = data_dir / "deadletter.jsonl"
        self._local = threading.local()
        with self._connect() as conn:
            conn.executescript(_SCHEMA)
        security.restrict(self.path, service_account)

    def _connect(self) -> sqlite3.Connection:
        conn: sqlite3.Connection | None = getattr(self._local, "conn", None)
        if conn is None:  # one connection per thread; WAL lets the uploader read while staging
            conn = sqlite3.connect(self.path, timeout=120, isolation_level=None)
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA synchronous=NORMAL")
            self._local.conn = conn
        return conn

    # --- writing --------------------------------------------------------------------------

    @contextmanager
    def window(self) -> Iterator[Window]:
        """Stage a response; `add_envelopes` inside turns it into items. Any exception rolls
        the whole window back."""
        conn = self._connect()
        window = Window(conn, uuid.uuid4().hex)
        conn.execute("BEGIN IMMEDIATE")
        try:
            yield window
            conn.execute("DELETE FROM staging WHERE window = ?", (window.name,))
            conn.execute("COMMIT")
        except BaseException:
            conn.execute("ROLLBACK")
            raise

    def add(
        self,
        *,
        kind: str,
        item_id: str,
        command_id: str,
        sync_run_id: str,
        collection: str | None,
        body_json: str,
        record_count: int,
    ) -> None:
        """Inside a window, or on its own (autocommit)."""
        self._connect().execute(
            "INSERT OR IGNORE INTO items (kind, item_id, command_id, sync_run_id, collection, "
            "payload, record_count, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                kind,
                item_id,
                command_id,
                sync_run_id,
                collection,
                zlib.compress(body_json.encode("utf-8")),
                record_count,
                self._clock(),
            ),
        )

    # --- uploading ------------------------------------------------------------------------

    def head(self) -> Item | None:
        """The oldest item, if it is due. Strict FIFO: a backing-off head holds the rest back."""
        row = (
            self._connect()
            .execute(
                "SELECT id, kind, command_id, sync_run_id, collection, payload, record_count, "
                "attempts, next_attempt_at FROM items ORDER BY id LIMIT 1"
            )
            .fetchone()
        )
        if row is None or row[8] > self._clock():
            return None
        body = json.loads(zlib.decompress(row[5]).decode("utf-8"))
        return Item(row[0], row[1], row[2], row[3], row[4], body, row[6], row[7])

    def done(self, item: Item) -> None:
        self._connect().execute("DELETE FROM items WHERE id = ?", (item.id,))

    def failed(self, item: Item, error: str) -> None:
        attempts = item.attempts + 1
        if attempts >= self.limits.max_attempts:
            self.dead_letter(item, f"failed {attempts} times; last: {error}")
            return
        wait = backoff_seconds(attempts, self.limits)
        self._connect().execute(
            "UPDATE items SET attempts = ?, next_attempt_at = ?, last_error = ? WHERE id = ?",
            (attempts, self._clock() + wait, error[:1000], item.id),
        )
        log.warning(
            "upload_retry_scheduled", attempts=attempts, wait_seconds=round(wait), error=error
        )

    def dead_letter(self, item: Item, reason: str) -> int:
        """AGT-2.5, D-042 #6: the item and every later item of its run and collection go to the
        dead-letter file, so the watermark cannot pass the gap; the next run re-pulls them."""
        conn = self._connect()
        rows = conn.execute(
            "SELECT id, kind, item_id, command_id, sync_run_id, collection, payload, record_count "
            "FROM items WHERE sync_run_id = ? AND collection IS ? AND id >= ? ORDER BY id",
            (item.sync_run_id, item.collection, item.id),
        ).fetchall()
        with self.deadletter_path.open("a", encoding="utf-8", newline="\n") as f:
            for r in rows:
                entry = {
                    "reason": reason,
                    "kind": r[1],
                    "item_id": r[2],
                    "command_id": r[3],
                    "sync_run_id": r[4],
                    "collection": r[5],
                    "record_count": r[7],
                    "body": json.loads(zlib.decompress(r[6]).decode("utf-8")),
                }
                f.write(json.dumps(entry) + "\n")
        security.restrict(self.deadletter_path, self._account)
        conn.execute("BEGIN IMMEDIATE")
        conn.executemany("DELETE FROM items WHERE id = ?", [(r[0],) for r in rows])
        self._bump(conn, "dead_letter_count", len(rows))
        conn.execute("COMMIT")
        log.error(
            "upload_dead_lettered",
            items=len(rows),
            collection=item.collection,
            sync_run_id=item.sync_run_id,
            reason=reason,
        )
        return len(rows)

    def drop_run(self, sync_run_id: str, reason: str) -> int:
        """D-042 #6: the backend no longer accepts this run (its command was lost)."""
        conn = self._connect()
        conn.execute("BEGIN IMMEDIATE")
        dropped = conn.execute("DELETE FROM items WHERE sync_run_id = ?", (sync_run_id,)).rowcount
        self._bump(conn, "obsolete_dropped", dropped)
        conn.execute("COMMIT")
        if dropped:
            log.warning(
                "upload_obsolete_dropped", items=dropped, sync_run_id=sync_run_id, reason=reason
            )
        return dropped

    @staticmethod
    def _bump(conn: sqlite3.Connection, name: str, by: int) -> None:
        conn.execute(
            "INSERT INTO counters (name, value) VALUES (?, ?) "
            "ON CONFLICT (name) DO UPDATE SET value = value + excluded.value",
            (name, by),
        )

    # --- status ---------------------------------------------------------------------------

    def pending(self, sync_run_id: str, collection: str | None = None) -> int:
        sql = "SELECT count(*) FROM items WHERE sync_run_id = ?"
        args: tuple[Any, ...] = (sync_run_id,)
        if collection is not None:
            sql, args = sql + " AND collection IS ?", (*args, collection)
        return int(self._connect().execute(sql, args).fetchone()[0])

    def status(self) -> Status:
        conn = self._connect()
        records, oldest = conn.execute(
            "SELECT coalesce(sum(record_count), 0), min(created_at) FROM items"
        ).fetchone()
        counters = dict(conn.execute("SELECT name, value FROM counters").fetchall())
        age = None if oldest is None else max(0, int(self._clock() - oldest))
        full = records >= self.limits.max_records or (
            age is not None and age >= self.limits.max_age_seconds
        )
        return Status(
            records=int(records),
            oldest_age_seconds=age,
            dead_letter_count=int(counters.get("dead_letter_count", 0)),
            obsolete_dropped=int(counters.get("obsolete_dropped", 0)),
            full=full,
        )
