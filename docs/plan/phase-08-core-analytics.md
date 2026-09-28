# Phase 8 — Core accounting analytics

**Size:** L (split: P8.1–P8.4, then P8.5–P8.10) · **Depends on:** P6
**SRS:** 8.1–8.4, 8.7–8.10, 8.12, 8.14, 17.5, 19.2 (analytics rows)
**Requirements:** ACC-1.1, 1.2, 1.5, 1.6, 1.7, ACC-2.1, 2.2, ACC-3.1, 3.3, 3.4, ACC-4.4, 4.5, ACC-5.1–5.5, ACC-7.x (use), ACC-8.x (use), ACC-9.1–9.6, ACC-DATA-1, FR-2.1
**Acceptance:** AC-26, 27, 28, 29, 34, 35, 36, 37, 38 (computed part), 62, 63 (in series) · **Gates:** G14, G16, G26 · **Decisions:** D-001, D-016, D-020, D-021 (ACCEPTED 2026-09-28), D-044

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
- Expenses (**D-044 #5, owner**): the net movement on Expense-class ledgers, Σ `amount_signed` (debit +) of ACTIVE entries in any voucher. A credit to an expense ledger reduces expenses; a reclassification between two expense heads changes the breakdown, not the total (departs from ACC-1.5's "DEBIT entries"). Group by ledger, predefined group, or cost centre. By cost centre uses `cost_centre_allocations.amount_absolute`; the unallocated remainder appears as "(No cost centre)" so the breakdown totals the metric.

### P8.6 Cash flow (ACC-1.6, 1.7, 3.1, 3.3, 3.4; D-021 ACCEPTED)
Every movement on Cash/Bank allow-list ledgers on ACTIVE vouchers of any base type (Sales/Purchase with cash as the party, Journals, Contras) counts. Each voucher contributes the net of its entries on list ledgers (`amount_signed`, debit +): net > 0 inflow, net < 0 outflow, 0 (a transfer between own cash and bank ledgers) nothing. A Contra to a ledger outside the list (e.g. an unlisted Bank OD) counts. `cashflow.include_journal` defaults to **true**; false leaves JOURNAL vouchers out. **Invariant, tested directly:** net cash flow for any period = the change in the Cash/Bank allow-list balance over it. Net series by period; the response states the rule.

### P8.7 Balances — `metrics/balances.py` (ACC-9.x)
- ~~ACC-9.1 as worded (opening for the FY containing D)~~ — replaced by the roll-forward rule below (D-039 #5). Metrics: `cash_bank_position`, `receivables`, `payables`, `ledger_balances` (D-045 #2); unavailable openings are named in the response (D-045 #3).
- Income/expense ledgers (nature from primary group) report period movement only (ACC-9.2).
- **Blank openings (D-044 #6, GATE-G16):** our TDL always emits `OPENINGBALANCE`; present but blank or zero → a zero opening is stored; absent → no row → "unavailable". Done in session 1 (parser).
- **Balances (D-039 #5, owner decision):** openings are stored as at the company's books-beginning date (`companies.books_from`). A balance-sheet ledger's balance on any date D = its books-beginning opening + all ACTIVE movements from `books_from` to D, so a company with several years of books needs no separate opening per year. "Opening balance unavailable" (ACC-9.6, never zero) applies only when the ledger has no books-beginning opening row at all. P10 verifies the computed balances against Tally closing balances (G19).
- Cash and bank position, total receivables (Sundry Debtors), total payables (Sundry Creditors) on D (ACC-9.3, 9.4). Display with Dr/Cr.

### P8.8 Analytics API
`GET /companies/{id}/analytics/{metric}` for `sales`, `purchases`, `expenses`, `cash-flow`, `balances`, `unclassified-adjustments`, with `from`, `to`, `granularity` (day|month|quarter), filters, `group_by`. Response: `{metric, filters_applied, company_timezone, summary, series[], breakdown[], notes[]}`. Permission VIEW_FINANCIALS.

### P8.9 Architecture guards (written in P8.1, D-044 #1, #4)
- AST test over `app/analytics`, `app/exports`, `app/reconciliation`, `app/anomaly`: no `amount_raw` (AC-34 second half).
- Every metric module exposes exactly one public function, `detail_query`, and calls `select(` nowhere else; entry tables are queried only from approved modules (ACC-4.4).

### P8.10 Tests
- AC-26: Sales voucher Dr customer ₹10,000 / Cr Sales ₹10,000 → Total Sales ₹10,000 (not 20,000, not 0).
- AC-27: purchase counts only the purchase-ledger debit.
- AC-28: ledger under "Sales – Online" under Sales Accounts is included.
- AC-29: "POS Invoice" derived from Sales included exactly like Sales.
- AC-35 (with G26 forced PASSED in the test): linked credit note reduces sales. AC-36: unlinked note not subtracted, listed in Unclassified Adjustments.
- AC-37: Receipt ₹5,000, Payment ₹3,000, Contra cash↔bank ₹10,000 → +5,000 and −3,000, contra nets to 0. Plus: cash sale inflow, cash purchase outflow, Journal Dr Bank inflow, a Contra from a listed bank to an unlisted Bank OD is an outflow, and the D-021 invariant (net = change in Cash/Bank balance) over several periods and as a property test.
- Expenses: a journal crediting an expense ledger reduces expenses; a reclassification between two expense ledgers changes the breakdown, not the total.
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
