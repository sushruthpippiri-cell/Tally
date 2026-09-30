# Progress log

Claude Code updates this at the end of every session. Newest entries at the top of each section.

## Current phase
P12 (stock analytics) — **complete** 2026-09-30. CI green (`check` 36712395193; `capture-kit` and `agent-windows` not triggered, last green 36539892090 / 36534423546). Local suite PASS ([phase-12](test-reports/phase-12.md), 1,438 tests: 1,435 passed, 3 skipped — Windows-only; 90.0% line coverage). FR-STK-20 ACCEPTED (fast-moving by sales value) and D-050 ACCEPTED with the owner's two additions ("No sale since <books_from>" label; stale-snapshot warning). Stock rules in [`docs/metrics.md`](metrics.md). FR-STK-8/9 wait for G27. Next: P13 (frontend foundation) — waits for the owner.

P11 (aging and payment behaviour) — **complete** 2026-09-29. CI green (`check` 36539892109, `capture-kit` 36539892090; `agent-windows` not triggered, last green 36534423546). Local suite PASS ([phase-11](test-reports/phase-11.md), 1,388 tests: 1,385 passed, 3 skipped — Windows-only; 89.9% line coverage). D-049 ACCEPTED with the owner's two additions (reused bill names marked unverified and listed; payment behaviour counts receipts only). Aging rules in [`docs/metrics.md`](metrics.md). Payment behaviour stays hidden until G25 passes; G25 and G31 join the pending G-E captures (the CHECKLIST gains a reused bill name). Next: P12 (stock) — waits for the owner.

P10 (reconciliation) — **complete** 2026-09-29. CI green (`check` 36534423550, `agent-windows` 36534423546, `capture-kit` 36534423565). Local suite PASS ([phase-10](test-reports/phase-10.md), 1,327 tests: 1,324 passed, 3 skipped — Windows-only; 89.9% line coverage). D-048 ACCEPTED with the owner's three changes (independence stated and tested; explicit dates on every voucher request, post-dated vouchers included; stock compared within the same run). The basis is in [`docs/reconciliation-basis.md`](reconciliation-basis.md): **still to be reviewed by the accountant** (the phase's definition of done). New gates G36 and G37 (NOT TESTED) join the G-E captures. Next: P11 (aging and payment behaviour) — waits for the owner.

