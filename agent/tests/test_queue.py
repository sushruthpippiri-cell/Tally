"""P7.6: the local upload queue and the uploader (AGT-2.x, D-042 #2, #6)."""

import json
import os
import stat
import sys
import threading
from pathlib import Path
from typing import Any

import pytest

from tally_agent import security
from tally_agent.backend_client import BackendClient
from tally_agent.config import AgentSettings
from tally_agent.queue import BATCH, Limits, Queue, backoff_seconds
from tally_agent.uploader import Uploader
from tally_contract.testing import assert_logged

ACCOUNT = r"NT SERVICE\TallyAgent"
RUN = "run-1"


class Clock:
    def __init__(self) -> None:
        self.now = 1_000_000.0

    def __call__(self) -> float:
        return self.now


def queue(tmp_path: Path, clock: Clock | None = None, **limits: Any) -> Queue:
    return Queue(tmp_path / "agent", ACCOUNT, Limits(**limits), clock=clock or Clock())


def add(q: Queue, name: str, collection: str, records: int = 1, run: str = RUN) -> None:
    body = {"collection_type": collection, "records": [{"n": name}] * records, "name": name}
    q.add(
        kind=BATCH,
        item_id=name,
        command_id="cmd-1",
        sync_run_id=run,
        collection=collection,
        body_json=json.dumps(body),
        record_count=records,
    )


def uploader(q: Queue, backend: Any, lost: list[str] | None = None) -> Uploader:
    record = lost.append if lost is not None else (lambda command_id: None)
    return Uploader(q, lambda: backend, threading.Event(), on_lost=record)


def client(fake_backend: Any, tmp_path: Path) -> BackendClient:
    fake_backend.running("cmd-1")
    settings = AgentSettings(backend_url=fake_backend.url, company_name="X", data_dir=tmp_path)
    return BackendClient(settings, credential=fake_backend.credential)


@pytest.mark.req("AGT-2.3")
def test_retries_back_off_from_30_seconds_doubling_to_15_minutes_with_jitter() -> None:
    limits = Limits()
    assert [backoff_seconds(n, limits, lambda: 0.5) for n in range(1, 8)] == [
        30,
        60,
        120,
        240,
        480,
        900,
        900,
    ]
    assert backoff_seconds(1, limits, lambda: 0.0) == pytest.approx(24)
    assert backoff_seconds(1, limits, lambda: 1.0) == pytest.approx(36)


@pytest.mark.req("AGT-2.1")
def test_items_upload_first_in_first_out_and_a_backing_off_head_holds_the_rest(
    tmp_path: Path, fake_backend: Any
) -> None:
    clock = Clock()
    q = queue(tmp_path, clock)
    for name in ("a", "b"):
        add(q, name, "VOUCHER")
    fake_backend.upload_failures = [(503, {"code": "X", "message": "busy"})]
    up = uploader(q, client(fake_backend, tmp_path))
    backend = client(fake_backend, tmp_path)
    assert up.step(backend) is False  # a 503: the head backs off...
    assert q.head() is None  # ...and holds "b" behind it
    clock.now += 40
    assert q.head() is not None and q.head().body["name"] == "a"  # type: ignore[union-attr]


@pytest.mark.req_partial("AGT-2.6")  # the service account itself: the installer, P7.9
def test_a_batch_that_keeps_failing_goes_to_the_dead_letter_file_with_the_rest_of_its_collection(
    tmp_path: Path, fake_backend: Any, caplog: pytest.LogCaptureFixture
) -> None:
    """AGT-2.5 and D-042 #6: after max_attempts the item and the later items of its run and
    collection are moved, never dropped, so the watermark cannot pass the gap."""
    q = queue(tmp_path, max_attempts=3, first_backoff=0)
    for name, collection in (
        ("v1", "VOUCHER"),
        ("l1", "LEDGER"),
        ("v2", "VOUCHER"),
        ("v3", "VOUCHER"),
    ):
        add(q, name, collection)
    fake_backend.upload_failures = [(503, {"code": "X", "message": "down"})] * 3
    backend = client(fake_backend, tmp_path)
    up = uploader(q, backend)
    for _ in range(3):
        up.step(backend)
    lines = (tmp_path / "agent" / "deadletter.jsonl").read_text(encoding="utf-8").splitlines()
    assert [json.loads(line)["body"]["name"] for line in lines] == ["v1", "v2", "v3"]
    assert q.status().dead_letter_count == 3
    assert_logged(caplog, "upload_dead_lettered", level="error", items=3, collection="VOUCHER")
    assert up.step(backend) is True  # the ledger batch was not held back
    assert fake_backend.paths("/agent/commands/cmd-1/batches")[-1:] and q.head() is None
    for private in ("queue.db", "deadletter.jsonl"):  # AGT-2.6
        security.check(tmp_path / "agent" / private, ACCOUNT)
        if sys.platform != "win32":
            assert stat.S_IMODE(os.stat(tmp_path / "agent" / private).st_mode) == 0o600


@pytest.mark.req("AGT-2.5")
def test_nothing_is_ever_dropped_silently(tmp_path: Path, fake_backend: Any) -> None:
    """A batch the backend can never accept (422) goes to the dead-letter file at once, and is
    counted for the heartbeat; retrying it would hold the whole queue for hours."""
    q = queue(tmp_path)
    add(q, "bad", "VOUCHER")
    fake_backend.upload_failures = [(422, {"code": "VALIDATION_ERROR", "message": "bad envelope"})]
    backend = client(fake_backend, tmp_path)
    uploader(q, backend).step(backend)
    assert q.head() is None and q.status().dead_letter_count == 1


