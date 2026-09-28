# Metrics (Phase 8)

What each figure means, in plain English, and where its SQL lives. Written for the accountant reviewing the rules and for later phases building on them. The binding decisions are in `docs/decisions.md`: D-001, D-020, D-021, D-039 #5, D-044, D-045.

## Rules every metric follows
- **One detail query per metric** (D-044 #1).
  - Each metric is a module `backend/app/analytics/metrics/<name>.py` with one function, `detail_query(ctx)`. It returns one row per thing that contributes to the figure, with its signed `amount`.
  - The total, the period series, every breakdown and the drill-down are all sums of those same rows, built only in `backend/app/analytics/query.py`. So the dashboard, the drill-down and (from P14) the export cannot disagree (ACC-4.4, FR-DD-5).
  - Tests fail if a metric gets a second query path (`tests/analytics/test_architecture.py`).
- **Voucher status.** Only ACTIVE vouchers count. Cancelled vouchers and vouchers no longer in Tally (MISSING_IN_TALLY) count only when the request explicitly asks for them (ACC-4.5).
- **Classification** (D-001).
  - A ledger belongs to a class (Sales, Purchase, Expense, Cash/Bank, Tax) when its classification anchor is in that class's list in Settings. The anchor is its nearest predefined Tally group, or its own top-level group.
  - Customers are ledgers anchored at Sundry Debtors; suppliers at Sundry Creditors.
  - A ledger whose group chain is broken has no anchor and is in no class (ACC-7.4). Data Quality lists it.
- **Voucher types.** "Is it a sale?" is the voucher type's base type (so "POS Invoice" derived from Sales is a sale, ACC-8.2). A type that can't be resolved is OTHER and never counts as a sale or purchase (ACC-8.3).
- **Amounts.** Only the normalized direction and amounts are read, never Tally's raw text (ACC-DATA-1, AC-34). Money is summed in the database as exact decimals and sent as strings.
- **Dates.** A voucher's date is Tally's date and is never shifted (D-020). "Today", default ranges and any timestamp use the company's time zone. Periods are grouped inside SQL; quarters count from the financial year start (or calendar quarters, per the `analytics.quarter_mode` setting) (D-044 #2).
- **Returns** (ACC-5.x).
  - A credit note is a sales return only when it names, "against reference", a bill created by an ACTIVE sale to the same party; debit notes mirror this for purchases.
  - How Tally exports that link is gate G26. **Until G26 passes, no note is a return**: none is subtracted, and all are listed under Unclassified Adjustments.
  - Code: `backend/app/analytics/returns.py`.

## The metrics
API: `GET /companies/{id}/analytics/{metric}` and `…/{metric}/drilldown`, with `from`, `to` (default: the financial year to date), `granularity` (day | month | quarter), `group_by`, `include_cancelled` and `include_missing`. Permission: VIEW_FINANCIALS.

| Metric (API name) | In plain English | Rows | Sign | Group by | SQL entry point |
|---|---|---|---|---|---|
| Total Sales Revenue (`sales`) | What was sold: the credits to sales ledgers on sales vouchers, less the sales-ledger debits on linked credit notes. The customer's side is never read, so a sale counts once (AC-26). Output tax is left out in taxable-value mode (the default) (ACC-1.1, 2.1, 2.2) | one per entry | + sale, − return | ledger | `metrics/sales.py` → `returns.gross_less_returns` |
| Purchase Value (`purchases`) | The mirror of sales: debits to purchase ledgers on purchase vouchers, less the purchase-ledger credits on linked debit notes; input tax is left out in taxable-value mode (ACC-1.2) | one per entry | + purchase, − return | ledger | `metrics/purchases.py` → `returns.gross_less_returns` |
| Expenses (`expenses`) | **The net movement on expense ledgers**, in any voucher. A credit to an expense (a reversed provision, a refund, a rate difference) reduces it; moving an amount from one expense head to another changes the breakdown, not the total. This matches Tally's Profit & Loss. **Departs from ACC-1.5's "debit entries only" (D-044 #5)** | one per cost-centre allocation, plus the unallocated remainder as "(No cost centre)" (D-045 #1) | debit + | ledger, group (the anchor), cost_centre | `metrics/expenses.py` |
| Cash flow (`cash-flow`) | **Every movement on Cash/Bank-list ledgers, in any voucher type**: receipts, payments, cash sales and purchases, journals and contras. Each voucher counts once, as the net of its cash/bank lines: positive is an inflow, negative an outflow. A transfer between the company's own listed cash and bank ledgers nets to zero and drops out; a transfer to a ledger *not* on the list (e.g. an overdraft account that isn't listed) is an outflow. Journals count unless `cashflow.include_journal` is switched off. **Invariant:** net cash flow for any period = the change in the Cash & Bank position over it. **Departs from ACC-1.6, 1.7, 3.3, 3.4 as worded (D-021)** | one per voucher (net ≠ 0) | inflow +, outflow − (ACC-3.1) | flow (INFLOW / OUTFLOW) | `metrics/cash_flow.py` |
| Cash and bank position (`cash-bank-position`) | The balance of the Cash/Bank-list ledgers on the `to` date. An overdraft ledger counts only if it is added to that list (ACC-9.3) | balance rows (below) | Dr + (shown Dr/Cr) | ledger | `metrics/cash_bank_position.py` → `blocks.balance_rows` |
| Receivables (`receivables`) | The balance of customer ledgers (anchored at Sundry Debtors) on the `to` date (ACC-9.4) | balance rows | Dr + | ledger | `metrics/receivables.py` |
| Payables (`payables`) | The balance of supplier ledgers (anchored at Sundry Creditors) on the `to` date; normally a credit (ACC-9.4) | balance rows | Dr + (so usually shown Cr) | ledger | `metrics/payables.py` |
| Ledger balances (`ledger-balances`) | Every classified ledger. An asset or liability ledger is its balance on the `to` date. An income or expense ledger shows only its movement between `from` and `to`, so it never carries into the next year (ACC-9.2). All ledgers together always total zero; read it by ledger | balance rows, and entries for income/expense | Dr + | ledger | `metrics/ledger_balances.py` |
| Unclassified Adjustments (`unclassified-adjustments`) | Credit and debit notes not linked to an original bill (UNLINKED_CREDIT_NOTE / UNLINKED_DEBIT_NOTE). They are never subtracted from sales or purchases (ACC-5.3, 5.4). Shows what each note would have reversed: its sales- or purchase-ledger lines. Data Quality lists the notes themselves (`unlinked_notes`) | one per entry | + | type, ledger | `metrics/unclassified_adjustments.py` |

### Balances (D-039 #5, D-044 #6, D-045 #3)
- **The rule.** A balance on date D = the ledger's opening at the start of the books (`books_from`) + every ACTIVE movement from then to D. One opening serves every later year.
  - This replaces ACC-9.1's "opening for the financial year containing D". Tally's ledger opening is as at the start of the books.
  - The rows are one opening row per ledger (dated `books_from`) plus the entries (`blocks.balance_rows`).
- **Openings.** A blank opening in Tally's export is a zero opening. Our TDL always sends the field, and Tally leaves a zero opening blank (GATE-G16). A ledger with no opening at all has no row.
- **Unavailable.** A ledger with no opening row makes every figure it is part of **"opening balance unavailable"**, never a partial sum (ACC-9.6).
  - The response names those ledgers (up to 20, with the count) and points to the Data Quality check `ledgers_without_opening_balance`.
- **Checking against Tally.** P10 checks the computed balances against Tally's own closing balances (ACC-9.5, G19).

## Speed (PERF-1.1)
Measured at the SRS 17.2 size (100,000 vouchers, 500,000 entries): see `docs/benchmarks/p8-analytics.md` and the P8 entry in `docs/progress.md`. To reproduce: `make bench-data && make bench-analytics`.
