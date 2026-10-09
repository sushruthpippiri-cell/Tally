# Home view under concurrency (PERF-1.1, P16.5)

**PERF-1.1 passes on the SRS 17.2 dataset: the home view opens in about 1.0 s at the median and
1.2 s at the 95th percentile, against a 3 s budget** — with ten users, realistic reading time,
and no failures.

These are **engineering measurements of our own share of the budget, not PERF-VAL-1 evidence**,
and PERF-1.1 stays blocked in `docs/manual-verification.md` on target hardware and hosting. The
conditions are below, because a number without them is not a number.

## What is measured

**The home view as the product requests it.** FR-4.1 lists six things on the home view: sales,
cash and bank position, receivables, payables, last sync and reconciliation status, and Agent
health. In the frontend that is `HomePage.tsx` — four analytics figures plus `/sync/status` and
`/agents` — plus the layout's one availability probe (`/analytics/payment-behaviour`, asked on
every company page to decide whether to list that nav item, FR-PAY-6). **Seven requests**, timed
together as one event, because the user waits for the slowest rather than the mean.

`tools/tests/test_loadtest_profile.py` pins the profile to `HomePage.tsx` and
`CompanyLayout.tsx`, and `frontend/src/pages/home.test.tsx` asserts the same list from the other
side, including that **`product-difference` is not requested**.

**The load model.** Ten users, each signed in on **their own account**, alternating between the
home view (4 in 5 actions) and opening one section (1 in 5), with **5–15 s of think time** between
page views. That is "ten users using the product". It is not ten users hammering one endpoint.

**The period.** The home view opens on the financial year to date (`frontend/src/lib/filters.ts`);
that is the main figure. The three-year range is the worst case a user can select.

## Results — realistic profile, 3 minutes, 10 users

| Range | Home opens | Failures | Median | p95 | p99 | Budget |
|---|---|---|---|---|---|---|
| **Financial year** (the default) | 135 | 0 | **1.0 s** | 1.2 s | 1.8 s | 3 s |
| Three years (worst case) | 140 | 0 | **1.1 s** | 1.3 s | 2.0 s | 3 s |

The slowest single request in either run is `sales`, at a 390–440 ms median and a 590–810 ms
p95; the six others are each under 300 ms at the median. Nothing in the home view is close to
the budget on its own.

## Conditions

| | |
|---|---|
| Dataset | `tally_bench`: 100,000 vouchers, 500,000 entries, 5,000 ledgers, 10,000 stock items; migration 0013 |
| Backend | uvicorn, **on the host** (macOS), one worker, scheduler off |
| Database | PostgreSQL 16 in Docker Desktop, default configuration (`shared_buffers = 128MB`) |
| Machine | Apple M4, 10 CPUs, 16 GB; Docker Desktop's VM has **10 CPUs and 8.3 GB**, no per-container limit |
| Client | Locust on the same machine, over loopback |
| SRS 17.2 | backend and database are **separate 4-vCPU machines**; the database has 16 GB |

What that does to the reading. Here the backend, the database, Docker's VM and the load
generator all share one chip. On SRS 17.2 hardware the backend and database are separate, which
helps, but each has 4 vCPUs rather than a share of 10 fast cores, which hurts, and the database's
16 GB is far more cache than 128 MB of `shared_buffers`. These do not net out to a known number.
That is the reason the figure is interim, and the reason it must not be quoted to a customer as
what their PC will do (PERF-VAL-2).

## Stress — no think time, kept separate

A different question, answered separately as asked: how much can the backend carry? Same ten
users, same dataset, but **no think time**, so each user opens the home view again the moment the
last one finishes. That is a capacity test and is not "ten users using the product".

| Range | Home opens | Failures | Median | p95 | Throughput |
|---|---|---|---|---|---|
| Financial year | 355 | 0 | 2.2 s | 2.5 s | 4.0 opens/s |
| Three years | 269 | 0 | 3.0 s | 3.6 s | 3.0 opens/s |

Read it as a ceiling. At roughly **3-4 home opens per second** the backend is saturated and the
median approaches the budget; the realistic profile arrives at **0.8 per second**, about a
quarter of that. The three-year range reaches the budget first, at ten users with no pause.

**Each stress user has their own account, and that was a correction.** The first stress run put
all ten on one account and reported 13,215 failures of 13,466 opens. Those were `429 Too Many
Requests`: the per-user rate limit (1,000/min, SEC-1.9) working as designed. It measured the
limiter, not the backend, and a second run inherited its saturated counters and was throttled
at sign-in. Each user now has `loadtest{n}@example.com`, and the counters are cleared between
runs. The limit is a property of the product - one account cannot exceed it however fast the
backend is - and the stress figure above is what the backend carries once it is not in the way.

## The cost is on the Sales page, not the home view

`product_difference` (Total Sales Revenue minus Product-attributed Revenue, ACC-7.6) is the most
expensive single figure there is, and it is rendered by the **Sales page** as its "Difference"
section, not by the home view. Measured one user at a time:

| Sales page section | Financial year | Three years |
|---|---|---|
| Sales | 197 ms | 219 ms |
| Product-attributed Revenue | 80 ms | 116 ms |
| **Difference** | **1,052 ms** | **2,660 ms** |

Difference is about 79% of that page's database work at the default range and 89% at three
years. The page does not wait on it: every `MetricSection` runs its own query with its own
loading state, so Sales and Product-attributed Revenue paint in about 0.3 s and Difference fills
in afterwards. What a user waits 1-2.7 s for is that one section.

Whether to defer it further - load it only when scrolled to, or on request - is a decision about
how that page behaves, and is recorded in `docs/progress.md` for the owner rather than made here.

## What this replaces

This page previously reported two other numbers, both wrong, and both are recorded rather than
quietly replaced because they appear in earlier PR descriptions.

| Earlier figure | What was wrong |
|---|---|
| **49 ms** (PR #7) | It timed one call, not a dashboard: the task wrapped `sales` in `catch_response` and issued the others inside the block, and `catch_response` records the enclosing request's own duration. It also ran on the demo dataset |
| **6.8 s median** (PR #9) | It measured a twelve-call set I invented in P8 — cash flow, expenses, purchases, rankings and `product_difference` — that **the home view does not request**. It also ran with 1–3 s think time and a second task in the same loop, and all ten users shared one account |

The second is the instructive one. The decision taken on it was to move `product_difference` off
the landing view; the premise was that the landing view loaded it, and it did not. There was
nothing to move. The 6.8 s described a page no user opens.

## Reproducing

```sh
make bench-data                                  # if tally_bench is empty or behind the migration
make loadtest-bench                              # realistic, financial year
make loadtest-bench FROM=2023-04-01              # three-year worst case
make loadtest-bench PROFILE=stress               # no think time; see below
```
