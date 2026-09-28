"""Owner (D-042 #2): a large Tally response is streamed into the queue, never held as a list of
parsed records (P4 measured about 19 KB per parsed voucher)."""

import threading
import tracemalloc
import uuid
from datetime import date
from pathlib import Path

import pytest

from tally_agent.config import AgentSettings
from tally_agent.executor import Executor
from tally_agent.protocol import AgentConfig
from tally_agent.queue import Queue
from tally_agent.tally_client import TallyError
from tally_contract.enums import CollectionType
from tally_contract.parser import iter_collection
from tally_contract.records import AlterIdWindow
from tally_tools.mock_tally import voucher_row

ACCOUNT = r"NT SERVICE\TallyAgent"
VOUCHERS = 5000
PARSED_VOUCHER_BYTES = 19_000  # P4.9's measurement


def _vouchers(n: int) -> bytes:
    rows = "".join(voucher_row(i, i, date(2024, 4, 1)).xml for i in range(1, n + 1))
    return f"<ENVELOPE><TA_VOUCHERS>{rows}</TA_VOUCHERS></ENVELOPE>".encode()


def _executor(tmp_path: Path) -> Executor:
    settings = AgentSettings(
        backend_url="http://127.0.0.1:1", company_name="Sharma Traders", data_dir=tmp_path / "agent"
    )
    config = AgentConfig(
        poll_interval_seconds=30,
        progress_interval_seconds=60,
        command_lease_seconds=300,
        extraction_batch_size=5000,
        tally_host="127.0.0.1",
        tally_port=9000,
        tally_company_name="Sharma Traders",
        expected_tdl_version="0.0.0",
        collection_sync_modes={},
    )
    executor = Executor(
        settings=settings,
        config=config,
        registered_guid="guid",
        backend=None,  # type: ignore[arg-type]  # not called while staging
        tally=None,  # type: ignore[arg-type]
        queue=Queue(settings.data_dir, ACCOUNT),
        lost=threading.Event(),
    )
    executor.command = {"command_id": str(uuid.uuid4())}
    executor.run_id, executor.batch_seq = str(uuid.uuid4()), 0
    return executor


def _stage(executor: Executor, raw: bytes) -> int:
    return executor._stage(
        iter_collection(raw, CollectionType.VOUCHER),
        CollectionType.VOUCHER,
        AlterIdWindow(from_alter_id=0, to_alter_id=VOUCHERS),
    )


def test_a_5000_voucher_window_streams_into_the_queue_without_holding_its_records(
    tmp_path: Path,
) -> None:
    executor = _executor(tmp_path)
    raw = _vouchers(VOUCHERS)
    tracemalloc.start()
    try:
        staged = _stage(executor, raw)
        _, peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()
    assert staged == VOUCHERS
    assert executor.queue.pending(executor.run_id) == VOUCHERS // 500  # 10 envelopes of 500
    accumulated = VOUCHERS * PARSED_VOUCHER_BYTES  # ~95 MB if the records were kept
    assert peak < 2 * len(raw) + 4_000_000, (
        f"peak {peak / 1e6:.1f} MB for {len(raw) / 1e6:.1f} MB of XML"
    )
    assert peak < accumulated / 5
    first = executor.queue.head()
    assert first is not None
    alter_ids = [r["alter_id"] for r in first.body["records"]]
    assert alter_ids == list(range(1, 501))  # in ALTERID order (D-026)


def test_a_malformed_document_leaves_nothing_queued(tmp_path: Path) -> None:
    """P4's rule survives streaming: records already staged from a document that turns out to
    be broken are rolled back with it."""
    executor = _executor(tmp_path)
    raw = _vouchers(50)[:-40]  # cut off mid-voucher
    with pytest.raises(TallyError) as caught:
        _stage(executor, raw)
    assert caught.value.code.value == "PARSE_ERROR"
    assert executor.queue.pending(executor.run_id) == 0
    with executor.queue.window() as staged:
        assert list(staged.sorted_records()) == []
