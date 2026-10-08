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

Generated 2026-03-16 12:04 UTC by `make bench-sync`.

## Dataset

| | |
|---|---|
| Identifier | seed 8, version 1 |
| Digest | `e072b809beeade75…` |
| Vouchers / entries | 100,000 / 500,000 |
| Ledgers / stock items | 5,000 / 10,000 |
| Mock load time | 0.67 s (once, at startup) |

## Results

| Target | Budget | Measured here | Of budget |
|---|---|---|---|
| PERF-1.2 full sync | 30 min | **3.9 min** | 13% |
| PERF-1.3 incremental (500 changed) | 2 min | **0.4 min** | 18% |

## Upload volume, and what a real link would add

| | |
|---|---|
| Uploaded by the full sync | **275.9 MB** in 237 batches |
| Uploaded by the incremental | 21.78 MB |
| At SRS 17.2's 10 Mbps floor | about **3.7 min** of transfer |
| **Full sync, compute + transfer** | about **7.6 min** against a 30 min budget |

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
