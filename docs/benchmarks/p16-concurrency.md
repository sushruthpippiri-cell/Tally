# Dashboard under concurrency (P16.5)

**Not PERF-VAL-1 evidence, and not yet a PERF-1.1 measurement.** This records that the load
test works and what it reported on the dataset available; the figure that counts needs the
SRS 17.2 dataset. Both gaps are stated below rather than left for a reader to notice.

## What was run

```sh
LOAD_EMAIL=… LOAD_PASSWORD=… make loadtest USERS=10 RUNTIME=30s
```

`tools/tally_tools/loadtest/locustfile.py` times **one dashboard open** — the twelve summary
calls the landing view makes — as a single user-visible event, because the user waits for the
slowest of the twelve, not their mean. A per-request average would flatter us.

## Result, 2026-10-07

| | |
|---|---|
| Users | 10, spawned immediately |
| Duration | 30 s |
| Dashboard opens | 60, **0 failures** |
| Median | 24 ms |
| 95th percentile | **49 ms** |
| Worst | 120 ms |
| PERF-1.1 budget | 3,000 ms |
| Machine | Apple M4, 16 GB, PostgreSQL 16 in Docker |

The run exits non-zero if the 95th percentile misses the budget or any dashboard open fails, so
the target is enforced rather than reported.

## Why this is not PERF-1.1 yet

**The dataset is wrong.** This ran against `make demo-data` — roughly four months of trading —
not the SRS 17.2 benchmark dataset of 100,000 vouchers, 500,000 entries, 5,000 ledgers and
10,000 stock items. Dashboard queries aggregate over the period, so the dataset size is most of
what the figure measures. A 49 ms p95 here says the query plans are not pathological and the
concurrency harness is sound; it does not say what ten users see on a real company's books.

To make it a PERF-1.1 measurement, point a backend at `tally_bench` (`make bench-data`) and run
the same command against it. That is the remaining half of P16.5.

**And it is still not PERF-VAL-1 evidence** even then: PERF-VAL-1 requires a Windows machine's
edition and build, the Tally machine's CPU and RAM, TallyPrime's version, and measured bandwidth
and latency — none of which a developer Mac can supply. `docs/benchmarks/TEMPLATE.md` lists every
field for the run on the benchmark machine.

## What it replaces

`p8-analytics.md` is a median of five **sequential** runs: it says what one query costs. Nothing
before this measured more than one user at a time, which is also what PERF-VAL-2 asks to be
recorded. The two are complementary and should not be merged.
