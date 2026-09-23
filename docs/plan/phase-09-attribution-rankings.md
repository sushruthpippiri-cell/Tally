# Phase 9 — Customer & product attribution, Top-N rankings

**Size:** M · **Depends on:** P8
**SRS:** 8.5, 8.6, 8.11, 8.12, 8.13
**Requirements:** ACC-6.1–6.4, ACC-1.4, ACC-1.8–1.10, ACC-VAL-1, TOPN-1.1–1.4, FR-2.4
**Acceptance:** AC-30, AC-31, AC-32, AC-33 · **Gates:** G27 (quantities), G28 (label) · **Decisions:** D-019

## Goal
Honest attribution: revenue is assigned to a customer or product only when the data proves it, the remainder is shown under the correct label, and rankings never pretend to add up to totals.

## Tasks

### P9.1 Customer attribution — `metrics/customer_revenue.py` (ACC-6.1–6.4)
- For each qualifying SALES voucher, count distinct customer ledgers (Sundry Debtors class) among its entries: exactly one → that customer; zero (cash sale) or more than one → Unattributed Customer Revenue. Never split by guesswork (ACC-6.3).
- Detail rows = the Total Sales detail rows (P8.4) joined with the voucher's `customer_id` or NULL. Linked returns follow D-019.
- Because the rows are identical, Σ customer-attributed + unattributed = Total Sales Revenue for the same period and filters (ACC-6.4) holds by construction — and is still tested.

### P9.2 Supplier equivalents (ACC-1.4)
Same pattern with Purchase Value and Sundry Creditors.

### P9.3 Product attribution — `metrics/product_revenue.py` (ACC-1.8–1.10, ACC-VAL-1)
- Product-attributed Revenue = Σ `voucher_items.amount` on vouchers qualifying under ACC-1.1, minus linked-return items (D-019).
- Difference = Total Sales Revenue − Product-attributed Revenue. `difference_label` = "Product Attribution Difference" unless gate G28 is PASSED, then "Unattributed / Non-product Sales Revenue". The API returns exactly one label field; there is no code path that returns both (ACC-VAL-1).
- Difference drill-down (FR-DD-4, built in P14) = per voucher: voucher sales total − voucher item total, non-zero rows only.

### P9.4 Top-N — `app/analytics/ranking.py` (TOPN-1.x)
`rank(detail_query, dimension, n)` returns rows, `n`, `total_count`, `is_top_n`. "View All" calls the same function without the limit (TOPN-1.2). N defaults to `analytics.top_n_default` and can be overridden by `top_n` (1–100). Responses never include a "Top N total as share of total" figure unless explicitly labelled as such (TOPN-1.4).

### P9.5 Customer and product endpoints (FR-2.4)
- `GET /analytics/customers`: ranked by customer-attributed revenue; the Unattributed line is shown separately, never ranked among customers.
- `GET /analytics/suppliers`.
- `GET /analytics/products`: ranked by product-attributed revenue and, with `rank_by=quantity`, by quantity sold. Quantities use base-unit conversion when G27 passed; otherwise raw quantities with each item's multi-unit flag (hook for P12).

### P9.6 Tests
- AC-30: single-customer Sales voucher ₹50,000 → ₹50,000 to that customer.
- AC-31: cash sale → Unattributed; attributed + unattributed = Total Sales.
- AC-32: ₹92,000 stock lines + ₹8,000 service line, G28 not passed → Total ₹100,000, Product ₹92,000, ₹8,000 shown as Product Attribution Difference (not as service revenue).
- AC-33: N = 10 and 25 customers → Top view 10, no claim of summing to total, View All → 25.
- Two-customer voucher → unattributed. Exactly-one-label test with G28 NOT_TESTED and PASSED.
- Property test (hypothesis): random mixes of 0/1/2-customer vouchers and returns → ACC-6.4 identity always holds.

## Definition of done
All tests pass; `docs/metrics.md` extended with attribution rules and label logic.

## Kickoff prompt
~~~text
Read CLAUDE.md, docs/plan/phase-09-attribution-rankings.md, docs/metrics.md, docs/decisions.md (D-019) and SRS Sections 8.5, 8.6, 8.11–8.13. In plan mode, show how each metric reuses the Total Sales detail rows and how the difference label is chosen. Wait for approval, implement P9.1–P9.6 with tests first, commit per task, update docs/progress.md.
~~~
