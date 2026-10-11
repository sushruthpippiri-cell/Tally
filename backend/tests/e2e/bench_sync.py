"""PERF-1.2 and PERF-1.3: a full and an incremental sync of the benchmark dataset (P16.5).

    make dataset            # once: writes dataset/ (100,000 vouchers as Tally XML)
    make bench-sync

**Not named `test_*` on purpose.** It takes minutes and must never run in `make check` or CI, but
it needs `backend/tests/e2e/harness.py` and the `committed` fixture, which only exist inside this
conftest's tree - so it lives here and is collected only when the Makefile names the file.

**What a figure from this proves, and what it does not.** This is a developer machine talking to
a mock over loopback. It is **not** PERF-1.1/1.2/1.3 evidence under PERF-VAL-1: no Windows
machine, no TallyPrime extraction time, no >= 10 Mbps link, not the SRS 17.2 hardware. What it
measures is **our own share of the budget** - parse, queue, upload, ingest - which is the part we
can change. The report records the conditions and the megabytes uploaded, so the transfer time a
real 10 Mbps link would add can be estimated rather than guessed.
"""

import json
import os
import re
import time
from collections import Counter
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx
import pytest
import time_machine
from sqlalchemy import func, select

from app.jobs.reconciliation import reconcile_runs
from app.jobs.runner import LOCK_RECONCILE_RUNS, run_exclusive
from app.models.agents import AgentCommand
from app.models.enums import RoleName
from app.models.vouchers import Voucher, VoucherEntry
from tally_agent.backend_client import BackendClient
from tally_agent.cli import app as agent_cli
from tally_tools import dataset_gen
from tally_tools.mock_tally import MockConfig, Row, load_dataset, running
from tests.e2e.harness import Server, Uploading, _agent, _run, start_server
from tests.factories import auth_header, make_company, make_registration_token, make_user
from tests.sync.helpers import Factory


