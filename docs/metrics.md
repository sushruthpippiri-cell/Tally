# Metrics (Phases 8–14)

What each figure means, in plain English, and where its SQL lives. Written for the accountant reviewing the rules and for later phases building on them. The binding decisions are in `docs/decisions.md`: D-001, D-020, D-021, D-039 #5, D-044, D-045, D-046, D-047.

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
| Customer-attributed Revenue (`customer-revenue`) | Total Sales Revenue split by customer. A sale with exactly one customer ledger among its entries is that customer's; a cash sale (no customer) or a sale naming two or more customers is **Unattributed Customer Revenue**, never split by guesswork (ACC-6.1–6.3). A linked return comes off **the bucket its original sale was counted in** (D-046 #1). The rows are exactly Total Sales' rows, so customers + Unattributed always equal Total Sales (ACC-6.4) | one per sales entry, with `party_id` (NULL = Unattributed) | as sales | customer | `metrics/customer_revenue.py` → `returns.attributed` |
| Supplier-attributed purchases (`supplier-purchases`) | The same for Purchase Value and suppliers (Sundry Creditors) (ACC-1.4) | one per purchase entry | as purchases | supplier | `metrics/supplier_purchases.py` → `returns.attributed` |
| Product-attributed Revenue (`product-revenue`) | The inventory lines (`voucher_items.amount`) of sales vouchers, less the lines of linked credit notes (ACC-1.8, D-046 #2–3). Lines are before tax | one per inventory line, with item, quantity and unit | + sale, − return | product | `metrics/product_revenue.py` → `blocks.items` |

### Filters, drill-down narrowing and the product difference (P14: D-053)
- **Filters (FR-4.3).** `customer`, `product` and `cost_centre` narrow only the metrics whose rows carry that dimension: customer → Customer-attributed Revenue and Receivables; product → Product-attributed Revenue; cost centre → Expenses. Any other figure is not narrowed, and the response lists the filter in `filters_applied.not_applicable` (the screen says so). Total Sales Revenue is never narrowed by customer: a customer's sales are their Customer-attributed Revenue.
- **Narrowing (`by`).** `by=<group_by option>:<key>`, repeatable, keeps only the rows of one breakdown value (`key` `none` is the NULL bucket: Unattributed, "(No cost centre)"). The metric endpoint with `by` gives the next level's breakdown; the drill-down with `by` gives the rows. Both apply in `query.detail`, so the drill-down total is the figure expanded (FR-DD-5).
- **Product difference** (`product-difference`). Its own metric: Total Sales Revenue's rows (+) and Product-attributed Revenue's lines (−), leaving out vouchers where they cancel out. Its total is Total Sales − Product-attributed; grouped by voucher it lists the contributing vouchers (FR-DD-4). The response carries the one label (ACC-VAL-1).
- **Drill-down pages** are ordered by date, number, voucher, ledger and then every other column, so no row repeats or goes missing between pages.

### Balances (D-039 #5, D-044 #6, D-045 #3)
- **The rule.** A balance on date D = the ledger's opening at the start of the books (`books_from`) + every ACTIVE movement from then to D. One opening serves every later year.
  - This replaces ACC-9.1's "opening for the financial year containing D". Tally's ledger opening is as at the start of the books.
  - The rows are one opening row per ledger (dated `books_from`) plus the entries (`blocks.balance_rows`).
- **Openings.** A blank opening in Tally's export is a zero opening. Our TDL always sends the field, and Tally leaves a zero opening blank (GATE-G16). A ledger with no opening at all has no row.
- **Unavailable.** A ledger with no opening row makes every figure it is part of **"opening balance unavailable"**, never a partial sum (ACC-9.6).
  - The response names those ledgers (up to 20, with the count) and points to the Data Quality check `ledgers_without_opening_balance`.
- **Checking against Tally.** P10 checks the computed balances against Tally's own closing balances (ACC-9.5, G19).

### Attribution, the product difference and rankings (P9: D-046, TOPN-1.x)
- **Attribution.** Customer and supplier figures are Total Sales' and Purchase Value's own rows, each tagged with a bucket.
  - A voucher's bucket is its one party ledger, or none (`blocks.party_bucket`).
  - A linked return's bucket is its originals' bucket. When the originals are in different buckets, the return goes to Unattributed.
  - Tested as an invariant with returns, on a mixed dataset and against a model in a property test.
- **Product difference.** Total Sales Revenue − Product-attributed Revenue (`query.product_difference`), under **exactly one** label (ACC-VAL-1).
  - "Unattributed / Non-product Sales Revenue" requires both that gate G28 has passed (product revenue proven on the same basis) **and** that taxable-value mode is on. Inventory lines are before tax, so with tax in Total Sales the difference would be mostly tax (D-046 #5).
  - Otherwise the label is "Product Attribution Difference": a data-quality figure, not an accounting claim (ACC-1.10).
- **Rankings** (`query.ranking`; API `…/analytics/customers`, `/suppliers`, `/products`).
  - A Top-N list is the full ranked list's own query with a LIMIT (TOPN-1.2). N defaults to the company's `analytics.top_n_default` (10); `top_n` overrides it and `view_all` removes the cut-off.
  - Unattributed is shown apart and never ranked.
  - No total of the listed rows is ever returned, and the response says the list is not meant to add up to the reference total (TOPN-1.4).
- **Quantities and units** (D-046 #4, FR-STK-10).
  - Products ranked by quantity are ranked per (item, unit), with the unit beside every quantity. Quantities in different units are never added.
  - An item sold in more than one unit is flagged `multiple_units` on each of its rows.
  - Converting to base units (FR-STK-9) waits for gate G27 and P12.

## Aging and payment behaviour (P11: D-049, SRS 10)
- **Where the rows come from.** Two detail queries, `receivable_bills` (customer ledgers) and `payable_bills` (supplier ledgers), give one row per bill allocation on an ACTIVE voucher dated on or before the as-of date, plus the ledger masters' opening bills as New References (D-022). UNSUPPORTED allocations are left out and listed in Data Quality (AGE-BILL-1, 2). All of aging is summed from these rows in `backend/app/analytics/aging.py`.
- **Signs.** Each row keeps its own direction: on the receivable side a debit is +, on the payable side a credit is +. A sale's New Reference raises the bill, a receipt's Against Reference lowers it, a refund paid back against it raises it again (D-049 #1).
- **A bill** is a (ledger, reference) with a New Reference. Its outstanding on the as-of date is the sum of its New and Against References (FR-AGE-1, FR-AGE-2). Its bill date is the New Reference's voucher date (or the opening bill's date), its due date the New Reference's.
  - **Over-settled** (outstanding below zero): shown as a **Credit**, a positive amount marked Cr, never in a bucket; also in Data Quality "Over-settled bills".
  - **Reused name** (New References from more than one voucher, e.g. invoice numbers restarting each year): still one bill, marked unverified (GATE-G31) and listed in Data Quality "Bill reference reused" (D-049 #7).
- **Buckets** (SRS 10.1), from the as-of date (default: today in the company's time zone):
  - due date after it: **Not yet due** (never negative days);
  - no due date: **Due date unavailable**;
  - otherwise days overdue = as-of − due date, into the `aging.bucket_boundaries` buckets (default 0–30, 31–60, 61–90, 90+; a bill due that day is 0 days).
- **Kept out of the buckets, shown apart, per side, never netted across sides** (AGE-BILL-3, 4): Unadjusted Advances (an advance, less any Against Reference made to it later, GATE-G25), On-Account / Unallocated, unmatched settlements (Against References with no bill or advance; Data Quality "Unmatched settlements"). Each party's **net exposure** is the sum of all its rows.
- **No bill details** (SRS 10.3): a customer or supplier ledger that is not bill-wise, or has no bill rows, is one line with its balance (the `receivables` / `payables` figure) and "bill details not available".
- **Payment behaviour** (customers, FR-PAY-1–6, D-049 #5):
  - a settlement is an Against Reference that lowers a customer's bill **on a Receipt voucher**, dated in the trailing `payment.window_days` (365); each part settlement counts on its own. Credit notes, journals and other settlements are excluded and counted in the notes (a departure from FR-PAY-2's wording: a return is not a payment);
  - average days to pay = Σ(amount × (settled − bill date)) ÷ Σ amount; average days past due uses the due date, early payments count as 0, bills without a due date are left out and counted;
  - fewer than `payment.min_settlements` (3) settlements: "insufficient history";
  - hidden until gate G25 passes (FR-PAY-6).
- **Unverified gates.** Every aging and payment-behaviour response lists G25 and G31 while they have not passed.

## Stock movement (P12: D-050, SRS 11)
- **Current stock** is Tally's own closing quantity: the item's latest snapshot dated on or before today (FR-STK-15). Every item shows the snapshot date it used (FR-STK-16). An item with no snapshot is **Stock unknown**, never zero. When the newest snapshot is older than `stock.snapshot_stale_days` (2) days, the response warns and names its date.
- **The period** is the last `stock.measurement_period_days` days ending today in the company's time zone (30, 60, 90 or 180; default 90).
- **Sales** come from the `product_revenue` detail query (P9): the item's lines on ACTIVE sales vouchers, less the lines of linked credit notes. **Last sale** is the latest sales line; a return is not a sale.
- **Fast-moving is ranked by sales value** (FR-STK-20, owner): the items sold in the period whose value is at or above the 75th percentile (`stock.fast_percentile`, PostgreSQL `percentile_cont`) of the values of all items sold in the period. Ties at the threshold are all fast; one item sold is fast.
- **Classes, first match wins:**
  1. Fast (sold in the period, at or above the threshold);
  2. Normal (sold in the period, below it);
  3. Stock unknown (not sold in the period, no snapshot);
  4. Not classified (not sold in the period, stock zero or less; left out of the movement views, FR-STK-19);
  5. **No sale since the books began** (the SRS's "Never sold", FR-STK-12/13): stock above zero and no sale in the synced history. The synced history starts at the company's books-beginning date, so an item sold before it (for example in last year's Tally company) is here too; the response names the date;
  6. Dead (no sale for `stock.dead_stock_days`, 180, or more);
  7. Slow (last sale more than `stock.slow_threshold_days`, 90, and less than 180 days ago);
  8. Normal with "no sale in selected period" (last sale within 90 days but outside a shorter period).
  Every active item is in exactly one class.
- **Units.** Classes never compare quantities. Quantities are shown per unit and never added across units; an item seen in more than one unit is flagged, the limitation is stated, and Data Quality lists it (FR-STK-10). Conversion to the base unit waits for gate G27.

## Speed (PERF-1.1)
Measured at the SRS 17.2 size (100,000 vouchers, 500,000 entries, 94,000 inventory lines): see `docs/benchmarks/p8-analytics.md` and the P8 and P9 benchmark entries in `docs/progress.md`. Analytics statements are planned for their own dates (D-047). To reproduce: `make bench-data && make bench-analytics`.
