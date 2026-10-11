# Sync benchmark (P16.5)

**Not PERF-1.2 / PERF-1.3 evidence.** PERF-VAL-1 makes a benchmark valid evidence only
if it records the Windows edition and build, the Tally machine's CPU and RAM, the
TallyPrime version, and the measured bandwidth and latency of the run. This is a
developer Mac talking to a mock over loopback: **no Windows, no TallyPrime, no network**
and not the SRS 17.2 hardware.

What it does measure is **our own share of the budget** - parse, queue, upload, ingest -
which is the part we can change. PERF-1.2 and PERF-1.3 stay blocked in
`docs/manual-verification.md` on target hardware and real Tally; these figures are cited
there as interim evidence.

Generated 2026-10-11 12:04 UTC by `make bench-sync`.

## Dataset

| | |
|---|---|
| Identifier | seed 8, version 2 |
| Digest | `e072b809beeade75…` |
| Vouchers / entries | 100,000 / 500,000 |
| Ledgers / stock items | 5,000 / 10,000 |
| Mock load time | 0.59 s (once, at startup) |

## Results

| Target | Budget | Measured here | Of budget |
|---|---|---|---|
| PERF-1.2 full sync | 30 min | **3.6 min** | 12% |
| PERF-1.3 incremental (500 changed) | 2 min | **0.2 min** | 8% |

## Reconciliation at this size (REC-1.x)

The reconciliation the full sync queues, on the same 100,000 vouchers. The Agent
reads Tally's totals, key lists and closing balances from the mock; the comparison
job then checks them against what the backend holds. An engineering measurement - no
budget is set for it in SRS 17 - and, like the rest, not evidence under PERF-VAL-1.

| | |
|---|---|
| Result | **PASS** - 14,910 compared, 0 failed |
| Agent reading Tally and uploading | 12.9 s (8.09 MB) |
| Comparison job | 1.9 s |
| Not compared | {'opening balance unavailable (Data Quality)': 126} |

## Upload volume, and what a real link would add

| | |
|---|---|
| Uploaded by the full sync | **277.6 MB** in 256 batches |
| Uploaded by the incremental | 3.03 MB |
| At SRS 17.2's 10 Mbps floor | about **3.7 min** of transfer |
| **Full sync, compute + transfer** | about **7.4 min** against a 30 min budget |

That transfer time is **not** in the figures above: loopback has no meaningful cost. On a
10 Mbps office link it is additional, and it is the one part of the budget the code
cannot reduce except by sending less. A customer on a slower or contended line pays more.

## Conditions

| | |
|---|---|
| Tally | mock (`tally_tools.mock_tally --dataset`), loopback, **no extraction cost** |
| Agent and backend | same machine, same process tree |
| PostgreSQL | Docker on the same machine |
| Concurrent users | none (PERF-VAL-2) |

The missing cost that matters most is **TallyPrime's own extraction**: on a real machine
Tally reads its own data file and renders the XML, which the mock does not simulate. That
is why a figure from here cannot stand in for PERF-1.2.