def _render(t: dict[str, Any]) -> str:
    """The report, with the conditions beside every figure.

    A reader who takes a number out of here without the conditions would be quoting a
    developer Mac as if it were a customer's PC, so the caveat is the first thing on the page
    and the 10 Mbps estimate is spelled out rather than left as an exercise.
    """
    full, incr = t.get("full", {}), t.get("incremental", {})
    megabytes = full.get("megabytes_uploaded", 0)
    # 10 Mbps is SRS 17.2's floor; 1 MB takes about 0.8 s at that rate with overhead.
    transfer = megabytes * 8 / 10 if megabytes else 0
    lines = [
        "# Sync benchmark (P16.5)",
        "",
        "**Not PERF-1.2 / PERF-1.3 evidence.** PERF-VAL-1 makes a benchmark valid evidence only",
        "if it records the Windows edition and build, the Tally machine's CPU and RAM, the",
        "TallyPrime version, and the measured bandwidth and latency of the run. This is a",
        "developer Mac talking to a mock over loopback: **no Windows, no TallyPrime, no network**",
        "and not the SRS 17.2 hardware.",
        "",
        "What it does measure is **our own share of the budget** - parse, queue, upload, ingest -",
        "which is the part we can change. PERF-1.2 and PERF-1.3 stay blocked in",
        "`docs/manual-verification.md` on target hardware and real Tally; these figures are cited",
        "there as interim evidence.",
        "",
        f"Generated {time.strftime('%Y-%m-%d %H:%M', time.gmtime())} UTC by `make bench-sync`.",
        "",
        "## Dataset",
        "",
        "| | |",
        "|---|---|",
        f"| Identifier | seed {t['dataset']['seed']}, version {t['dataset']['version']} |",
        f"| Digest | `{t['dataset']['sha256'][:16]}…` |",
        f"| Vouchers / entries | {t['rows']['vouchers']:,} / {t['rows']['voucher_entries']:,} |",
        f"| Ledgers / stock items | {t['rows']['ledgers']:,} / {t['rows']['stock_items']:,} |",
        f"| Mock load time | {t['mock_load_seconds']} s (once, at startup) |",
        "",
        "## Results",
        "",
        "| Target | Budget | Measured here | Of budget |",
        "|---|---|---|---|",
    ]
    if full:
        lines.append(
            f"| PERF-1.2 full sync | 30 min | **{full['seconds'] / 60:.1f} min** "
            f"| {full['seconds'] / 1800:.0%} |"
        )
    if incr:
        lines.append(
            f"| PERF-1.3 incremental ({incr['changed']} changed) | 2 min "
            f"| **{incr['seconds'] / 60:.1f} min** | {incr['seconds'] / 120:.0%} |"
        )
    rec = t.get("reconciliation")
    if rec:
        lines += [
            "",
            "## Reconciliation at this size (REC-1.x)",
            "",
            "The reconciliation the full sync queues, on the same 100,000 vouchers. The Agent",
            "reads Tally's totals, key lists and closing balances from the mock; the comparison",
            "job then checks them against what the backend holds. An engineering measurement - no",
            "budget is set for it in SRS 17 - and, like the rest, not evidence under PERF-VAL-1.",
            "",
            "| | |",
            "|---|---|",
            f"| Result | **{rec['overall']}** - {rec['compared']:,} compared, "
            f"{rec['failed']} failed |",
            f"| Agent reading Tally and uploading | {rec['agent_seconds']} s "
            f"({rec['megabytes_uploaded']} MB) |",
            f"| Comparison job | {rec['compare_seconds']} s |",
            f"| Not compared | {rec['not_compared'] or 'none'} |",
        ]
        if rec["failures"]:
            lines += ["", "Failing rows (first 20):", ""]
            lines += [f"- {m} `{n}`: Tally {tv}, local {lv}" for m, n, tv, lv in rec["failures"]]
    lines += [
        "",
        "## Upload volume, and what a real link would add",
        "",
        "| | |",
        "|---|---|",
        f"| Uploaded by the full sync | **{megabytes} MB** in {full.get('batches', 0)} batches |",
        f"| Uploaded by the incremental | {incr.get('megabytes_uploaded', 0)} MB |",
        f"| At SRS 17.2's 10 Mbps floor | about **{transfer / 60:.1f} min** of transfer |",
        (
            f"| **Full sync, compute + transfer** | about "
            f"**{(full.get('seconds', 0) + transfer) / 60:.1f} min** against a 30 min budget |"
        ),
        "",
        "That transfer time is **not** in the figures above: loopback has no meaningful cost. On a",
        "10 Mbps office link it is additional, and it is the one part of the budget the code",
        "cannot reduce except by sending less. A customer on a slower or contended line pays more.",
        "",
        "## Conditions",
        "",
        "| | |",
        "|---|---|",
        "| Tally | mock (`tally_tools.mock_tally --dataset`), loopback, **no extraction cost** |",
        "| Agent and backend | same machine, same process tree |",
        "| PostgreSQL | Docker on the same machine |",
        "| Concurrent users | none (PERF-VAL-2) |",
        "",
        "The missing cost that matters most is **TallyPrime's own extraction**: on a real machine",
        "Tally reads its own data file and renders the XML, which the mock does not simulate. That",
        "is why a figure from here cannot stand in for PERF-1.2.",
        "",
    ]
    return "\n".join(lines)


DATASET = Path(os.environ.get("BENCH_DATASET", "dataset"))
REPORT = Path(__file__).parents[3] / "docs/benchmarks/p16-sync.md"
EDITS = 500  # PERF-1.3's "about 500 changed records"

# A 100,000-voucher sync takes four minutes by design; the suite-wide per-test timeout (60 s, 120 s
# for e2e) would kill it. Zero disables the limit for this module only.
pytestmark = pytest.mark.timeout(0)

__all__ = ["start_server"]


@pytest.fixture(autouse=True)
def after_the_books_end() -> Iterator[None]:
    """The suite's clock is mid-books (2026-03-16); the dataset's books end 2026-03-31, and
    Tally's closing balances in it are for a date after that. Reconciliation compares as of
    "today", so today has to be after the books end - as it is on any real day."""
    with time_machine.travel(datetime(2026, 10, 11, 12, tzinfo=UTC), tick=True):
        yield


def _touch(config: MockConfig, count: int) -> int:
    """Raise the ALTERID of `count` vouchers, as a Tally edit does.

    The dataset's GUIDs are UUIDs, so `mock_tally.edit_voucher` (which derives a voucher number
    from a `v-N` GUID) does not apply. Re-stamping the ALTERID is what the Agent actually keys
    its incremental window on.
    """
    rows = config.data["TA_Vouchers"]
    high = max(r.alter_id for r in rows)
    changed = {}
    for i, row in enumerate(rows[:count], 1):
        xml = re.sub(r"<ALTERID>\d+</ALTERID>", f"<ALTERID>{high + i}</ALTERID>", row.xml, count=1)
        changed[row.guid] = Row(row.guid, high + i, xml, row.day)
    config.data["TA_Vouchers"] = [changed.get(r.guid, r) for r in rows]
    company = config.data["TA_Company"][0]
    config.data["TA_Company"] = [
        Row(
            company.guid,
            company.alter_id,
            re.sub(
                r"<LASTVOUCHERALTERID>\d+</LASTVOUCHERALTERID>",
                f"<LASTVOUCHERALTERID>{high + len(changed)}</LASTVOUCHERALTERID>",
                company.xml,
            ),
            company.day,
        )
    ]
    return len(changed)