P9 (attribution and rankings) — **complete** 2026-09-28. Local suite PASS ([phase-09](test-reports/phase-09.md), 1,252 tests: 1,249 passed, 3 skipped — Windows-only; 89.5% line coverage); CI green (`check` 36460856648; `capture-kit` and `agent-windows` not triggered, last green 36444202153 / 36436892986). D-046 ACCEPTED (returns follow their original's bucket; product rows; units never summed across; the "Non-product" label needs G28 **and** taxable-value mode). D-047 (custom plans for analytics) added as a performance fix. The benchmark at SRS 17.2 size found the dashboard set at 2.6 s over three years once the P9 figures were added; fixed to 1.8 s (below). Next: P10 (reconciliation) — waits for the owner.

P8 (core analytics) — **complete** 2026-09-28. Local suite PASS ([phase-08](test-reports/phase-08.md), 1,204 tests: 1,201 passed, 3 skipped — the Windows-only tests; 89.5% line coverage); CI green (runs 36444202147 `check`, 36444202153 `capture-kit`; `agent-windows` not triggered, last green 36436892986). Decisions D-021, D-044, D-045 ACCEPTED (cash flow per voucher on the Cash/Bank list with the balance invariant; one detail query per metric; expenses as net movement; blank opening = zero, GATE-G16; unavailable openings named). Metrics and rules: [`docs/metrics.md`](metrics.md). Benchmark at SRS 17.2 size below: no query near PERF-1.1, nothing changed. **Pending from the owner:** the G-E captures (now including D-045a's mixed cost-centre split) and the Agent real-machine checklist. Next: P9 (attribution and rankings) — waits for the owner.

P7 (Tally Sync Agent) — **complete, except the real-machine checklist (pending)** 2026-09-28. Local suite PASS ([phase-07](test-reports/phase-07.md), 1,093 tests: 1,090 passed, 3 skipped — the Windows-only tests, which run on the `agent-windows` job; 90.5% line coverage); CI green (report commit: runs 36409095092 `check`, 36409095090 `agent-windows` with the DPAPI/ACL/service tests running, 36409095106 `capture-kit`; build fix 0b10f69: 36410146682 `check`, 36410146644 `agent-windows`). D-043 ACCEPTED (per-Agent rate-limit buckets, 429 never a failure, the Windows service). **Pending:** `docs/agent-windows-checklist.md` on the owner's Windows VM (service as `NT SERVICE\TallyAgent`, encrypt-as-installer/decrypt-as-service, ACLs, real TallyPrime), then again on a real x64 PC before launch (P16.8b). The x64 build for it: `dist/agent-build/TallyAgent-windows-x64.zip` on the owner's Mac (git-ignored; `agent-build` run 36410154837 from 0b10f69, SHA-256 `0556b36e…d4e47ff0`). Next: P8 (core analytics) — waits for the owner.

P6 (lifecycle, deletion detection, hierarchy, Data Quality) — **complete** 2026-09-27. Local suite PASS ([phase-06](test-reports/phase-06.md), 1020 tests, 0 skipped, 91.9% line coverage); CI green (runs 36310356334 `check`, 36310356314 `agent-windows`, 36310356316 `capture-kit`). D-041 ACCEPTED, and D-007 ACCEPTED with the guard floor lowered to 5. Not covered by design: DR-ML-5 (INACTIVE) waits for G29; SYNC-5.3 is P10; SYNC-5.5 reviewed (question 8, D-041); the metric halves of ACC-7.x/8.x are P8. Next: P7 (Sync Agent) — waits for the owner.

P5 (sync engine) — **complete** 2026-09-27. Local suite PASS ([phase-05](test-reports/phase-05.md), 935 tests, 0 skipped, 90.9% line coverage); CI green (runs 36299076074 `check`, 36299076088 `agent-windows`). Decisions D-039 and D-040 ACCEPTED (D-014, D-027 superseded). Not covered by design: DR-VE-2 (per-line voucher updates) waits for GATE-G24; the Agent-side halves of AC-01/02, SYNC-1.3, FR-STK-15, NFR-REL-2 are P7. Next: P6 (lifecycle and hierarchy) — waits for the owner.

P4 (Tally contract) — **complete on drafts, blocked on live captures (G-E)** 2026-09-27. Local suite PASS ([phase-04](test-reports/phase-04.md), 804 tests, 0 skipped); CI green (runs 36294681749 check, 36294681754 capture-kit, 36294681770 agent-windows). Every Tally fact is a GATE-tagged draft; confirming them needs the owner's captures from the Windows VM (`make capture-kit`, then the kit README). Next: P5 (sync engine) can start without the captures — it waits for the owner.

P3 (Agent control plane) — **complete** 2026-09-25. Local suite PASS ([phase-03](test-reports/phase-03.md), 613 tests, 0 skipped) and CI green (run 36107675601, both `check` and `agent-windows`). Next: P4 (Tally contract) — not started; waits for the owner, and **D-002 must be confirmed before P4**.

P2 (identity, RBAC, settings) — **complete** 2026-09-25. Local suite PASS ([phase-02](test-reports/phase-02.md), 416 tests, 1 skipped with reason) and CI green (run 36103266538, both `check` and `agent-windows`). Next: P3 (Agent control plane) — not started; waits for the owner.

P1 (data model) — **complete** 2026-09-23. Local suite PASS ([phase-01](test-reports/phase-01.md), 183 tests, 0 skipped) and CI green (run 35887137380, both `check` and `agent-windows`). Next: P2 (identity, RBAC, settings) — not started; waits for the owner.

P0 — **complete** 2026-09-23. Local suite PASS ([phase-00](test-reports/phase-00.md), 78 tests) and CI green (run 35881605525, both `check` and `agent-windows`).

## Done
| Date | Phase.Task | Commit | Notes |
|---|---|---|---|
| 2026-09-30 | P12 CI | 20fa690 | Green: `check` 36712395193. `capture-kit` and `agent-windows` not triggered (none of their paths changed); last green 36539892090, 36534423546. |
| 2026-09-30 | P12 phase report | (this commit) | [phase-12](test-reports/phase-12.md): 1,435 passed, 3 skipped (Windows-only), fresh DB, `make check` PASS. |
| 2026-09-30 | P12.5 stock API | 651f111 | `GET …/analytics/stock`: counts per class, items with snapshot date, "No sale since <books_from>", per-unit quantities, class filter (Never sold on its own, Not classified hidden unless asked), stale-snapshot warning, unit limitation, unverified gates. Days since last sale in company time at IST midnight, a month end and the FY end (90→91, 179→180). |
| 2026-09-30 | P12.1–P12.4 classification | 2f8a41b | `app/analytics/stock.py` over `product_revenue` and snapshots; truth table incl. 89/90/91/179/180 and the period gap/overlap; percentile with 1, 2 and 4 items and ties; NUMERIC percentile equals `percentile_cont`; partition property; linked returns net the value; Data Quality: items without a snapshot, multi-unit items. |
| 2026-09-30 | P12.0 decisions | 602652d | FR-STK-20 ACCEPTED, D-050; `stock.measurement_period_days` 30/60/90/180; `stock.snapshot_stale_days` (2); `stock.fast_ranking_basis` retired; metrics.md stock rules. |
| 2026-09-29 | P11 CI | 7ab94eb | Green: `check` 36539892109, `capture-kit` 36539892090. `agent-windows` not triggered (nothing under `agent/` or `shared/` changed); last green 36534423546. |
| 2026-09-29 | P11 phase report | (this commit) | [phase-11](test-reports/phase-11.md): 1,385 passed, 3 skipped (Windows-only), fresh DB, `make check` PASS. |
| 2026-09-29 | P11.7 payment behaviour | 2cae95a | `GET …/analytics/payment-behaviour`: receipts only (D-049 #5), credit notes and journals excluded and counted in the notes, refunds and advances never settlements, trailing 365 days, insufficient history below 3; hidden until G25 passes. AC-51 = 14 days. |
| 2026-09-29 | P11.6 aging API | e2afb4f | `GET …/analytics/aging`, `/aging/bills`, `/aging/allocations`: buckets, credit, advances, on-account, unmatched, net exposure, no-bill-details, unverified gates. "Today" in company time at IST midnight, a month end and the FY end; summary = Σ parties; a party's bills add up to its buckets less its credit. |
| 2026-09-29 | P11.2–P11.5 bills and buckets | 309f26c | `blocks.bill_rows`, `receivable_bills` / `payable_bills` detail queries, `app/analytics/aging.py`. AC-45–50, boundaries 0/30/31/60/61/90/91 and [15, 45], refunds, over-settled credits, payable mirror, opening bills, reused names, unmatched, UNSUPPORTED excluded, no bill details. Data Quality: over-settled bills, unmatched settlements, bill reference reused. |
| 2026-09-29 | P11.1 allocation types | e173384 | Stored types from the P4 fixture; "Bill allocations of an unknown type" Data Quality check. |
| 2026-09-29 | P11.0 decisions | bf28f36 | D-049; metrics.md aging section; CHECKLIST reused bill name. |
| 2026-09-29 | P10 CI | b23f8c4 | Green on all three workflows: `check` 36534423550, `agent-windows` 36534423546, `capture-kit` 36534423565. |
| 2026-09-29 | P10 phase report | (this commit) | [phase-10](test-reports/phase-10.md): 1,324 passed, 3 skipped (Windows-only), fresh DB, `make check` PASS. |
| 2026-09-29 | P10.6 API, end to end | 21edd57 | `POST …/reconciliation/run`, `GET …/reconciliation` (AC-40, REC-1.2: Tally, local, both differences, result; failures first; not compared; unverified gates; history), `sync/status.reconciliation` (FR-4.1), `uptime_advisory` none/advisory/prominent (AGT-6.4). The mock Tally computes `TA_ReconTotals` from its own vouchers; e2e: FULL → queued RECONCILIATION → job → PASS for every ledger and total; a changed Tally closing → FAIL on exactly that ledger. |
| 2026-09-29 | P10.5 comparison | 9398be9 | `app/reconciliation/compare.py` through `app.analytics.query` only; `recon_receipts` / `recon_payments` detail queries (not in the analytics API); the job `reconcile_runs`; a FULL run that stored data queues a RECONCILIATION command (audited). Migration 0008 `reconciliation_runs`. Tests: each basis, the shared-filter case, AC-10, AC-38, D-007 guard and date window on reconciliation lists, the one-writer architecture test. |
| 2026-09-29 | P10.4 tolerance | 30e9c2e | `app/reconciliation/tolerance.py`; the six SRS 9.3 rows, AC-41–44, Cr balances, inclusive limits. |
| 2026-09-29 | P10.3 RECONCILIATION runs | 27455d5 | Plan: every key list due, the periods, the FY start. Agent: snapshot then a second stock read, totals per period, ledger closings. Backend stages them in `reconciliation_tally_values` (migration 0007), no lease, RECONCILIATION runs only. |
| 2026-09-29 | P10.2 contract, TDL, dates | a8b8ce3 | `TA_ReconTotals` (GATE-G36); `ReconciliationTotalRecord`, `ReconciliationStockRecord`; parsers and fixtures; TDL 0.2.0, contract 1.1. Every voucher request names its dates (the builder refuses one without); a post-dated voucher syncs (agent and e2e tests). Capture kit: `recon_totals`, dated `voucher_keys`, scenario G37; CHECKLIST gains a post-dated voucher. |
| 2026-09-29 | P10.1 basis | bc20031 | `docs/reconciliation-basis.md`, D-048, D-007 wording amended, gates G36/G37. |
| 2026-09-28 | P9 CI | 7d321d0 | Green: `check` 36460856648. `capture-kit` and `agent-windows` were not triggered (none of their paths changed in P9); their last runs are green (36444202153, 36436892986). |
| 2026-09-28 | P9 phase report | (this commit) | [phase-09](test-reports/phase-09.md): 1,249 passed, 3 skipped (Windows-only), fresh DB, `make check` PASS. |
| 2026-09-28 | P9.6 benchmark, docs | 0206009 | The benchmark dataset gains 94,005 seeded inventory lines (some items sold by the Box); rankings and the product difference are timed; `docs/metrics.md` covers attribution, the return-bucket rule, the label and units. |
| 2026-09-28 | P9.6 performance fix | 0abeab9 | Found by the benchmark: the 3-year dashboard set had reached 2.6 s. (1) The customer bucket aggregate ran twice over every voucher; now one CTE over origin-type vouchers. (2) The planner (estimating 555 rows for 89k) nested-looped every sales row against the returns' origin buckets; sales rows and return rows are now joined to their buckets separately (UNION ALL). (3) asyncpg's prepared statements let PostgreSQL reuse a generic plan made for another date range (~60% slower): analytics set `plan_cache_mode = force_custom_plan` for the request's transaction (D-047). Top-10 customers over 3 years: 871 → 375 ms; dashboard set 2.6 s → 1.8 s; P8's receivables and payables also dropped (203 → 75, 186 → 60 ms). |
| 2026-09-28 | P9.5 ranking endpoints | 566fe05 | `GET …/analytics/customers`, `/suppliers`, `/products` (`rank_by=revenue|quantity`, `top_n`, `view_all`): "Top N" or "All", `total_count`, Unattributed apart, the reference total, no Top-N sum and a note saying so; quantity rows carry the unit and `multiple_units`; products carry `product_attributed` and one `difference` label. AC-33, TOPN-1.1, TOPN-1.4, FR-2.4, ACC-VAL-1 (four gate/mode states; the other label's text appears nowhere in the body). |
| 2026-09-28 | P9.4 rankings | 3b38df4 | `query.ranking`: the full list's query, `n` only adds a LIMIT; `total_count` and the per-item `siblings` come from window functions over the whole list. Tested: Top-N rows == first N of the full list for every N with ties (TOPN-1.2); Unattributed never ranked; quantities per (item, unit), Soap in Nos and Box flagged, never summed. |
| 2026-09-28 | P9.3 product attribution | c9090ef | `blocks.items`, `metrics/product_revenue.py` (sales lines +, linked credit notes' lines −), `query.product_difference` with one label: "Unattributed / Non-product Sales Revenue" only when G28 passed and taxable-value mode is on (owner). AC-32, ACC-1.8, ACC-1.9, ACC-1.10. |
| 2026-09-28 | P9.2 supplier attribution | d2be03b | `metrics/supplier_purchases.py`, the mirror (ACC-1.4). |
| 2026-09-28 | P9.1 customer attribution | 6e0c43b | `blocks.party_bucket`, `returns.note_origins`, `returns.attributed`, `metrics/customer_revenue.py`. AC-30, AC-31, ACC-6.1–6.3; ACC-6.4 over four periods on a mixed dataset (returns against single- and two-customer sales, a note against both, unlinked and cancelled-origin notes), each return's bucket checked directly, and a hypothesis test against a Python model of every bucket. |
| 2026-09-28 | P9.0 decisions | 973d428 | D-046 ACCEPTED; D-019 customer half superseded; the Phase 9 file updated. |
| 2026-09-28 | P8 CI | 5647cba | Green: `check` 36444202147 and `capture-kit` 36444202153. `agent-windows` was not triggered (nothing under `agent/`, `shared/` or the lockfile changed in P8 session 2); its last run, 36436892986 on f4e5b63, is green. |
| 2026-09-28 | P8 phase report | (this commit) | [phase-08](test-reports/phase-08.md): 1,201 passed, 3 skipped (Windows-only), fresh DB, `make check` PASS; hand-added notes list the SRS IDs superseded by D-021 / D-044 #5 / D-039 #5. |
| 2026-09-28 | P8.10 every metric, docs | 74e84a4 | A registry-wide test: every metric leaves out cancelled, missing and unresolved-ledger vouchers unless asked (ACC-4.5), and a new metric must add its case. `docs/metrics.md`. |
| 2026-09-28 | P8.8 analytics API | bc40b59 | `GET /companies/{id}/analytics/{metric}` and `/drilldown` for all nine metrics, through `query.py` only; FY-to-date default in company time; `group_by` per metric; balances as amount + Dr/Cr, or unavailable with the ledgers named and a pointer to Data Quality (D-045 #3). Tests: every view of every metric agrees to the paisa (summary = Σ series = Σ breakdown = Σ all drill-down pages); AC-62 in full ("today" and daily grouping at 23:58 IST and 00:30 IST under a UTC+14 database session); money as JSON strings; 422s; another company → 403. |
| 2026-09-28 | P8 benchmark | 81f3070 | `make bench-data` (seeded 100k vouchers / 500k entries / 5k ledgers / 10k items into `tally_bench`, 12 s) and `make bench-analytics` → [docs/benchmarks/p8-analytics.md](benchmarks/p8-analytics.md). Results in "Benchmark (P8)" below. |
| 2026-09-28 | P8.6 cash flow | 8193ccc | `metrics/cash_flow.py` per D-021. The invariant (net = change in Cash/Bank position) on a mixed dataset over 7 periods (from books-beginning, a month, a quarter with a contra to an unlisted OD, across the FY boundary, one day, an empty month, everything) and as a hypothesis property over random vouchers, types and statuses. Restricting to Receipt/Payment (the old wording) breaks it. |
| 2026-09-28 | P8.7 balances | 00735b0 | `blocks.balance_rows` (books-beginning opening row per ledger + entries since `books_from`); `cash_bank_position`, `receivables`, `payables`, `ledger_balances` (income/expense = period movement). A NULL opening makes totals and breakdowns unavailable; `query.unavailable` names the ledgers. AC-38 computed part, two-year carry, ACC-9.2/9.3/9.4/9.6. |
| 2026-09-28 | P8.5 purchases, expenses | e1f229f | `returns.gross_less_returns` shared by sales and purchases; ACC-1.2 in one test; expenses as net movement at cost-centre grain with a "(No cost centre)" remainder: a crediting journal and a refund reduce it, a reclassification moves only the breakdown. |
| 2026-09-28 | P8 D-045 | 4fca1e8 | D-045 ACCEPTED; capture-kit CHECKLIST gains a Journal with a mixed (Dr and Cr) cost-centre split (D-045a); Phase 8 file's ACC-9.1 bullet replaced. |
| 2026-09-28 | P8.4 Total Sales Revenue | 968517f | `metrics/sales.py`: CREDIT entries on Sales-class ledgers in SALES-base vouchers, minus linked credit notes; tax only when taxable-value mode is off. AC-26, 28, 29, 35, 36 and ACC-1.1 (every clause in one test); hypothesis property (random balanced vouchers with noise on non-class ledgers: total = Σ sales credits). Five mutations of the rule each caught. |
| 2026-09-28 | P8.3 returns | a06cbbb | `analytics/returns.py`: a note is linked only via AGST_REF = a NEW_REF (same ledger and reference) from an ACTIVE SALES/PURCHASE voucher, and only once G26 passes (ACC-5.1, 5.2, 5.5). `metrics/unclassified_adjustments.py` (ACC-5.3) and Data Quality check `unlinked_notes`. Four mutations of the link rule each caught. |
| 2026-09-28 | P8.1 architecture (+P8.2) | 0822b57 | `app/analytics/`: `context.py` (filter, `MetricContext` from `CompanyContext`, G26), `classification.py` (allow-lists → anchor ids, customer/supplier), `blocks.py` (entries of the filter's statuses and dates), `query.py` (the only caller of `detail_query`: total, series, breakdown, drilldown; `bucket` in SQL, `timezone(company_tz, ts)`, financial quarters). Guards: no `amount_raw` under analytics/exports/reconciliation/anomaly (AC-34 half); one public `detail_query` per metric module, no other `select()`, no async; money tables imported only by approved modules; every metric module registered. Each guard is also run against bad source. SQL buckets equal Python's `financial_quarter_of` for every day of 2024–2026 under four FY starts; AC-62 SQL half under UTC, New York and Kiritimati session zones. |
| 2026-09-28 | P8.0 decisions, settings, openings | db55119, 979dcab, 333e4c2 | D-021 ACCEPTED, D-016 note, D-044 ACCEPTED; `cashflow.include_journal` default true; Phase 8 file updated (expenses as net movement, cash-flow rule and invariant). Parser: a present-but-blank `OPENINGBALANCE` is a zero opening, absent is none (`BLANK_OPENING_IS_ZERO`, GATE-G16); fixtures `ledgers_opening_blank/zero/absent`, and an ingest test from those fixtures through the real parser (blank/zero → a 0 row, absent → no row). The masters writer already stored any known opening; unchanged. Data Quality text for missing openings updated. |
| 2026-09-28 | CI flake fix | 1e58d30 | Run 36412736302 failed: the forged-token rate-limit test's 101 requests straddled a real one-minute window (the limiter ran on the real monotonic clock). The middleware tests now pin the limiter's clock (`app.state.rate_limiter`); green again in run 36414645512. |
| 2026-09-28 | P7 agent build | 0b10f69 | `agent-build` run 36410154837 (x64, windows-latest): `TallyAgent-windows-x64.zip` with `tally-agent.exe`, `tally-agent-service.exe`, `tdl\`, the install scripts and guide at the top level (the first build had put them under `_internal\`; fixed and smoke-tested). Downloaded to `dist/agent-build/`. |
| 2026-09-28 | P7 phase report | 7bc6de2 | [phase-07](test-reports/phase-07.md): 1,090 passed, 3 skipped (Windows-only, run on `agent-windows`), fresh DB, `make check` PASS. |
| 2026-09-28 | P7.10 end-to-end | cef0ff4, cdfbd38 | Real Agent, real backend (uvicorn subprocess on the test clock), mock TallyPrime: register → FULL twice (AC-01) → edit (AC-02, old and new audited) → delete (AC-04, in Data Quality); backend SIGKILLed mid-upload and restarted: nothing lost or duplicated; the owner's drain test: 200 queued batches through the Agent's own bucket (100 per 5 s) with 429s, none dead-lettered, anonymous traffic from the same IP untouched (mutation-checked). Control calls ride out brief outages. |
| 2026-09-28 | P7.9 Windows service and build | 5ae98a3 | pywin32 service wrapper, PyInstaller x64 one-folder build (manual `agent-build` workflow), `Install-/Uninstall-TallyAgent.ps1` (virtual account, icacls, revoke reminder), `docs/agent-install.md`, `docs/agent-windows-checklist.md` (**pending**), `make dev-tls` / `dev-https` and `tally_tools.dev_backend` for the checklist; P16.8b (real x64 re-run). |
| 2026-09-28 | P7.8 mock Tally | d4cc2b4 | Edits between runs (edit, cancel, delete) and `--sample`. |
| 2026-09-28 | Agent 429 handling | 900f3eb | A 429 is deferred until Retry-After, never counted as an attempt or dead-lettered; control calls wait it out (D-043 #2). |
| 2026-09-28 | Per-Agent rate limits | 29ae4c6 | Owner finding confirmed: Agent requests fell into their office IP's anonymous bucket (100/min). Each verified Agent now has its own bucket (1,000/min); forged `agt_` tokens stay in the IP bucket (D-043 #1). |
| 2026-09-28 | P7 session 2 | b4d2922 | Progress log; CI green on all three workflows. |
| 2026-09-28 | P7.5/P7.7 executor and service | 7d8d633 | Collections in dependency order under their leases; ALTERID windows (full pulls from 0) or date pages for full-only vouchers and DATE_RANGE; a timed-out window retried once as two halves, a second timeout reported as TALLY_EXPORT_TIMEOUT (AGT-4.3); key lists when due; stock snapshot as of the plan's date; uploads drained before each release and the finish. Progress on its own thread: a Tally answer 3x the lease keeps the command RUNNING (owner 1). A 5,000-voucher window peaks at 1.3x its XML, not 95 MB (owner 2; the parser now feeds XML in 64 KB slices). Dates from the plan while the PC clock says 2031 (owner 5). AC-21, AC-23, AGT-3.2/3.3, AGT-5.4, heartbeat status; six mutations checked. |
| 2026-09-28 | P7.6 queue and uploader | bea67eb | SQLite (WAL) queue in the restricted data directory: windows staged on disk and committed whole, strict FIFO, backoff 30 s → 15 min with jitter, dead-letter cascade per run and collection, obsolete runs after a lost command, permanent refusals dead-lettered at once, pause on a rotated credential. |
| 2026-09-28 | P7.5 groundwork | eaa0d2a | Streaming parser (`iter_parse`); the run plan carries `as_of` (today in company time) and `full_pull_from`; the backend refuses a stock snapshot dated after its today. |
| 2026-09-27 | P7 session 1 | 92f987b | Progress log; CI green on all three workflows. |
| 2026-09-27 | P7.2 CLI | 8393ab3 | `register` per SRS 4.2 (Tally and our TDL checked first; credential only in the secret store; never registered twice), `set-credential` / `set-proxy-credentials` at hidden prompts, `status`, `test-tally`. |
| 2026-09-27 | P7.4 preflight | b157839 | The named company, the TDL version bundled with this Agent (D-042 #7), the registered GUID (COMPANY_MISMATCH halts before anything else is asked); closed or renamed → COMPANY_NOT_LOADED. |
| 2026-09-27 | P7.3 Tally client | 14fc0dd | SRS 16 mapping (refused + running → TALLY_SERVER_DISABLED, not running → TALLY_UNREACHABLE), timeout logged TALLY_EXPORT_TIMEOUT, TDL_NOT_LOADED / COMPANY_NOT_LOADED, never through a proxy; uptime from the process table; the mock Tally gained delay, GUIDs, TDL version and a request log. |
| 2026-09-27 | P7.1 foundations | 67d2c9a | D-042 (owner: DPAPI machine scope, TDL version equals the bundled one, P16 code signing). Strict `agent.toml` (no way to disable TLS checks, no secrets), DPAPI secret store and a data-dir ACL for the service account, SYSTEM and Administrators (verified on the Windows CI runner), TLS ≥ 1.2 with certifi plus a customer CA bundle, HTTP CONNECT proxy with DPAPI-stored credentials. |
| 2026-09-27 | P6 phase report | 3cf2ee4 | [phase-06](test-reports/phase-06.md): 1020 passed, 0 skipped, fresh DB, `make check` PASS. |
| 2026-09-27 | P6.8 docs | ed30437 | `docs/sync-engine.md` (key lists, lifecycle, hierarchy, Data Quality), `docs/agent-protocol.md` (key lists), traceability. |
| 2026-09-27 | P6.7 masters endpoints | 0326927 | `/masters/groups` (anchor, predefined and primary group by current name, nature, statuses) and `/masters/voucher-types`. |
| 2026-09-27 | P6.6 Data Quality | 10743c7 | Registry of checks, each one SQL query; 13 checks including the owner's "not in any classification list", "predefined group possibly renamed" and "predefined voucher type possibly renamed" (both retire when G32 passes). |
| 2026-09-27 | P6.4/P6.5 hierarchy | ba77328 | Group forest and voucher-type walks per chunk with cycle detection; one test per D-001 worked example (1-5); reparenting recomputes descendants and ledgers and is audited (ACC-7.5), fixing P5's parent linking that only filled NULLs; reserved names gated on G32, own nature from G14 flags. Four mutations checked. |
| 2026-09-27 | P6.2/P6.3 key lists | 9beb61a | Staged, windowed, guarded key lists (owner items 2 and 5, floor 5 with a small-collection test); reappearance by key list or pull whatever the ALTERID (owner item 3); missed changes lower the watermark; `key_list_due`; Owner/Admin confirmation. Five mutations checked. |
| 2026-09-27 | P6 decisions | 35efb09 | D-041, D-007 accepted; migration 0006; `KeyListChunk`; key requests never ALTERID-windowed and differ from the data request only in the report (owner item 4, TDL and request tests). |
| 2026-09-27 | P5 phase report | 6c884a3 | [phase-05](test-reports/phase-05.md): 935 passed, 0 skipped, fresh DB, `make check` PASS. |
| 2026-09-27 | P5.10 closing tests and docs | c694a63 | NFR-REL-2 (an exception mid-voucher leaves a new voucher absent or a modified one entirely at its stored version), SYNC-4.4 (lease + stale protection both needed), `docs/sync-engine.md`, agent-protocol run endings. |
| 2026-09-27 | P5.9 full-only collections | 0c8f7bc | Owner rule 1 / AC-12 / VAL-1.2: a scheduled INCREMENTAL run syncs a FULL_ONLY collection by full pull and ends COMPLETED; only ALTER_ID batches get `GATE_NOT_PASSED`; its watermark never moves; status shows "Full sync only". Mutation-checked. |
| 2026-09-27 | P5.8 status APIs | fb33188 | `sync/status`, `runs`, `errors` (VIEW_LOGS), `lease-status`; custom-field mappings (audited) and the generated UDF TDL (DR-UDF-1, DR-UDF-4). |
| 2026-09-27 | P5.7 run bookkeeping | d98f270 | `close_run` (D-040 #1): every `sync_errors` code classified NOT_STORED / INFO, with a source-scanning test; `finish` problems; the command result closes open runs; `on_command_lost` closes runs (PARTIAL if chunks committed), records AGENT_LOST, frees leases (committed race); CHUNK_FAILED holds the watermark (AC-05); first FULL COMPLETED or PARTIAL activates default schedules, FAILED leaves them off; `INITIAL_SYNC_INCOMPLETE` warning (owner rule 2). Five mutations checked. |
| 2026-09-27 | P5.6 stock snapshots | bfbccbf | Null-collection batches of STOCK_SNAPSHOT on the STOCK_ITEM lease, upserted per (item, date). |
| 2026-09-27 | P5 session 2 decisions | 5263174 | D-040; CHUNK_FAILED and AGENT_LOST codes (D-030); phase-05 plan refreshed; P13.9 lists the held-back check. |
| 2026-09-27 | P5.5 watermarks | 2de12c7 | AC-07 on the ingest side; DATE_RANGE never moves the watermark; a record edited during a date-paged FULL pull is re-pulled by the next incremental (release to the pre-pull max); no pre-pull max → no advance; release capped below failed records. Each rule mutation-checked. `docs/agent-protocol.md` documents runs, leases, batches and release. |
| 2026-09-27 | P5.4 vouchers | a1a40ea | Per-voucher SAVEPOINT, SRS 6.9 child replacement, balance recheck, name fallback (D-002), VOUCHER_MODIFIED / VOUCHER_CANCELLED audit. TEST-3.3: a real SIGKILL mid-voucher and mid-batch leaves no partial voucher and the committed watermark (mutation-checked against a non-atomic write). Owner tests: a voucher whose ledger arrives next run is stored on retry; a permanent failure never lets the watermark pass. |
| 2026-09-27 | P5.2/P5.3 ingest and masters | 6b7529b | Chunked ingest re-checking command RUNNING + live lease in every chunk (lost and takeover mid-batch tests, mutation-checked); replay by batch_id; stale-protected upserts for every master; openings at `books_from`; COMPANY GUID guard. |
| 2026-09-27 | P5.1 runs and leases | 3871b73 | Run plan per collection; lease CAS (committed race TEST-3.1/AC-09, mutation-checked); progress renews leases, result/finish releases them. |
| 2026-09-27 | P5 decisions | 8c509d7 | D-039 (owner changes: openings at books-beginning, failed records hold the watermark); migration 0005. |
| 2026-09-27 | P4.5 normalisation | 7d07f51 | Exact balance check (BALANCE_TOLERANCE = 0, GATE-G23) -> DEBIT_CREDIT_IMBALANCE via `RecordRejected`; cancellation only on an explicit Yes (G9); multi-currency amount forms rejected, never partly read; `Amount` built only in `normalize.py` (ACC-DATA-2). |
| 2026-09-27 | P3 test fix | 1f97eac | The 02:00 schedule test polled with the wall clock, so it began failing the day after its fixed date; now runs on the scenario's clock. |
| 2026-09-27 | P4.6 UDFs | 95f7632 | Generated TDL include (identifiers validated: no TDL injection), per-run reader, UDF_NOT_FOUND once per field per run. |
| 2026-09-27 | P4.7 fixtures | ddac9b8 | 26 synthetic cases, each expected result read by hand. The review found two parser problems, fixed: an On Account allocation has no bill name (no longer rejects its voucher); compound quantities ("2 Box = 24 Nos") now fail their record until G27, instead of being half-read. Capture kit CHECKLIST gains a USD voucher (G35). |
| 2026-09-27 | P4.8 harness | f0b62e0 | Every fixture compared with its reviewed expected result; TEST-1.2 case list enforced; `make update-fixtures [FORCE=1]`. |
| 2026-09-27 | P4.9 acceptance | 8fe4146 | AC-34 (parser half), AC-66, 5,000-voucher streaming budget (transient 1.1x the XML; 4.4x without clearing, mutation-checked). **For P7:** parsed records take ~19 KB per voucher (94 MB for 5,000), so the Agent's extraction batch size affects its memory. |
| 2026-09-25 | P4 decisions | 0510bae | D-002 and D-037 (GST out of v1) ACCEPTED; D-038 capture kit ACCEPTED; gates G34 (voucher scope) and G35 (error responses, encoding, formats) added. |
| 2026-09-25 | P4.1 records | 8a20ba6 | Record schemas and `BatchEnvelope`; `CollectionType`, `AccountingDirection`, `AllocationType` moved into `tally_contract.enums` (backend re-exports). |
| 2026-09-25 | P4.2 TDL drafts | c80473a | `tdl/TA_Minimal.tdl` (TA_Info only) and `tdl/TallyAnalytics.tdl`; `tally_constants.py` holds every Tally fact, GATE-tagged; static test ties TDL, version and XML tags together. |
| 2026-09-25 | P4.3 requests | 9423513 | Request builder with golden files; `.gitattributes` keeps fixtures and golden files byte-exact on Windows. |
| 2026-09-25 | P4.4 parser | 8b375ae | Streaming (stdlib `iterparse`, not lxml: no new Windows dependency), per-record isolation, TDL_NOT_LOADED / COMPANY_NOT_LOADED detection, AC-66. `normalize.to_amount` (G23) and the bill-type map (G25) moved here from P4.5 because the parser needs them; `values.py` sits beside the parser to avoid an import cycle. |
| 2026-09-25 | K1 mock Tally | 052aaa6 | `tools/tally_tools/mock_tally.py` for the kit's CI now and the Agent in P7. |
| 2026-09-25 | K2/K3 capture kit | 732403d, cc08b8f | `tools/capture_kit/` + `make capture-kit`. Windows workflows split and path-filtered (D-038 #7); capture-kit passed on real PS 5.1 on the first run apart from a verifier glob; expected Tally errors now shown as OK. `agent-windows` is now blocking. |
| 2026-09-25 | P3.7 commands + migration 0004 | b08caed | D-036 ACCEPTED. `created_at` from the app clock + `seq` identity: oldest = (created_at, seq); the P3.6 test workaround removed. Routing: one eligible Agent targeted even if OFFLINE/REGISTERING (waiting label); several need one ACTIVE or `agent_id`. |
| 2026-09-25 | P3.8 claim/progress/result | c86e7fd | Single conditional UPDATEs. Committed races: 10 claims → 1; claims blocked behind an uncommitted claim all lose; one Agent, two commands → 1 (unique index). Mutation-checked (naive claim; dropped index). |
| 2026-09-25 | P3.9 timeouts | 5be8794 | EXPIRED / FAILED_AGENT_LOST jobs; AGT-1.9 late calls → 409 with the row unchanged; on-time progress blocked behind the lost job loses (mutation-checked). `on_command_lost` hook for P5. |
| 2026-09-25 | P3.10 schedules | 8805249 | `next_fire_at`, cron in company TZ, missed runs coalesce; simultaneous firings INCREMENTAL first (tested in both insertion orders; removing the sort fails it). |
| 2026-09-25 | P3.11 Agent management | 27e63a5 | Agents view (+ `NO_ACTIVE_SCHEDULE`), rotation (committed races: one-instant switch, vs revocation, two rotations), revocation deactivates schedules, tally-settings (AC-24). Replacement path tested end to end. Phase 5 plan gains the required schedule-activation item. |
| 2026-09-25 | P3.12 docs | 2b31319 | `docs/agent-protocol.md` complete (states, sequence diagram); OpenAPI summary test for every Agent endpoint. Smoke test on the dev DB: register → heartbeat → Sync Now → claim/progress/result → COMPLETED. |
| 2026-09-25 | P3 tag review | (see log) | Downgraded to partial: AGT-1.1, VER-1.1 (the Agent's side: P7), AC-17, AC-19, AGT-1.6, FR-4.4 (dashboard: P13). |
| 2026-09-25 | P3.1 credentials + committing fixture | 7e43c09 | `agt_<id>.<secret>`, salted SHA-256; `reg_` tokens hashed. `committed` fixture: real commits on separate connections, TRUNCATE only on a `_test` database (D-035 #14). D-035 ACCEPTED. APScheduler added. |
| 2026-09-25 | P3.2 registration token | 7f4a380 | MANAGE_AGENTS, shown once, 24 h, audited. |
| 2026-09-25 | P3.3 registration | cb05398 | CAS on token and GUID binding in one transaction; mismatch leaves the token usable (AC-13, AC-14). Committed races: one token x8 → one Agent; two first Agents with different GUIDs → one binds. Mutation-checked against a naive read-then-write. |
| 2026-09-25 | P3.4 AgentContext | 2cab749 | CREDENTIAL_INVALID vs AGENT_REVOKED (SEC-2.2); a wrong secret never reveals revocation. |
| 2026-09-25 | P3.5 heartbeat | 3ea4b23 | Migration 0003 (`error_code`, partial unique index: one command in progress per Agent, D-035 #13). INCOMPATIBLE (AC-22), GUID confirmation, D-025, COMPANY_MISMATCH warning (AGT-3.4). Route test: P2 skip removed; Agent routes checked; user/company routes reject Agent credentials. `docs/agent-protocol.md` started (independent progress timer). |
| 2026-09-25 | P3.6 offline job | 03db83b | `mark_offline` per company threshold; `run_exclusive` advisory lock tested on real connections (D-017). **This commit went in with one failing test** (my check pipeline did not stop on failure); fixed in 74f5d17 — a heartbeat test tied on `created_at`. |
| 2026-09-25 | P2 follow-up | (see log) | D-034 ACCEPTED. Per-replica rate-limit ceiling added to the Phase 16 plan as required task P16.11 (before production). |
| 2026-09-25 | P2.7 audit service | 330c906 | `audit.record()` writes every LOG-1.2 field; `diff()`. D-033 ACCEPTED with the plan. |
| 2026-09-25 | P2.9 periods | 922b481 | TZ-safe day bounds, FY/quarter labels; AC-62 run under 3 server time zones. AC-62/AC-63 partial until analytics group by them (P8). |
| 2026-09-25 | P2.2 auth | ba670d2 | Migration 0002 (`refresh_tokens`, login index). Rotation; reuse revokes all sessions; per-email throttle from audit rows (D-033 #7). `RATE_LIMITED` code. |
| 2026-09-25 | P2.3/P2.4 permissions | e9bfb8c | SRS 14.1 matrix, `require()` (a `Require` object the route test can read), `CompanyContext`, `scoped()`. |
| 2026-09-25 | P2.5 companies + route access test | c5266d9 | `tests/api/test_route_access.py` enumerates every route (`fastapi.routing.iter_route_contexts`); verified it fails for a route without `require()`, a view permission on a write route, and an unlisted route. D-034 PROPOSED (FY start day 1-28). |
| 2026-09-25 | P2.6 users and roles | 580c28d | Attach existing accounts; per-company removal; last-Owner 409 (company row locked); all audited. |
| 2026-09-25 | P2.8 settings and flags | 0227a9d | Registry of all SRS 18.2 keys + 3 additions; allow-lists by identifier, shown by current name; AC-59. |
| 2026-09-25 | P2.10 middleware | 4514eb0 | CORS, 100/1000 rate limits, trusted-proxy IP and scheme, HTTPS in prod, request IDs, headers; `HTTPS_REQUIRED` code; `docs/security-review.md`. |
| 2026-09-25 | P2.1 create-owner CLI | 5b4f1cb | Manual smoke test on the dev DB: owner login, company, Accountant PUT settings → 403, Owner → 200. |
| 2026-09-25 | Env | — | The repo moved to `~/Desktop/tally-platform`; `.venv` scripts still pointed at the old path, so `uv sync --all-packages --reinstall` was needed once. |
| 2026-09-23 | P1.1 model conventions, types, enums | 631d0e7 | Money/Quantity/Rate NUMERIC, timestamptz, StrEnum CHECKs, tenant composite-FK helper; metadata convention tests. |
| 2026-09-23 | P1.2 companies, users, roles | 92e7776 | Single migration 0001 started; roles seeded. Rollback-per-test `session` fixture (cannot test commits; SYNC-6.1/6.2, TEST-3.3 need a committing fixture). |
| 2026-09-23 | P1.3 agents, commands, schedules | 0eccccc | RTE-1.4 trigger: agent_id/company_id immutable. |
| 2026-09-23 | P1.4 masters (D-001 columns) | a0c4db0 | Anchor columns, partial unique reserved_name, no-DELETE trigger (DR-ML-1). |
| 2026-09-23 | P1.5 opening balances, snapshots | 6a09f02 | opening_bill_allocations per D-022. |
| 2026-09-23 | P1.6 vouchers and children | 3ab7b56 | Normalized-amount CHECKs, cascading children for 6.9, identity tests on all 6 synced tables. |
| 2026-09-23 | P1.7 sync control | 892714b | Watermarks/lease, runs, errors, batches (D-024), reconciliation results. |
| 2026-09-23 | P1.8 settings, audit, anomaly | 10154d0 | Allow-list defaults in `app/models/defaults.py` (D-031 #13); rename-survival test; audit append-only for every role. |
| 2026-09-23 | P1.9 migration round-trip | 7cdae52 | Upgrade == models (no autogenerate diff), downgrade leaves nothing. Review fixed INTEGER→BIGINT FKs; convention tests for FK types and redundant indexes. |
| 2026-09-23 | P1.10 factories | bb033b3 | `backend/tests/factories.py`. |
| 2026-09-23 | Req-tag audit | (see log) | `req` now means the test fully proves the requirement; new `req_partial` marker, listed separately in traceability and phase reports. Every tag re-checked against the SRS: fully covered RTE-1.4, DR-ML-1, DR-4.6; 10 partial; removed TEST-1.3, ACC-DATA-1, DR-VE-3/4, SEC-1.7 (and DR-ML-1 on vouchers); AC-12 moved to the FAILED-gate test as partial. Phase 00/01 reports carry a correction note. |
| 2026-09-23 | P1 docs | (see log) | `docs/schema.md` (Mermaid ER + invariants); D-031 and D-032 ACCEPTED. |
| 2026-09-23 | Setup: repo, plan, SRS v7.3 PDF, .gitignore | 9b83697 | No application code. SRS PDF verified as "v7.3 Complete Edition", 34 pages. |
| 2026-09-23 | Setup: origin added, answers and toolchain recorded | e769a15 | Pushed `main` to origin. |
| 2026-09-23 | P0.1 workspace and directory tree | ba0987a | uv workspace: shared, backend, agent, tools. |
| 2026-09-23 | P0.5 quality tooling | (see log) | ruff (T20: no print), mypy strict on tally_contract + app.core, 3 import-linter contracts. |
| 2026-09-23 | P0.12 logging and test-run infrastructure | 30db670 | structlog via stdlib logging, `assert_logged`, req-ID JUnit properties, skips must give a reason. |
| 2026-09-23 | P0.3 error codes and contract version | (see log) | 15 SRS + 14 additions (D-030). |
| 2026-09-23 | P0.6 docker environment | (see log) | postgres 16 + backend; `tally_owner` (DDL) / `tally_app` (DML only). |
| 2026-09-23 | P0.2 backend skeleton | (see log) | config, db, AppError handlers, /health, /health/db, alembic skeleton. |
| 2026-09-23 | P0.10 gate plumbing | (see log) | gate_status.yaml G1-G33 NOT_TESTED; `collection_sync_mode` per VAL-1.1/1.2. |
| 2026-09-23 | P0.4 Agent CLI stubs | (see log) | register, run, status, set-credential, test-tally. |
| 2026-09-23 | P0.11 SRS transcription | b926e89 | `docs/srs/SRS_v7_3.md`, proven word-for-word against the PDF. |
| 2026-09-23 | P0.9 traceability | (see log) | 356 requirement IDs found; 6 covered so far. |
| 2026-09-23 | P0.7/P0.8 Makefile and CI | (see log) | GitHub Actions: `check` (ubuntu + postgres 16) and `agent-windows` (may fail until P7). |
| 2026-09-23 | P0 CI fixes | 2f0c340 | First CI run failed in both jobs. (1) Windows: `read_text()` defaults to cp1252 -> UnicodeDecodeError; every text I/O call now names `encoding="utf-8"`, guarded by `tools/tests/test_text_io_encoding.py`. (2) Linux: the SRS tests re-ran `pdftotext` and demanded byte-equality, so Ubuntu's older poppler failed them; `docs/srs/SRS_v7_3.raw.txt` is now the committed reference extraction. Markdown unchanged; no test skipped or weakened. CI run 35881605525 green. |

## In progress
-

## Blocked
| Item | Blocked by (gate / decision / question) | Since |
|---|---|---|
| Gate track G-E (confirm or fix every GATE-tagged TDL line and constant; live fixtures in the harness; gate statuses) | Live captures from the owner's Windows VM with TallyPrime (`make capture-kit`, then the kit README) | 2026-09-25 |
| Agent real-machine checklist, `docs/agent-windows-checklist.md` (service as `NT SERVICE\\TallyAgent`, encrypt as the installing user / decrypt as the service, ACLs, real TallyPrime) | The owner runs it on the Windows VM with the `agent-build` x64 zip; repeated on a real x64 PC in P16.8b | 2026-09-28 |

## Questions for the product owner
| # | Question | Raised in | Answer |
|---|---|---|---|
| 1 | Install poppler and use `pdftotext -layout` for the P0.11 SRS transcription? | Setup | Yes. poppler 26.09.0 installed via brew (2026-09-23). |
| 2 | GitHub remote for CI (P0.8)? | Setup | `origin` = https://github.com/sushruthpippiri-cell/Tally (private). |
| 3 | Repo location? | Setup | Moved to `/Users/sushruthp/code/tally-platform` (2026-09-23). |
| 4 | Git author correct? | Setup | Yes: `sushruthpippiri-cell <sushruth.pippiri@gmail.com>`. |
| 5 | D-001 (before P1), D-002 (before P4), D-021 (before P8)? | Setup | Noted. Owner will confirm D-001 before P1 and D-002 before P4, and answer D-021 before P8. Do not start those phases until confirmed. |
| 6 | Confirm D-001 (classification anchor). | P0 end | **ACCEPTED 2026-09-23.** Anchor = nearest predefined group, else the chain's own top-level group; only a broken chain is UNRESOLVED_GROUP. Allow-list entries are stored by reserved name (predefined) or GUID (company groups), never by display name, and shown by current name. P1 is unblocked. |
| 7 | Accept the P1 plan's new schema choices (D-031) and the allow-list seeding approach? | P1 plan | **ACCEPTED 2026-09-23**, with the note that the rollback-per-test fixture must say it cannot test commit behaviour. D-032 (smaller choices made during implementation) **ACCEPTED 2026-09-23** — none changes a business rule or drops an SRS requirement. |
| 8 | SYNC-5.5: "the reference implementation's deletion handling is reviewed before this mechanism is finalized." Which reference implementation should the key-list design (D-041) be reviewed against? | P6 | **Answered 2026-09-27:** tally-database-loader (SRS 1.5). Reviewed from its public source (commit 6aae17d); findings and comparison recorded in D-041. No gap found in our mechanism; nothing changed. |
| 9 | D-021 (cash flow scope) and the SRS 27 journal question, before P8. | Setup / P8 | **ACCEPTED 2026-09-28:** every movement on Cash/Bank-list ledgers on ACTIVE vouchers of any type, transfers between own cash/bank ledgers excluded, journals included by default (`cashflow.include_journal` = true), and net cash flow = the change in the Cash/Bank balance. Also D-044: expenses as net movement, blank opening = zero. |

## Owner rules added at P0 start (2026-09-23)
Testing and logs rules (logs captured at DEBUG and saved per run, log-record assertions, per-phase full-suite report in `docs/test-reports/phase-NN.md`, no next phase on a red suite) are in `CLAUDE.md` -> "Testing and logs" and in `docs/plan/phase-00-foundation.md` (P0.12).

## Test reports
| Phase | Report | Result |
|---|---|---|
| 12 | [phase-12](test-reports/phase-12.md) | PASS - 1,438 tests, 0 failed, 3 skipped (Windows-only), 90.0% coverage; CI green: check 36712395193 |
| 11 | [phase-11](test-reports/phase-11.md) | PASS - 1,388 tests, 0 failed, 3 skipped (Windows-only), 89.9% coverage; CI green: check 36539892109, capture-kit 36539892090 |
| 10 | [phase-10](test-reports/phase-10.md) | PASS - 1,327 tests, 0 failed, 3 skipped (Windows-only), 89.9% coverage; CI green: check 36534423550, agent-windows 36534423546, capture-kit 36534423565 |
| 09 | [phase-09.md](test-reports/phase-09.md) | PASS - 1,252 tests, 0 failed, 3 skipped (Windows-only), 89.5% coverage; CI green: check 36460856648 |
| 08 | [phase-08.md](test-reports/phase-08.md) | PASS - 1,204 tests, 0 failed, 3 skipped (Windows-only), 89.5% coverage; CI green: check 36444202147, capture-kit 36444202153 |
| 04 | [phase-04.md](test-reports/phase-04.md) | PASS on drafts - 804 tests, 0 failed, 0 skipped, 90.0% coverage; CI green: check 36294681749, capture-kit 36294681754, agent-windows 36294681770 |
| 03 | [phase-03.md](test-reports/phase-03.md) | PASS - 613 tests, 0 failed, 0 skipped, 89.3% coverage; CI run 36107675601 green |
| 02 | [phase-02.md](test-reports/phase-02.md) | PASS - 416 tests, 0 failed, 1 skipped (no Agent routes until P3), 90.2% coverage; CI run 36103266538 green |
| 01 | [phase-01.md](test-reports/phase-01.md) | PASS - 183 tests, 0 failed, 0 skipped, 91.4% coverage; CI run 35887137380 green |
| 00 | [phase-00.md](test-reports/phase-00.md) | PASS - 78 tests, 0 failed, 0 skipped, 83% coverage; CI run 35881605525 green |

## Benchmark (P9, 2026-09-28)
Same machine and method as P8. The dataset now also has 94,005 inventory lines. The P9 metrics and rankings are included, and the dashboard set adds the top 10 customers, the top 10 products and the product difference. Full plans: [docs/benchmarks/p8-analytics.md](benchmarks/p8-analytics.md) (now "P8, P9").

| | current FY (ms) | 3 years (ms) |
|---|---|---|
| customer_revenue total / drill-down | 301 / 586 | 348 / 685 |
| supplier_purchases total / drill-down | 221 / 423 | 246 / 480 |
| product_revenue total / drill-down | 74 / 113 | 102 / 133 |
| top 10 customers | 328 | 375 |
| top 10 products (revenue / quantity) | 86 / 97 | 121 / 129 |
| product difference | 274 | 306 |
| **dashboard set** (P8 figures + top customers, top products, difference) | **1,540** | **1,780** |

**Before the fix, the three-year numbers were:**
- the dashboard set: 2,623 ms;
- the top 10 customers: 847 ms (871 ms when run on its own);
- the customer drill-down: 1,122 ms (1,501 ms when run on its own).

**The causes and fixes** are in the P9.6 performance row above and in D-047. **Still to watch for P16's PERF-VAL-1 run:**
- the customer figures (~350 ms) do the attribution work on every call;
- a materialized per-voucher bucket, kept up to date by sync, is the upgrade if 10 concurrent users on the 17.2 hardware need it.

## Benchmark (P8, 2026-09-28)
SRS 17.2 dataset size (100,000 vouchers, 500,000 entries, 5,000 ledgers, 10,000 stock items; seed 8) in `tally_bench`, on this Mac (Apple M4, 16 GB, PostgreSQL 16.15 in Docker), one user. **Not PERF-VAL-1 evidence** (PERF-VAL-2): a design check before P9–P14 build on it. Median of 5 after a warm-up, as `tally_app`, through `app.analytics.query` exactly as the API calls it, with G26 treated as passed so return linking runs. "Series" is monthly; for balances the by-ledger breakdown. Full EXPLAIN (ANALYZE, BUFFERS) plans for the 3-year range: [docs/benchmarks/p8-analytics.md](benchmarks/p8-analytics.md).

| Metric | total FY / 3y (ms) | series FY / 3y | first drill-down page (50) FY / 3y |
|---|---|---|---|
| sales | 149 / 216 | 150 / 237 | 291 / 510 |
| purchases | 139 / 153 | 141 / 160 | 279 / 331 |
| expenses | 49 / 102 | 52 / 119 | 97 / 198 |
| cash_flow | 51 / 67 | 55 / 72 | 107 / 132 |
| cash_bank_position | 53 / 54 | 56 / 57 | 106 / 104 |
| receivables | 75 / 192 | 107 / 234 | 145 / 384 |
| payables | 184 / 187 | 194 / 195 | 367 / 369 |
| ledger_balances | 230 / 431 | 387 / 507 | 460 / 848 |
| unclassified_adjustments | 309 / 293 | 316 / 296 | 662 / 577 |
| **Dashboard summary** (sales total + series, purchases, expenses, cash-flow total + series, the three positions) | **905 / 1,279** against PERF-1.1's 3,000 | | |

**Condensed plans (3-year totals, from the EXPLAIN output):**
- sales 177 ms: a sequential scan of `voucher_entries` (500k rows; 280k kept by direction), a hash join to ledgers (90k in class), index lookups into `vouchers` by primary key, and a hashed subplan for linked credit notes (a parallel scan of `bill_allocations` for AGST_REF, then an index probe on `(company_id, ledger_id, reference_name)` per note).
- purchases 178 ms: the same shape.
- expenses 93 ms: parallel sequential scans of entries and vouchers; two scans of `cost_centre_allocations` (the parts and the remainder).
- cash_flow 72 ms and cash_bank_position 65 ms: index scan `ix_voucher_entries_company_id_ledger_id` (the list has 20 ledgers), then primary-key lookups into vouchers; openings by sequential scan (4,304 rows).
- receivables 106 ms and payables 82 ms: sequential scans of entries and vouchers (3,000 / 1,200 party ledgers make the index less useful than a scan).
- ledger_balances 409 ms: both halves; every ledger.
- unclassified_adjustments 350 ms: the linked-note subplan twice (credit and debit notes).

**Decision:** nothing is near 3 s. The slowest call is 848 ms: the 3-year ledger-balances first drill-down page, where the count and the sort cover every entry. It is not a dashboard call. The whole dashboard set is 1.3 s over 3 years and 0.9 s for the current FY, so **no index or query change was made**. Watch items for P16's PERF-VAL-1 run (10 concurrent users, 4 vCPU managed PostgreSQL):
- the drill-down counts every row: consider an estimated count or keyset paging if needed;
- the sales/purchases row estimates are off (558 estimated vs 89k actual). The plans are still sound, but extended statistics on `(accounting_direction, ledger_id)` are the first thing to try if a plan flips.

## Environment (recorded 2026-09-23, macOS arm64)
| Tool | Version |
|---|---|
| uv | 0.12.17 |
| Python | 3.12.14 (`python3.12`, /opt/homebrew/bin) |
| Node | v24.13.0 (npm 11.6.2) |
| Docker | 29.8.0 (Compose v5.5.1). Daemon running (verified 2026-09-23). |
| poppler / pdftotext | 26.09.0 |
| make | /usr/bin/make |

Notes for P0.11: the Read tool cannot render PDFs without poppler (now installed); transcribe with `pdftotext -layout docs/srs/Tally_SRS_v7_3_Complete.pdf`. Plain `pypdf` output flattens tables, so do not use it for the transcription.

## Gate status summary
All gates NOT TESTED (see docs/validation-gate.md).