def test_a_run_whose_command_is_over_is_dropped_as_obsolete(
    tmp_path: Path, fake_backend: Any, caplog: pytest.LogCaptureFixture
) -> None:
    """D-039, D-042 #6: the backend refuses a lost command's batches; they are re-pulled next
    run, so they are removed (counted and logged) and the executor is told to stop."""
    q = queue(tmp_path)
    for name in ("v1", "v2"):
        add(q, name, "VOUCHER")
    add(q, "other", "VOUCHER", run="run-2")
    fake_backend.upload_failures = [(409, {"code": "INVALID_COMMAND_STATE", "message": "lost"})]
    lost: list[str] = []
    backend = client(fake_backend, tmp_path)
    uploader(q, backend, lost).step(backend)
    assert lost == ["cmd-1"]
    assert q.pending(RUN) == 0 and q.pending("run-2") == 1
    assert q.status().obsolete_dropped == 2
    assert_logged(caplog, "upload_obsolete_dropped", level="warning", items=2)


def test_a_rotated_credential_pauses_uploads_without_counting_attempts(
    tmp_path: Path, fake_backend: Any
) -> None:
    q = queue(tmp_path, max_attempts=1)
    add(q, "v1", "VOUCHER")
    fake_backend.upload_failures = [(401, {"code": "CREDENTIAL_INVALID", "message": "rotated"})]
    backend = client(fake_backend, tmp_path)
    up = Uploader(q, lambda: backend, threading.Event(), idle_seconds=0)
    up._stop.wait = lambda timeout=None: False  # type: ignore[method-assign]  # no real wait
    assert up.step(backend) is False and up.paused
    assert q.head() is not None and q.status().dead_letter_count == 0  # kept, not failed


@pytest.mark.req("AGT-2.2")
def test_the_queue_is_full_at_its_record_limit_or_when_its_oldest_item_is_too_old(
    tmp_path: Path,
) -> None:
    clock = Clock()
    q = queue(tmp_path, clock, max_records=10, max_age_seconds=3600)
    add(q, "a", "VOUCHER", records=6)
    assert q.status().full is False
    add(q, "b", "VOUCHER", records=4)
    assert q.status().full is True  # 10 records
    q2 = queue(tmp_path / "other", clock, max_records=10, max_age_seconds=3600)
    add(q2, "old", "VOUCHER")
    clock.now += 3600
    status = q2.status()
    assert (status.full, status.oldest_age_seconds) == (True, 3600)  # a duration, never a time


def test_a_window_that_fails_leaves_nothing_behind(tmp_path: Path) -> None:
    q = queue(tmp_path)
    with pytest.raises(RuntimeError), q.window() as staged:
        staged.add(5, '{"alter_id": 5}')
        add(q, "inside", "VOUCHER")
        raise RuntimeError("the document turned out to be malformed")
    assert q.head() is None
    with q.window() as staged:
        assert list(staged.sorted_records()) == []


RATE_LIMITED = (
    429,
    {"code": "RATE_LIMITED", "message": "slow down", "_headers": {"Retry-After": 1}},
)


def test_a_rate_limited_batch_is_retried_and_never_dead_lettered(
    tmp_path: Path, fake_backend: Any, caplog: pytest.LogCaptureFixture
) -> None:
    """Owner (D-043): 30 answers of 429 in a row, far more than max_attempts; the batch waits
    each time, is never counted as a failure, and uploads in the end."""
    clock = Clock()
    q = queue(tmp_path, clock, max_attempts=3)
    add(q, "v1", "VOUCHER")
    fake_backend.upload_failures = [RATE_LIMITED] * 30
    backend = client(fake_backend, tmp_path)
    up = uploader(q, backend)
    for _ in range(30):
        assert up.step(backend) is False
        head = q._connect().execute("SELECT attempts FROM items").fetchone()
        assert head == (0,)  # never counted
        clock.now += 2  # past Retry-After (1 s plus up to 20% jitter)
    assert up.step(backend) is True
    assert q.head() is None and q.status().dead_letter_count == 0
    assert len(fake_backend.batches) == 1
    assert_logged(caplog, "upload_rate_limited", level="info")


def test_a_rate_limited_batch_waits_for_retry_after(tmp_path: Path, fake_backend: Any) -> None:
    clock = Clock()
    q = queue(tmp_path, clock)
    add(q, "v1", "VOUCHER")
    fake_backend.upload_failures = [
        (429, {"code": "RATE_LIMITED", "message": "x", "_headers": {"Retry-After": 7}})
    ]
    backend = client(fake_backend, tmp_path)
    uploader(q, backend).step(backend)
    clock.now += 6.9
    assert q.head() is None  # still waiting
    clock.now += 1.6  # 7 s plus the most jitter (20%) has passed
    assert q.head() is not None


def test_control_calls_wait_out_a_429(tmp_path: Path, fake_backend: Any) -> None:
    """The executor's lease, run and finish calls wait Retry-After and try again (D-043)."""
    import time

    backend = client(fake_backend, tmp_path)
    fake_backend.next_answers = [RATE_LIMITED]
    started = time.monotonic()
    answer = backend.call(
        "POST",
        "/agent/leases/acquire",
        {"sync_run_id": "r", "collection_type": "GROUP"},
        patience=5,
    )
    assert answer["collection_type"] == "GROUP"
    assert time.monotonic() - started >= 1.0  # honoured Retry-After: 1
