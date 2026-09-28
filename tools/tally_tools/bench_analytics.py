"""Times every metric on the benchmark database (P8, owner; dataset: tally_tools.benchmark).

For each metric, over the current financial year and over all three years of books: the
total, the monthly series (for a balance, the by-ledger breakdown instead: balances have no
series) and the first drill-down page of 50, each through `app.analytics.query` exactly as
the API calls it. Median of 5 runs after a warm-up, as `tally_app`, with return links
treated as passed (G26) so the heavier path is measured. Every statement a call sends is then
run once more under EXPLAIN (ANALYZE, BUFFERS); the report keeps the plans for the widest
range. Writes docs/benchmarks/p8-analytics.md.

    make bench-analytics
"""

import argparse
import asyncio
import functools
import platform
import statistics
import subprocess
import sys
import time
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import replace
from datetime import date
from pathlib import Path
from typing import Any

from sqlalchemy import event, select, text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from app.analytics import query
from app.analytics.context import AnalyticsFilter, MetricContext, load
from app.core.permissions import CompanyContext
from app.models.company import Company
from tally_tools.phase_report import ROOT

APP_URL = "postgresql+asyncpg://tally_app:tally_app_dev@localhost:5432/tally_bench"
REPORT = ROOT / "docs/benchmarks/p8-analytics.md"
RANGES = {
    "current FY": (date(2025, 4, 1), date(2026, 3, 31)),
    "3 years": (date(2023, 4, 1), date(2026, 3, 31)),
}
# The dashboard summary (PERF-1.1): every headline figure plus the sales series.
DASHBOARD = [
    ("sales", "total"),
    ("sales", "series"),
    ("purchases", "total"),
    ("expenses", "total"),
    ("cash_flow", "total"),
    ("cash_flow", "series"),
    ("cash_bank_position", "total"),
    ("receivables", "total"),
    ("payables", "total"),
    ("rankings", "customers top 10"),
    ("rankings", "products top 10"),
    ("product_difference", "total"),
]
Op = Callable[[], Awaitable[Any]]


def _ops(session: AsyncSession, ctx: MetricContext) -> list[tuple[str, str, Op]]:
    """(metric, op, call): every metric's total, series (for a balance, its by-ledger
    breakdown) and first drill-down page, then the P9 rankings and the product difference."""
    ops: list[tuple[str, str, Op]] = []
    for metric in query.METRICS:
        balance = getattr(query.METRICS[metric], "KIND", "flow") == "balance"
        second: Op = (
            functools.partial(query.breakdown, session, ctx, metric, "ledger_id", "ledger_name")
            if balance
            else functools.partial(query.series, session, ctx, metric, "month")
        )
        ops += [
            (metric, "total", functools.partial(query.total, session, ctx, metric)),
            (metric, "series", second),
            (
                metric,
                "drill-down",
                functools.partial(query.drilldown, session, ctx, metric, limit=50),
            ),
        ]
    rank = functools.partial(query.ranking, session, ctx, n=10)
    ops += [
        (
            "rankings",
            "customers top 10",
            functools.partial(rank, "customer_revenue", ("party_id",), "party_name"),
        ),
        (
            "rankings",
            "products top 10",
            functools.partial(rank, "product_revenue", ("stock_item_id",), "stock_item_name"),
        ),
        (
            "rankings",
            "products by quantity top 10",
            functools.partial(
                rank,
                "product_revenue",
                ("stock_item_id", "unit"),
                "stock_item_name",
                measure="quantity",
            ),
        ),
        ("product_difference", "total", functools.partial(query.product_difference, session, ctx)),
    ]
    return ops


async def measure(url: str, runs: int) -> tuple[list[dict[str, Any]], dict[str, str]]:
    engine = create_async_engine(url)
    sent: list[tuple[str, Any]] = []
    recording = False

    @event.listens_for(engine.sync_engine, "before_cursor_execute")
    def _capture(_c: Any, _cur: Any, statement: str, params: Any, _ctx: Any, _many: Any) -> None:
        if recording:
            sent.append((statement, params))

    results: list[dict[str, Any]] = []
    async with AsyncSession(engine) as session:
        env = {"postgres": str(await session.scalar(text("select version()")))}
        company_id = await session.scalar(select(Company.company_id))
        if company_id is None:
            raise SystemExit("tally_bench is empty: run `make bench-data` first")
        user = CompanyContext(company_id, uuid.uuid4(), frozenset())
        for label, (start, end) in RANGES.items():
            ctx = replace(
                await load(session, user, AnalyticsFilter(start, end)), returns_linkable=True
            )
            for metric, op, call in _ops(session, ctx):
                sent.clear()
                recording = True
                await call()  # warm-up; records the statements
                recording = False
                statements = list(sent)
                times = []
                for _ in range(runs):
                    t0 = time.perf_counter()
                    await call()
                    times.append((time.perf_counter() - t0) * 1000)
                plans = []
                conn = await session.connection()
                for statement, params in statements:
                    plan = await conn.exec_driver_sql(
                        "EXPLAIN (ANALYZE, BUFFERS) " + statement, params
                    )
                    plans.append("\n".join(r[0] for r in plan))
                results.append(
                    {
                        "range": label,
                        "metric": metric,
                        "op": op,
                        "ms": statistics.median(times),
                        "plans": plans,
                    }
                )
                sys.stdout.write(f"{label:<10} {metric:<26} {op:<10} {results[-1]['ms']:8.1f} ms\n")
    await engine.dispose()
    return results, env


