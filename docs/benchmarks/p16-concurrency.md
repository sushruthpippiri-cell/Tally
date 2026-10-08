# Dashboard under concurrency (P16.5)

**PERF-1.1 is missed on the benchmark dataset under concurrency, by a wide margin.** That is the
finding; the rest of this page is how it was measured and why the earlier number was wrong.

Not PERF-VAL-1 evidence: a developer Mac, PostgreSQL in Docker, no Windows machine, no real
Tally, no measured link. PERF-1.1 stays blocked in `docs/manual-verification.md`, with this
cited as interim evidence of our own share of the budget.

## The figures

`make loadtest-bench` — 10 concurrent users, 90 s, against a backend serving `tally_bench`
(100,000 vouchers, 500,000 entries, 5,000 ledgers, 10,000 stock items; migration 0013).
One **dashboard open** is the ten calls the landing view makes, timed as one event.

| | Measured | PERF-1.1 budget |
|---|---|---|
| Dashboard opens | 74, **0 failures** | |
| Median | **6,800 ms** | 3,000 ms |
| Average | 6,883 ms | |
| 95th percentile | **11,000 ms** | 3,000 ms |
| Fastest | 4,912 ms | |

Roughly **2.3× the budget at the median and 3.7× at the 95th percentile**. The run exits non-zero
on that, so `make loadtest-bench` reports the miss rather than printing it.

For comparison, the same twelve figures measured **one at a time** with no concurrency
(`docs/benchmarks/p8-analytics.md`) sum to 2,449 ms for the current financial year. Ten users
contending for the same database turn that into about 6.8 s. Concurrency is most of the gap,
which is exactly why PERF-VAL-2 asks for the number of users to be recorded.

## Two corrections to the earlier number

`docs/benchmarks/p16-concurrency.md` previously reported **49 ms** at the 95th percentile and
said only that it was not PERF-VAL-1 evidence. It was wrong twice over, and both faults were
mine:

1. **It measured one call, not the dashboard.** The Locust task wrapped the `sales` request in
   `catch_response` and issued the other nine inside that block. `catch_response` records the
   enclosing request's *own* duration, so a figure labelled "12 summary calls" was the time of
   `sales` alone. The task now times the group itself and reports it through a custom event.
2. **It ran against the demo dataset** — four months of trading, not the SRS 17.2 size. Dashboard
   queries aggregate over the period, so dataset size is most of what the figure measures.

A number that flattering should have prompted the check at the time. It is recorded here rather
than quietly replaced, because the earlier figure appears in PR #7's description.

## Where the time goes, and the one obvious lever

From the plans in `docs/benchmarks/p16-explain-review.md`: **no index is warranted** — every
sequential scan in them is a large-fraction aggregate filtered on `company_id` plus a
low-cardinality enum, which is precisely when a sequential scan is the right plan.

One of the twelve figures dominates:

| Metric | Current FY | 3 years | Share of the 3-year dashboard |
|---|---|---|---|
| `product_difference` total | 1,052 ms | 2,660 ms | **52%** |
| everything else, together | 1,397 ms | 2,461 ms | 48% |

Loading `product_difference` **when the user opens that section** rather than as part of the
initial dashboard would roughly halve the dashboard's work. That is a product decision about what
the landing view loads eagerly, not a performance fix, so it is recorded for the owner rather
than made here — see the follow-up row in `docs/progress.md`.

## Reproducing

```sh
make bench-data        # if tally_bench is empty or behind the current migration
make loadtest-bench    # USERS=n RUNTIME=90s
```