class _Meter:
    """Totals the bytes the Agent uploads, for PERF-VAL-1's bandwidth field.

    Patches `BackendClient.call` on the **class**, not by wrapping the instance. A proxy object
    was the first attempt and it broke the Agent: the uploader's client stopped authenticating
    (`credential_invalid`) and the command was abandoned, so the instrumentation would have been
    measuring its own damage. Patching the method leaves the client exactly itself.
    """

    def __init__(self) -> None:
        self.uploaded = 0
        self.batches = 0
        self._original: Any = None

    def __enter__(self) -> "_Meter":
        meter = self
        self._original = BackendClient.call

        def counting(
            client: Any, method: str, path: str, body: Any = None, *args: Any, **kw: Any
        ) -> Any:
            if body is not None and path.endswith("/batches"):
                meter.uploaded += len(json.dumps(body, default=str).encode())
                meter.batches += 1
            return meter._original(client, method, path, body, *args, **kw)

        BackendClient.call = counting  # type: ignore[method-assign]
        return self

    def __exit__(self, *_: object) -> None:
        BackendClient.call = self._original  # type: ignore[method-assign]


async def _clean() -> None:
    """Remove every company-scoped row, exactly as the `committed` fixture's teardown does -
    through the **owner** role, because the app role has no TRUNCATE (SEC-1.15)."""
    from sqlalchemy import text
    from sqlalchemy.ext.asyncio import create_async_engine

    from app.core.config import get_settings
    from tests.conftest import committed_database_urls

    _, owner_url = committed_database_urls(get_settings())
    engine = create_async_engine(owner_url.replace("+psycopg", "+asyncpg"))
    try:
        async with engine.begin() as conn:
            await conn.execute(text("TRUNCATE companies, users CASCADE"))
    finally:
        await engine.dispose()


async def _counts(committed: Factory) -> tuple[int, int]:
    async with committed() as s:
        return (
            int(await s.scalar(select(func.count()).select_from(Voucher)) or 0),
            int(await s.scalar(select(func.count()).select_from(VoucherEntry)) or 0),
        )


async def _last_completed_mode(committed: Factory) -> str:
    """Which sync mode the Agent most recently completed. The Agent runs the oldest command, so a
    command queued behind another (a FULL sync queues a RECONCILIATION) is not the next one it
    runs; a figure for "the incremental" that was really the reconciliation looks just like one."""
    async with committed() as s:
        return str(
            await s.scalar(
                select(AgentCommand.sync_mode)
                .where(AgentCommand.completed_at.is_not(None))
                .order_by(AgentCommand.completed_at.desc())
                .limit(1)
            )
        )


def _reconciliation(server: Server, company: Any, owner: Any) -> dict[str, Any]:
    r = httpx.get(
        f"{server.url}/companies/{company.company_id}/reconciliation",
        params={"only_failures": True, "page_size": 200},
        headers=auth_header(owner),
        trust_env=False,
        timeout=120,
    )
    assert r.status_code == 200, r.text
    body: dict[str, Any] = r.json()
    return body


def _sync(server: Server, company: Any, owner: Any, mode: str) -> None:
    r = httpx.post(
        f"{server.url}/companies/{company.company_id}/sync",
        json={"sync_mode": mode},
        headers=auth_header(owner),
        trust_env=False,
    )
    assert r.status_code == 201, r.text


