# Phase 12 — Stock analytics

**Size:** M · **Depends on:** P8 (and P5.6 snapshots)
**SRS:** 11 (all), 1.3 (godown/batch out of scope)
**Requirements:** FR-STK-1–20
**Acceptance:** AC-52, AC-53, AC-54 · **Gates:** G18, G27 · **Decisions:** D-009, D-016, D-019

## Goal
Every stock item with current stock or recent sales gets exactly one movement class, computed from Tally's own closing-quantity snapshot and net sales quantities, with the snapshot date and any unit limitations always visible.

## Tasks

### P12.1 Current stock
Latest `stock_snapshots` row per item is the current quantity (FR-STK-15). Every response includes `snapshot_date` (FR-STK-16). Company level only (FR-STK-17).

### P12.2 Units (FR-STK-8–10, G27)
- If G27 passed: convert every transaction quantity to the item's base unit before use (FR-STK-9).
- If not: use raw quantities, flag items that appear with more than one transaction unit, and return `limitations: ["Items sold in more than one unit are not converted; their quantities are not comparable."]` (FR-STK-10, AC-54). Register the "Multi-unit items" Data Quality check.

### P12.3 Sales quantity and last sale
- Period sales quantity per item = `voucher_items.quantity` on ACTIVE SALES-base vouchers in the period, minus linked-return quantities (FR-STK-6, D-019).
- `last_sale_date` per item across all synced history.
- Optional `sales_value` per item for the value-based ranking option.

### P12.4 Classification — `app/analytics/stock/classify.py` (D-009)
Period = `stock.measurement_period_days` (30/60/90/180 selectable, FR-STK-1). Evaluate in order; first match wins:
1. **Not classified**: stock ≤ 0 and no sale in period → excluded from movement views (FR-STK-19).
2. **Never sold**: no sale in all synced history and stock > 0 (FR-STK-12, FR-STK-13).
3. **Fast-moving**: sold in period and ranking value ≥ the `stock.fast_percentile` percentile of items sold in the period (FR-STK-2). Ranking value = quantity by default; `stock.fast_ranking_basis = value` uses sales value (FR-STK-20). Percentile via PostgreSQL `percentile_cont`.
4. **Normal**: sold in period, below the threshold (FR-STK-3).
5. **Dead stock**: last sale ≥ `stock.dead_stock_days` ago and stock > 0 (FR-STK-5).
6. **Slow-moving**: last sale > `stock.slow_threshold_days` and < `stock.dead_stock_days` ago (FR-STK-4).
7. **Gap case**: stock > 0, last sale outside the period but within the slow threshold → Normal with `note = "no sale in selected period"` (D-009).

### P12.5 Stock API
`GET /companies/{id}/analytics/stock?period_days=` → counts per class, paginated item lists with class, current quantity, unit, last sale date, period quantity/value, multi-unit flag; filter by class (Never Sold filterable on its own, FR-STK-14); `snapshot_date`; `limitations`.

### P12.6 Tests
- AC-52: stock > 0, no sales ever → Never Sold (not Slow, not Dead).
- AC-53: snapshot quantity 40, no sale for 200 days → Dead, snapshot date shown.
- AC-54: unit data unavailable, item sold in two units → flagged, limitation stated.
- Boundaries: last sale exactly 90, 91, 179, 180 days ago; period 30 vs 180 (gap case and overlap case); percentile ties; linked returns reduce quantity; cancelled vouchers excluded; zero-stock items with no sale in period excluded.

## Definition of done
Tests pass; `docs/metrics.md` extended with the stock rules and precedence.

## Kickoff prompt
~~~text
Read CLAUDE.md, docs/plan/phase-12-stock.md, docs/metrics.md, docs/decisions.md (D-009, D-016, D-019) and SRS Section 11. In plan mode, propose the classification query and a truth table covering every precedence rule and boundary. Wait for approval, implement P12.1–P12.6 with tests first, commit per task, update docs/progress.md.
~~~
