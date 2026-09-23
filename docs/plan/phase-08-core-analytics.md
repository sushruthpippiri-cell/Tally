# Phase 8 — Core accounting analytics

**Size:** L (split: P8.1–P8.4, then P8.5–P8.10) · **Depends on:** P6
**SRS:** 8.1–8.4, 8.7–8.10, 8.12, 8.14, 17.5, 19.2 (analytics rows)
**Requirements:** ACC-1.1, 1.2, 1.5, 1.6, 1.7, ACC-2.1, 2.2, ACC-3.1, 3.3, 3.4, ACC-4.4, 4.5, ACC-5.1–5.5, ACC-7.x (use), ACC-8.x (use), ACC-9.1–9.6, ACC-DATA-1, FR-2.1
**Acceptance:** AC-26, 27, 28, 29, 34, 35, 36, 37, 38 (computed part), 62, 63 (in series) · **Gates:** G14, G16, G26 · **Decisions:** D-001, D-016, D-020, D-021

## Goal
Deterministic, single-sided, correctly classified metrics for sales, purchases, expenses, cash flow and balances, built on an architecture where summaries, drill-downs and exports cannot disagree.

## Tasks

### P8.1 Analytics architecture — `app/analytics/`
- `filters.py`: `AnalyticsFilter(company_id, date_from, date_to, customer_ids?, stock_item_ids?, cost_centre_ids?, include_cancelled=False, include_missing=False)` (FR-4.3, ACC-4.5).
- `classification.py`: loads allow-lists from settings and returns sets of `classification_group_id`s for Sales, Purchase, Expense, Cash/Bank, Tax, plus customer (Sundry Debtors) and supplier (Sundry Creditors) sets (ACC-7.3, 7.6, D-001). Ledgers under UNRESOLVED groups are never in any class (ACC-7.4); a ledger whose anchor is in no allow-list is simply in no class, and is listed in Data Quality (D-001 case 3).
- `metrics/<metric>.py`: each metric defines **one** `detail_query(filter) -> Select` returning one row per contributing entry (voucher_id, voucher_date, voucher_number, voucher_type_name, base_voucher_type, ledger_id, ledger_name, contribution amount with the metric's sign, plus dimensions). Shared helpers build `total`, `by_period(granularity)`, `by_dimension(dim)` and `drilldown(page)` from that subquery. This guarantees ACC-4.4 and FR-DD-5 by construction.
- `periods` from `app/core/periods.py` for day / month / financial quarter (FR-2.1, Q-1.x).
- Result DTOs serialize Decimal as strings.

### P8.2 Base building blocks
Reusable CTEs/selectables: `active_vouchers` (ACTIVE unless include flags), `typed_vouchers` (joins `base_voucher_type`; OTHER excluded from type-filtered metrics, ACC-8.3), `classified_entries` (entries + ledger class flags). Only `accounting_direction`, `amount_absolute`, `amount_signed` are read (ACC-DATA-1).

### P8.3 Returns classification — `metrics/returns.py` (ACC-5.x)
- For each ACTIVE CREDIT_NOTE (DEBIT_NOTE) voucher: **linked** only if gate G26 passed **and** the party entry has an AGST_REF allocation whose `(ledger_id, reference_name)` matches a NEW_REF created by a SALES (PURCHASE) voucher. Otherwise `UNLINKED_CREDIT_NOTE` / `UNLINKED_DEBIT_NOTE` (ACC-5.3). Until G26 passes, every note is unlinked (ACC-5.5).
- Return amount = DEBIT entries on Sales-class ledgers in a linked credit note (CREDIT entries on Purchase-class ledgers in a linked debit note); tax ledgers excluded in taxable-value mode.
- Unlinked notes are never subtracted (ACC-5.4); `GET /analytics/unclassified-adjustments` lists them; register the Data Quality check.

### P8.4 Total Sales Revenue — `metrics/sales.py` (ACC-1.1, ACC-2.1, ACC-2.2)
Detail rows: CREDIT entries on Sales-class ledgers in ACTIVE SALES-base vouchers (positive) plus linked-return rows (negative). Tax-class ledgers excluded when `analytics.taxable_value_mode` is true; when false, CREDIT entries on tax ledgers in the same vouchers are included. Never sums a voucher's entries as a whole.

### P8.5 Purchases and expenses (ACC-1.2, ACC-1.5)
- Purchase Value mirrors sales: DEBIT entries on Purchase-class ledgers in PURCHASE-base vouchers, minus linked purchase returns, tax excluded.
- Expenses: DEBIT entries on Expense-class ledgers in any ACTIVE voucher; group by ledger, predefined group, or cost centre. By cost centre uses `cost_centre_allocations.amount_absolute`; the unallocated remainder appears as "(No cost centre)" so the breakdown totals the metric.

### P8.6 Cash flow (ACC-1.6, 1.7, 3.1, 3.3, 3.4; D-021)
Inflow = DEBIT on Cash/Bank-class ledgers in RECEIPT vouchers (+); outflow = CREDIT on Cash/Bank ledgers in PAYMENT vouchers (−); CONTRA excluded; JOURNAL included only when `cashflow.include_journal` (debit +, credit −). Net series by period. Response carries a note stating the voucher types counted (see D-021).

### P8.7 Balances — `metrics/balances.py` (ACC-9.x)
- Balance-sheet ledger on date D = opening balance for the financial year containing D (signed, DEBIT +) + Σ `amount_signed` of ACTIVE entries from FY start to D (ACC-9.1).
- Income/expense ledgers (nature from primary group) report period movement only (ACC-9.2).
- No opening row for that year → `opening_available = false`, balance `null`, label "opening balance unavailable" — never zero (ACC-9.6). If G16 shows Tally exports only the books-beginning opening, compute later-year openings as opening + net movement (balance-sheet ledgers only) and flag them `derived = true`; P10 verifies them against Tally closing balances.
- Cash and bank position, total receivables (Sundry Debtors), total payables (Sundry Creditors) on D (ACC-9.3, 9.4). Display with Dr/Cr.

### P8.8 Analytics API
`GET /companies/{id}/analytics/{metric}` for `sales`, `purchases`, `expenses`, `cash-flow`, `balances`, `unclassified-adjustments`, with `from`, `to`, `granularity` (day|month|quarter), filters, `group_by`. Response: `{metric, filters_applied, company_timezone, summary, series[], breakdown[], notes[]}`. Permission VIEW_FINANCIALS.

### P8.9 Architecture guards
- Test that parses every module under `app/analytics` (AST) and fails on any reference to `amount_raw` (AC-34 second half).
- Test that every metric module exposes exactly one `detail_query`.

### P8.10 Tests
- AC-26: Sales voucher Dr customer ₹10,000 / Cr Sales ₹10,000 → Total Sales ₹10,000 (not 20,000, not 0).
- AC-27: purchase counts only the purchase-ledger debit.
- AC-28: ledger under "Sales – Online" under Sales Accounts is included.
- AC-29: "POS Invoice" derived from Sales included exactly like Sales.
- AC-35 (with G26 forced PASSED in the test): linked credit note reduces sales. AC-36: unlinked note not subtracted, listed in Unclassified Adjustments.
- AC-37: Receipt ₹5,000, Payment ₹3,000, Contra ₹10,000 → +5,000 and −3,000, contra excluded.
- AC-38 (computed part): bank ledger ₹50,000 Dr opening + ₹20,000 net Dr → ₹70,000 Dr.
- Cancelled and MISSING_IN_TALLY vouchers excluded from every metric; UNRESOLVED ledgers excluded; missing opening → "unavailable".
- Series grouped by financial quarter (AC-63) and by local day (AC-62 via D-020).
- Property test (hypothesis): random balanced Sales vouchers → Total Sales equals Σ generated sales credits; no metric changes when a voucher's debit side is duplicated onto non-class ledgers.

## Definition of done
All tests pass; `docs/metrics.md` defines each metric in plain English with its SQL entry point, so P9–P14 sessions and the accountant can review the rules.

## Kickoff prompt
~~~text
Read CLAUDE.md, docs/plan/phase-08-core-analytics.md, docs/decisions.md (D-001, D-016, D-020, D-021) and SRS Sections 8.1–8.4, 8.7–8.10, 8.12, 8.14. In plan mode, propose the detail_query architecture with one worked example (Total Sales) in SQL, then the list of metrics and tests. Implement P8.1–P8.4, stop and update docs/progress.md; P8.5–P8.10 in the next session. Tests first, commit per task.
~~~