def _machine() -> str:
    def sysctl(key: str) -> str:
        try:
            return subprocess.run(
                ["sysctl", "-n", key], capture_output=True, text=True, check=True
            ).stdout.strip()
        except (OSError, subprocess.CalledProcessError):
            return "?"

    mem = sysctl("hw.memsize")
    ram = f"{int(mem) / 2**30:.0f} GB" if mem.isdigit() else "?"
    return f"{platform.platform()}, {sysctl('machdep.cpu.brand_string')}, {ram} RAM"


def render(results: list[dict[str, Any]], env: dict[str, str], counts: dict[str, int]) -> str:
    lines = [
        "# Analytics timings at SRS 17.2 size (P8, P9)",
        "",
        "Generated by `make bench-analytics` on the `make bench-data` dataset (seed 8). "
        "**Not PERF-VAL-1 evidence**: a developer machine, PostgreSQL in Docker, one user "
        "(PERF-VAL-2); it is a check of the query design before later phases build on it.",
        "",
        f"- Machine: {_machine()}",
        f"- PostgreSQL: {env['postgres']}",
        "- Rows: " + ", ".join(f"{t} {n:,}" for t, n in counts.items()),
        "- Median of 5 runs after a warm-up, as `tally_app`, G26 treated as passed. "
        '"series" is the monthly series; for balances, the by-ledger breakdown.',
        "",
        "## Timings (ms)",
        "",
        "| Metric | Op | " + " | ".join(RANGES) + " |",
        "|---|---|" + "---:|" * len(RANGES),
    ]
    by = {(r["range"], r["metric"], r["op"]): r for r in results}
    for metric, op in dict.fromkeys((r["metric"], r["op"]) for r in results):
        cells = " | ".join(f"{by[(rng, metric, op)]['ms']:.0f}" for rng in RANGES)
        lines.append(f"| {metric} | {op} | {cells} |")
    dash = {rng: sum(by[(rng, m, op)]["ms"] for m, op in DASHBOARD) for rng in RANGES}
    lines.append(
        "| **dashboard summary** (PERF-1.1, ≤ 3,000) | "
        + ", ".join(f"{m} {op}" for m, op in DASHBOARD)
        + " | "
        + " | ".join(f"**{v:.0f}**" for v in dash.values())
        + " |"
    )
    worst = list(RANGES)[-1]
    lines += ["", f"## EXPLAIN (ANALYZE, BUFFERS), {worst}", ""]
    for r in (r for r in results if r["range"] == worst):
        for i, plan in enumerate(r["plans"], 1):
            lines += [
                f"### {r['metric']} — {r['op']} — {r['range']} ({i}/{len(r['plans'])})",
                "",
                "```",
                plan,
                "```",
                "",
            ]
    return "\n".join(lines) + "\n"


async def _counts(url: str) -> dict[str, int]:
    engine = create_async_engine(url)
    async with engine.connect() as conn:
        counts = {
            t: int(await conn.scalar(text(f"select count(*) from {t}")) or 0)
            for t in ("vouchers", "voucher_entries", "voucher_items", "ledgers", "stock_items")
        }
    await engine.dispose()
    return counts


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m tally_tools.bench_analytics")
    parser.add_argument("--url", default=APP_URL)
    parser.add_argument("--runs", type=int, default=5)
    parser.add_argument("--out", type=Path, default=REPORT)
    args = parser.parse_args(argv)
    results, env = asyncio.run(measure(args.url, args.runs))
    counts = asyncio.run(_counts(args.url))
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(render(results, env, counts), encoding="utf-8", newline="\n")
    sys.stdout.write(f"wrote {args.out}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
