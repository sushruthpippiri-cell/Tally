# EXPLAIN ANALYZE review (P16.5)

The review P16.5's plan asks for: *"`EXPLAIN ANALYZE` review of the top queries; add indexes or
materialized views only if needed, keeping one definition per metric (ACC-4.4)."*

**Outcome: no index is warranted, and the reason is worth recording** — so that the next person
who sees a sequential scan in these plans does not add one.

The figures come from `make bench-analytics` on `tally_bench` regenerated at migration **0013**
(100,000 vouchers, 500,000 entries, 5,000 ledgers, 10,000 stock items). That regeneration
mattered on its own: the database had been left at migration **0006**, so every figure taken from
it since P9 described a schema seven migrations old.

Not PERF-VAL-1 evidence: a developer Mac, PostgreSQL in Docker, one user. See
`docs/benchmarks/p16-concurrency.md` for the concurrent figure and the same caveat.

## Why the sequential scans are the right plan

Every scan in these plans has the same shape. The two that appear most often:

| Table | Rows | Filter | Kept |
|---|---|---|---|
| `voucher_entries` | 500,000 | `company_id = … AND (accounting_direction = 'CREDIT' OR (… 'DEBIT' AND subplan))` | 280,807 (56%) |
| `bill_allocations` | 130,936 | `company_id = … AND allocation_type = 'NEW_REF' \| 'AGST_REF'` | 59,000–101,000 (45–77%) |

Both filters are **`company_id` plus a low-cardinality enum**. In a single-company benchmark
`company_id` has no selectivity at all, and `accounting_direction` has two values and
`allocation_type` four. An index on either pair would be read for roughly half the table, which
is the textbook case where PostgreSQL correctly prefers a sequential scan — and it chose one.
The `voucher_entries` scan costs 98 ms of the 908 ms query and is almost entirely cached
(115,859 buffer hits against 322 reads), so the scan is not where the time goes.

`Seq Scan on voucher_types` appears 152 times and is the most eye-catching line in the file. It
is also the cheapest possible plan: the table has **ten rows**.

Adding an index here would cost write throughput on the sync path — which P16.5's own sync
benchmark measures — and buy nothing. A materialized view was considered and rejected on
sight: it would be a second definition of a metric, which is what CLAUDE.md rule 9 and ACC-4.4
exist to prevent, and it would introduce staleness into figures the Reconciliation page exists to
prove exact.

## Where the time actually goes

| Range | Dashboard summary | PERF-1.1 budget |
|---|---|---|
| Current financial year | **2,449 ms** | 3,000 ms — passes, at 82% |
| Three years | **5,121 ms** | 3,000 ms — **misses** |

The dashboard summary is the sum of the twelve figures the landing view loads. One of them
dominates:

| Metric | Current FY | 3 years | Share of the 3-year dashboard |
|---|---|---|---|
| `product_difference` total | 1,052 ms | 2,660 ms | **52%** |
| everything else, together | 1,397 ms | 2,461 ms | 48% |

`product_difference` is Total Sales Revenue minus Product-attributed Revenue (ACC-7.6): it joins
the sales entries to the inventory lines of the same vouchers and subtracts. At three years that
join produces 167,940 rows from 179,028 inputs. The work is inherent to the question, not to a
missing index.

## What would actually make the 3-year dashboard fit

Not an index: **loading `product_difference` when the user asks for it** rather than as part of
the initial dashboard. Without it the dashboard is about 1,400 ms for the current year and
2,460 ms for three years, both inside the budget, and the figure still appears the moment someone
opens Unclassified Adjustments or the Product Attribution Difference view.

That is a product decision — what the landing view loads eagerly — not a performance fix, so it
is recorded here and in `docs/progress.md` for the owner rather than made unilaterally. The
alternative, if the dashboard should keep loading everything, is to accept that the widest
selectable range is roughly 5 s and say so in the UI.

**PERF-1.1 is met for the default view and missed for the widest range.** It stays blocked in
`docs/manual-verification.md` either way: these are developer-machine figures, and PERF-VAL-1
needs the Windows machine, real Tally and a measured link.
