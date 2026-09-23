# Phase 11 — Aging & payment behaviour

**Size:** M · **Depends on:** P8
**SRS:** 10 (all), 8.10 (ACC-9.4)
**Requirements:** FR-AGE-1, FR-AGE-2, AGE-BILL-1–5, FR-PAY-1–6, TZ-1.1
**Acceptance:** AC-45 to AC-51 · **Gates:** G25 (allocation types; payment behaviour hidden until PASSED), G31 · **Decisions:** D-004, D-022

## Goal
Receivables and payables aged per bill reference using due dates, with advances and on-account amounts kept visible but out of the buckets, and a payment-behaviour metric that only appears once the underlying data is verified.

## Tasks

### P11.1 Allocation types (AGE-BILL-1, 2, 5)
Confirm P4's `BILL_TYPE_MAP` output in stored rows. UNSUPPORTED allocations are excluded from aging and listed: register the "Unsupported bill allocations" Data Quality check.

### P11.2 Bills — `app/analytics/aging/bills.py`
- Bill key `(company_id, ledger_id, reference_name)` (D-004). Side: RECEIVABLE for Sundry Debtors-class ledgers, PAYABLE for Sundry Creditors-class ledgers; other bill-wise ledgers are out of aging.
- Sources: NEW_REF allocations on ACTIVE vouchers, plus `opening_bill_allocations` treated as New References (D-022).
- `bill_date` = voucher date of the New Reference (or the opening bill date); `due_date` from the New Reference (nullable).
- Outstanding as of a date = signed net of the New Reference and all Against Reference allocations for the same bill dated on or before that date (FR-AGE-2), using `accounting_direction` (receivable: debit +; payable: credit +). For the standard case this equals "New Reference minus Against References".
- Against References with no matching bill → "Unmatched settlements" Data Quality item. Negative outstanding → "Over-settled bills" Data Quality item, not bucketed.

### P11.3 Buckets (SRS 10.1)
`today` = `periods.today(company)`. `due_date > today` → Not yet due (never negative days). Otherwise `days = today − due_date` into buckets built from `aging.bucket_boundaries` (default [30, 60, 90] → 0–30, 31–60, 61–90, 90+; works for any ascending list). No due date → "Due date unavailable". Only bills with outstanding ≠ 0.

### P11.4 Advances and on-account (AGE-BILL-3, 4)
ADVANCE totals as "Unadjusted Advances" and ON_ACCOUNT as "On-Account / Unallocated", per party and in total, separately for receivable and payable sides, never netted across sides, never in buckets. They reduce the party's net exposure figure, which is shown separately from the bucket total.

### P11.5 Ledgers without bill-wise details (SRS 10.3)
Debtor/creditor ledgers with `is_bill_wise = false`, or with no bill allocations at all → one line with the ledger balance (ACC-9.4) and the note "bill details not available". Never placed into guessed buckets.

### P11.6 Aging API
`GET /companies/{id}/analytics/aging?side=receivable|payable&as_of=` → bucket summary, per-party breakdown, advances, on-account, no-bill-details list, and drill-down: party → bills → allocations → vouchers (uses the same bill query).

### P11.7 Payment behaviour — `app/analytics/aging/payment_behaviour.py` (FR-PAY-1–6)
- Settlements = each Against Reference allocation (part settlements separately, FR-PAY-2) whose settlement date (its voucher date) falls within the trailing `payment.window_days` from today. Advance and On Account excluded (FR-PAY-4).
- Average days to pay = Σ(settled amount × (settlement date − bill date)) ÷ Σ settled amount (FR-PAY-1).
- Average days past due = same weighting with `max(0, settlement date − due date)`; settlements of bills without a due date are excluded from this figure and counted in a note (FR-PAY-3).
- Fewer than `payment.min_settlements` → "insufficient history" (FR-PAY-5).
- Until G25 PASSED, the endpoint returns `{available: false, reason: "Awaiting Tally validation (G25)"}` and the UI hides the section (FR-PAY-6).
- `GET /companies/{id}/analytics/payment-behaviour`.

### P11.8 Tests
- AC-45: ₹20,000 outstanding, due 45 days ago → 31–60 bucket.
- AC-46: due in 5 days → Not yet due, never negative. AC-47: no due date → Due date unavailable.
- AC-48: customer Advance → Unadjusted Advances, no bucket. AC-49: On Account → On-Account / Unallocated. AC-50: equal customer and supplier advances appear on their sides, not netted.
- AC-51: ₹10,000 bill dated 1 June; ₹6,000 settled 11 June, ₹4,000 on 21 June → average days to pay = 14 (with G25 forced PASSED).
- Boundaries: due today (0 days → 0–30), 30, 31, 60, 61, 90, 91 days; custom boundaries [15, 45]; part settlements; opening bills; unmatched settlements; UNSUPPORTED excluded; payment behaviour hidden with G25 NOT_TESTED.

## Definition of done
Tests pass; `docs/metrics.md` extended with aging and payment-behaviour rules.

## Kickoff prompt
~~~text
Read CLAUDE.md, docs/plan/phase-11-aging-payment.md, docs/metrics.md, docs/decisions.md (D-004, D-022) and SRS Section 10. In plan mode, propose the bill query (SQL), the bucket function and the payment-behaviour computation, with the AC-45–51 test list. Wait for approval, implement P11.1–P11.8 with tests first, commit per task, update docs/progress.md.
~~~
