# Phase 10 — Reconciliation

**Size:** M · **Depends on:** P7, P8
**SRS:** 9 (all), 8.10 (ACC-9.5), 6.1 (reconciliation sync), 4.11 (AGT-6.4)
**Requirements:** REC-1.1–1.5, ACC-9.5, FR-1.1 (totals collection), SYNC-5.3, TEST-4.2
**Acceptance:** AC-38 (match with Tally), AC-40, AC-41, AC-42, AC-43, AC-44 · **Gates:** G18, G19, G21 · **Decisions:** D-007, D-008

## Goal
Prove, independently of the sync code path, that the local database matches Tally — using totals Tally computes itself, compared on identical bases, with the SRS tolerance rule.

## Tasks

### P10.1 Reconciliation basis — `docs/reconciliation-basis.md` (D-008)
For each metric, write the exact Tally-side and local-side definitions so they measure the same thing:

| Metric | Tally side (TDL Totals report) | Local side |
|---|---|---|
| SALES_CREDITS | Σ credits on ledgers under Sales-class groups in non-cancelled Sales-base vouchers, period | Same aggregation over ACTIVE vouchers (raw, no return adjustment) |
| PURCHASE_DEBITS | Mirror for purchases | Mirror |
| RECEIPTS | Σ debits on Cash/Bank ledgers in Receipt vouchers | Same |
| PAYMENTS | Σ credits on Cash/Bank ledgers in Payment vouchers | Same |
| LEDGER_BALANCE (per ledger, as of D) | Tally closing balance as of D (G19) | ACC-9.1 computed balance |
| STOCK_QTY (per item, as of D) | Tally closing quantity as of D (G18) | Stored snapshot for D (checks snapshot freshness/parsing — local data cannot recompute stock, SRS 11.3) |

Also state which periods are reconciled by default: each month of the current financial year, the current FY to date, and the previous FY.

### P10.2 TDL Totals and parser
Complete the totals Report/Collection in `tdl/` (separate from the detail Collections, SRS 9.1), request builders and `ReconciliationTotalRecord` parsing in `tally_contract`. Tag assumptions `# GATE-G18/G19`.

### P10.3 Agent RECONCILIATION mode
In the executor: pull totals for the configured periods, ledger closing balances and stock closing quantities as of today (company TZ), and full key lists for every collection (REC-1.5, SYNC-5.3). Upload via `POST /agent/commands/{id}/reconciliation` (D-006); key lists via the P6 endpoint.

### P10.4 Tolerance engine — `app/reconciliation/tolerance.py` (SRS 9.2)
Pure function on Decimals:
- `absolute_difference = |tally − local|`; `percentage_difference = absolute / |tally| × 100` when tally ≠ 0.
- tally = 0 → PASS only if local = 0.
- Otherwise PASS when absolute ≤ absolute tolerance **or** percentage ≤ percentage tolerance (both inclusive); FAIL only when both are exceeded.
- Money tolerances (₹1.00, 0.01 %) and quantity tolerances (0 units, 0.5 %) from settings.

### P10.5 Comparison job
After every FULL sync and every RECONCILIATION sync completes, and on demand (REC-1.4): compute local values per the basis, compare, write one `reconciliation_results` row per comparison (REC-1.3). Full key lists go through P6's evaluation — local-only records become MISSING_IN_TALLY (REC-1.5), still subject to the D-007 guard.

### P10.6 API
- `POST /companies/{id}/reconciliation/run` (optional `agent_id`, auto-routed like Sync Now) → creates a RECONCILIATION command.
- `GET /companies/{id}/reconciliation`: latest run (overall PASS/FAIL, per-metric Tally value, local value, absolute and percentage difference, result — REC-1.2), history, `only_failures` filter, per-ledger balance mismatches.
- Home status field for FR-4.1. Agents list: `uptime_advisory` becomes `prominent` when the latest reconciliation has a FAIL (AGT-6.4).

### P10.7 Tests
- AC-40: display fields present. AC-41–AC-43 and all six rows of the SRS 9.3 table (table-driven). AC-44: Tally 100 units, local 98, tolerances 0 / 0.5 % → FAIL.
- AC-38 (match): computed balance equals Tally closing balance within tolerance on fixtures.
- TEST-4.2 harness: for every ledger in the test dataset, computed balance vs Tally closing balance — runs on synthetic fixtures now and on `fixtures/xml/live/` when available.
- Results persisted; job triggered after FULL and RECONCILIATION runs only.

## Definition of done
Tests pass; `docs/reconciliation-basis.md` reviewed by you (the product owner) and the accountant.

## Kickoff prompt
~~~text
Read CLAUDE.md, docs/plan/phase-10-reconciliation.md, docs/metrics.md, docs/decisions.md (D-007, D-008) and SRS Section 9 and ACC-9.5. In plan mode, first draft docs/reconciliation-basis.md and show it to me; after I approve it, propose the TDL totals, agent mode, tolerance engine and job. Implement P10.1–P10.7 with tests first, commit per task, update docs/progress.md.
~~~