async def test_full_then_incremental_sync_of_the_benchmark_dataset(
    committed: Factory, start_server: Any, tmp_path: Path
) -> None:
    if not (DATASET / dataset_gen.MANIFEST).is_file():
        pytest.skip(f"no dataset at {DATASET}: run `make dataset` first")
    manifest = json.loads((DATASET / dataset_gen.MANIFEST).read_text(encoding="utf-8"))
    name = manifest["company"]["name"]

    # Start from a known state. A benchmark that inherits an interrupted run's rows is not
    # measuring an initial sync, and the first attempt at this failed on the company left behind
    # by a run that had been killed.
    await _clean()

    load_started = time.perf_counter()
    mock = load_dataset(DATASET)
    load_seconds = time.perf_counter() - load_started

    with running(mock) as url:
        tally_port = int(url.rsplit(":", 1)[1])
        server = start_server()
        async with committed() as s:
            company = await make_company(s, name=name, tally_guid=manifest["company"]["guid"])
            owner = await make_user(s, company, RoleName.OWNER)
            token = await make_registration_token(s, company, owner)
            await s.commit()

        from typer.testing import CliRunner

        result = CliRunner().invoke(
            agent_cli,
            [
                "register", "--token", token, "--name", "Benchmark",
                "--backend-url", server.url, "--company", name,
                "--tally-host", "127.0.0.1", "--tally-port", str(tally_port),
                "--data-dir", str(tmp_path / "agent"),
            ],
        )  # fmt: skip
        assert result.exit_code == 0, result.output

        agent = _agent(tmp_path / "agent", tally_port)
        meter = _Meter().__enter__()
        uploading = Uploading(agent)
        timings: dict[str, Any] = {
            "dataset": {k: manifest[k] for k in ("seed", "version", "sha256")},
            "rows": manifest["database_rows"],
            "mock_load_seconds": round(load_seconds, 2),
        }
        try:
            # PERF-1.2
            started = time.perf_counter()
            _sync(server, company, owner, "FULL")
            outcome = await _run(agent)
            full_seconds = time.perf_counter() - started
            vouchers, entries = await _counts(committed)
            timings["full"] = {
                "status": outcome.status,
                "seconds": round(full_seconds, 1),
                "vouchers": vouchers,
                "entries": entries,
                "megabytes_uploaded": round(meter.uploaded / 1e6, 1),
                "batches": meter.batches,
            }
            assert outcome.status == "COMPLETED", outcome
            assert vouchers == manifest["database_rows"]["vouchers"]

            assert await _last_completed_mode(committed) == "FULL"

            # REC-1.x at the SRS 17.2 size: the reconciliation the FULL sync queued. The Agent
            # reads Tally's totals and key lists (the mock answers from the same 100,000
            # vouchers), then the comparison job runs. Recorded and reported, never asserted.
            before = meter.uploaded
            started = time.perf_counter()
            outcome = await _run(agent)
            agent_seconds = time.perf_counter() - started
            assert outcome.status == "COMPLETED", outcome
            assert await _last_completed_mode(committed) == "RECONCILIATION"
            started = time.perf_counter()
            await run_exclusive(LOCK_RECONCILE_RUNS, reconcile_runs, committed)
            compare_seconds = time.perf_counter() - started
            result = _reconciliation(server, company, owner)
            timings["reconciliation"] = {
                "agent_seconds": round(agent_seconds, 1),
                "compare_seconds": round(compare_seconds, 1),
                "megabytes_uploaded": round((meter.uploaded - before) / 1e6, 2),
                "overall": result["run"]["overall"],
                "compared": result["run"]["compared"],
                "failed": result["run"]["failed"],
                "failures": [
                    (r["metric"], r["entity_name"], r["tally_value"], r["local_value"])
                    for r in result["rows"][:20]
                ],
                "not_compared": dict(Counter(n["reason"] for n in result["not_compared"])),
            }

            # PERF-1.3
            before = meter.uploaded
            changed = _touch(mock, EDITS)
            started = time.perf_counter()
            _sync(server, company, owner, "INCREMENTAL")
            outcome = await _run(agent)
            incremental_seconds = time.perf_counter() - started
            timings["incremental"] = {
                "status": outcome.status,
                "seconds": round(incremental_seconds, 1),
                "changed": changed,
                "megabytes_uploaded": round((meter.uploaded - before) / 1e6, 2),
            }
            assert outcome.status == "COMPLETED", outcome
            assert await _last_completed_mode(committed) == "INCREMENTAL"
        finally:
            uploading.close()
            meter.__exit__()
            REPORT.parent.mkdir(parents=True, exist_ok=True)
            REPORT.write_text(_render(timings), encoding="utf-8", newline="\n")
    # Reported, never asserted: see this module's docstring on what the figure proves.
    print(json.dumps(timings, indent=2))  # noqa: T201 - the benchmark's own output
