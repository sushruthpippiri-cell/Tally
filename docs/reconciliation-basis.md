# Reconciliation basis (P10.1, D-008, D-048)

What each reconciliation figure compares, on both sides, so that the Tally value and the local value measure the same thing. Written for the accountant reviewing it and for anyone changing a query later. The requirements are in SRS Section 9 (REC-1.x), ACC-9.5 and TEST-4.2.

## The rule
- **The Tally side is always a figure Tally computes.** It comes from a TDL aggregation or from Tally's own closing balance or closing quantity. It is uploaded into `reconciliation_tally_values`, and that table is used for nothing else.
- **The local side is always computed from the synced rows** (`voucher_entries`, `ledger_opening_balances`, `stock_snapshots`), through the Phase 8 query path (`app.analytics.query`).
- **Neither side is built from the other.** The local side never reads `reconciliation_tally_values`, and the Tally side never re-adds synced detail rows (SRS 9.1).
- **Classification is ours, not Tally's** (D-001).
  - Tally sends its totals **per ledger, per voucher type, per period**, identified by GUID.
  - Both sides then apply the **same** `Classes` (`app/analytics/classification.py`) and the same base voucher type (P6's resolver).
  - Only the adding up differs: Tally's own sums on one side, our SQL over the synced entries on the other.

## Which vouchers
- **Tally side.** The totals Collection takes its vouchers from the sync's own voucher Collection (`TA_VouchersColl`), so it applies the same filter: accounting vouchers only, not optional (GATE-G34). It then also leaves out cancelled vouchers (GATE-G9).
- **Local side.** ACTIVE vouchers only; CANCELLED and MISSING_IN_TALLY are left out (ACC-4.5).
- **Dates.** Every voucher request names its dates explicitly (D-048 #2), so no figure depends on the period currently selected in Tally.

## What each figure compares
| Metric | Tally figure | Local figure | Query used | Tolerance |
|---|---|---|---|---|
| `SALES_CREDITS`, per period | Σ credits in `TA_ReconTotals` rows for the period whose ledger is in the Sales class **and** whose voucher type has base type Sales | Σ `amount_absolute` of CREDIT entries on Sales-class ledgers in ACTIVE Sales-base vouchers dated in the period. **Raw: no return is subtracted, and tax ledgers are not included** | the Phase 8 `sales` query with return linking and tax switched off (`returns_linkable=False`, `taxable_value_mode=True`). With no note linked and no tax ledger, it is exactly this sum | money |
| `PURCHASE_DEBITS`, per period | Σ debits: Purchase-class ledgers, base type Purchase | Σ DEBIT entries on Purchase-class ledgers in ACTIVE Purchase-base vouchers in the period, raw | the Phase 8 `purchases` query, same switches | money |
| `RECEIPTS`, per period | Σ debits: Cash/Bank-list ledgers, base type Receipt | Σ DEBIT entries on Cash/Bank-list ledgers in ACTIVE Receipt-base vouchers in the period | `recon_receipts`: no Phase 8 metric has this basis, because cash flow nets every voucher type (D-021) | money |
| `PAYMENTS`, per period | Σ credits: Cash/Bank-list ledgers, base type Payment | Σ CREDIT entries on Cash/Bank-list ledgers in ACTIVE Payment-base vouchers in the period | `recon_payments` | money |
| `LEDGER_BALANCE`, per ledger, on the sync date D (today in the company's time zone) | Tally's closing balance from `TA_LedgerClosing`, from the start of the financial year containing D to D, Dr + (GATE-G19, G23) | **The Phase 8 balance.** A balance-sheet ledger: its books-beginning opening plus every ACTIVE entry up to D (D-039 #5). An income or expense ledger: its ACTIVE movement from the financial year start to D (ACC-9.2) | the Phase 8 `ledger_balances` query, by ledger | money |
| `STOCK_QTY`, per item, on D | Tally's closing quantity from `TA_StockClosing` on D (GATE-G18, G27) | the snapshot **the same reconciliation run** stored for D, moments earlier (D-048 #3) | direct read of `stock_snapshots` | quantity, only when the units match |

**Periods (REC-1.1).**
- Each calendar month of the current financial year, clipped to the year's start and to D.
- The current financial year to D.
- The previous financial year.
- The backend sends the periods in the run plan. Each period has its own Tally request, so a year's figure is Tally's own sum for the year, never our sum of its months.

## What each check can and cannot catch
**Sales, Purchases, Receipts and Payments share the voucher filter with the sync.**
- Both sides use the same voucher Collection and filter (G34). If that shared filter is wrong, the same vouchers are missing from both sides, and these four figures **still PASS**.
- They catch everything after the filter:
  - a voucher lost or doubled in upload, parsing or storage;
  - a wrong amount or direction;
  - a voucher wrongly left ACTIVE, CANCELLED or MISSING_IN_TALLY locally;
  - a ledger or voucher type synced under the wrong GUID.

**`LEDGER_BALANCE` is the check that does not share the filter.**
- Tally's closing balance is Tally's own figure over **all** of the ledger's vouchers, whatever our Collection selects.
- So a voucher the shared filter wrongly leaves out makes the balances of its ledgers FAIL, even while `SALES_CREDITS` passes. `tests/reconciliation/test_independence.py` tests exactly that case.

**`STOCK_QTY` checks storage and parsing only.**
- Local data cannot recompute stock (SRS 11.3). So the check compares the snapshot this run stored with a second read of Tally's closing quantity, taken moments later in the same run.
- A FAIL therefore means a storage or parsing problem, not normal trading between two syncs.

## Not compared
Some things cannot be compared on this basis. The response lists them, with the reason.

These make the run's overall result **FAIL**:
- A Tally totals row whose ledger or voucher type GUID is not in the local masters. The vouchers behind it cannot have synced either, so leaving the row out of both sides would hide the gap.
- A ledger Tally reports that is not in the local masters, or an ACTIVE local ledger that Tally did not report.
- A stock item without a snapshot from this run, or with a unit that differs from Tally's.

These are listed but do **not** make it FAIL, because Data Quality already reports them:
- A ledger whose balance is "opening balance unavailable" (ACC-9.6).
- A ledger with an unresolved group chain, which has no nature and so no Phase 8 balance (ACC-7.4). This includes Tally's own *Profit & Loss A/c*, whose Tally closing carries earlier years' profit.

## Tolerance (SRS 9.2)
- `absolute_difference = |tally − local|`.
- `percentage_difference = absolute_difference / |tally| × 100`, when tally ≠ 0.
- **Tally = 0:** PASS only when local = 0.
- **Otherwise:** PASS when the absolute difference ≤ the absolute tolerance **or** the percentage difference ≤ the percentage tolerance. Both limits are inclusive, so FAIL only when both are exceeded.
- **Defaults** (settings `reconciliation.*`):
  - money: ₹1.00 / 0.01 %;
  - quantities: 0 units / 0.5 %.

| Tally | Local | Result |
|---|---|---|
| ₹100,000 | ₹100,000.50 | PASS (within ₹1) |
| ₹100,000 | ₹100,010 | PASS (0.01 %, equal to the limit) |
| ₹100,000 | ₹100,012 | FAIL |
| ₹100,000 | ₹100,500 | FAIL |
| ₹0 | ₹0 | PASS |
| ₹0 | ₹50 | FAIL |

## When it runs (REC-1.4)
All three triggers go through one run type, RECONCILIATION:
- **Every day**, on the default schedule.
- **After every FULL sync** that ends COMPLETED or PARTIAL: the backend queues a RECONCILIATION command for the same Agent.
- **On demand**, via `POST /companies/{id}/reconciliation/run`.

A RECONCILIATION run does the following, in order:
1. Catches up like an incremental sync, so the local side is current.
2. Sends a full key list for every collection. Local-only records become MISSING_IN_TALLY through the same evaluation and D-007 guard as sync (REC-1.5, D-041). There is no second path.
3. Stores the stock snapshot and reads the comparison quantity in the same step.
4. Uploads the totals and the ledger closing balances.

The backend then compares the values within a minute and records one `reconciliation_results` row per comparison (REC-1.3).

## Gates
The values are drafts until these gates pass with live evidence:
- **G36:** the totals aggregation.
- **G37:** explicit voucher dates and post-dated vouchers.
- **G18:** stock closing on a date.
- **G19:** ledger closing on a date.
- **G21:** key lists.
- **G23:** Dr/Cr.

Until then, comparisons still run (a FAIL loses no data), and the response lists `unverified_gates` so the screen can say so.
