"""A process killed mid-voucher and mid-batch leaves no partial voucher and the watermark
where the last committed chunk put it (TEST-3.3, SYNC-6.2, DR-VE-4). A real SIGKILL of a real
process: PostgreSQL rolls back its open transaction when the connection drops."""

import asyncio
import json
import os
import signal
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import text

from app.models.enums import CollectionType as C
from tests.sync.helpers import Factory, Setup, envelope, lease, sale, setup, sync_masters, watermark

pytestmark = pytest.mark.skipif(
    sys.platform == "win32", reason="SIGKILL is POSIX; the backend runs on Linux"
)
BACKEND = Path(__file__).parents[2]

# A partial voucher: a header without entries, or a first line without its bill allocation.
PARTIAL = """
SELECT count(*) FROM vouchers v
 WHERE NOT EXISTS (SELECT 1 FROM voucher_entries e WHERE e.voucher_id = v.voucher_id)
    OR EXISTS (
        SELECT 1 FROM voucher_entries e
         WHERE e.voucher_id = v.voucher_id AND e.line_sequence = 1
           AND NOT EXISTS (SELECT 1 FROM bill_allocations b
                            WHERE b.voucher_entry_id = e.voucher_entry_id))
"""


async def _run_and_kill(tmp_path: Path, spec: dict[str, Any]) -> None:
    marker = tmp_path / "paused"
    spec_file = tmp_path / "spec.json"
    spec_file.write_text(json.dumps(spec | {"marker": str(marker)}), encoding="utf-8")
    env = os.environ | {"PYTHONPATH": str(BACKEND)}
    proc = await asyncio.create_subprocess_exec(
        sys.executable, "-m", "tests.races.crash_worker", str(spec_file), cwd=BACKEND, env=env
    )
    for _ in range(300):
        if marker.exists() or proc.returncode is not None:
            break
        await asyncio.sleep(0.1)
    assert marker.exists(), f"worker did not reach the pause point (exit {proc.returncode})"
    os.kill(proc.pid, signal.SIGKILL)
    await proc.wait()
    await asyncio.sleep(0.5)  # let PostgreSQL notice the dropped connection


async def _state(committed: Factory) -> dict[str, int]:
    async with committed() as s:

        async def one(sql: str) -> int:
            return int(await s.scalar(text(sql)) or 0)

        return {
            "vouchers": await one("SELECT count(*) FROM vouchers"),
            "entries": await one("SELECT count(*) FROM voucher_entries"),
            "allocations": await one("SELECT count(*) FROM bill_allocations"),
            "partial": await one(PARTIAL),
        }


def _spec(st: Setup, records: list[Any], pause_at: int) -> dict[str, Any]:
    return {
        "company_id": str(st.company_id),
        "agent_id": str(st.agent.agent_id),
        "command_id": str(st.command_id),
        "envelope": envelope(st, C.VOUCHER, records).model_dump_json(),
        "pause_at_voucher": pause_at,
        "now": datetime.now(UTC).isoformat(),  # the worker runs on the test's clock
    }


@pytest.mark.req("TEST-3.3", "SYNC-6.2", "DR-VE-4")
async def test_killed_mid_voucher_leaves_nothing_of_that_chunk(
    committed: Factory, tmp_path: Path
) -> None:
    st = await setup(committed, chunk_size=10)
    await sync_masters(committed, st)
    await lease(committed, st, C.VOUCHER)
    batch = [sale(f"v-{n}", n, "1180.00", number=f"S-{n}") for n in (100, 110, 120)]
    await _run_and_kill(tmp_path, _spec(st, batch, pause_at=2))
    assert await _state(committed) == {"vouchers": 0, "entries": 0, "allocations": 0, "partial": 0}
    assert await watermark(committed, st.company_id, C.VOUCHER) == 0  # unmoved


@pytest.mark.req("TEST-3.3")
async def test_killed_mid_batch_keeps_committed_chunks_and_their_watermark(
    committed: Factory, tmp_path: Path
) -> None:
    st = await setup(committed, chunk_size=2)
    await sync_masters(committed, st)
    await lease(committed, st, C.VOUCHER)
    batch = [sale(f"v-{n}", n, "1180.00", number=f"S-{n}") for n in (100, 110, 120, 130, 140)]
    await _run_and_kill(tmp_path, _spec(st, batch, pause_at=3))
    assert await _state(committed) == {"vouchers": 2, "entries": 6, "allocations": 2, "partial": 0}
    assert await watermark(committed, st.company_id, C.VOUCHER) == 110  # chunk 1's max
