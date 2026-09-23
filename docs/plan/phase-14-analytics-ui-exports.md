# Phase 14 — Analytics UI, drill-down & exports

**Size:** L (split: P14.1–P14.5, then P14.6–P14.9) · **Depends on:** P9, P10, P11, P12, P13
**SRS:** 13 (all), 8.11, 8.12, 17.4, 15 (export auditing)
**Requirements:** FR-4.1–4.3, FR-DD-1–5, EXP-1.1–1.6, ACC-4.4, ACC-VAL-1, TOPN-1.3, DR-UDF-2, NFR-UI-1–3, SEC-1.11, LOG-1.1
**Acceptance:** AC-39, AC-61, AC-65 (analytics pages) · **Decisions:** D-020

## Goal
The owner-facing dashboard: every summary figure can be drilled down to the vouchers behind it, and every view exports to CSV/PDF with figures identical to the screen.

## Tasks

### P14.1 Drill-down API (FR-DD-1–5)
- `GET /companies/{id}/analytics/{metric}/drilldown?level=&key=&page=` built on the metric's `detail_query`. Each page returns `rows`, `page`, `total_rows`, and `total_amount` computed over the full filtered set, equal to the figure being expanded (FR-DD-5).
- Paths: Revenue → customer → vouchers → voucher detail (FR-DD-1); Product revenue → product → contributing line items (FR-DD-2); Expense category → ledger → vouchers (FR-DD-3); Product Attribution Difference (or Unattributed / Non-product) → contributing vouchers (FR-DD-4); aging party → bills → allocations → vouchers.
- `GET /companies/{id}/vouchers/{voucher_id}`: header, status, ledger entries (ledger, direction, amount), line items, bill allocations, cost-centre allocations, custom fields (DR-UDF-2), link to its audit history.

### P14.2 Home dashboard (FR-4.1)
Cards: sales for the selected period, cash and bank position, receivables, payables, last sync time and status, reconciliation status. Period selector with FY and quarter presets. Every card links to its section.

### P14.3 Section pages (FR-4.2) and filters (FR-4.3)
Sales, Purchases, Cash Flow, Balances, Aging, Payment Behaviour (hidden until G25), Customers, Products, Expenses, Stock, Reconciliation, Data Quality, Anomalies (only when enabled, built in P15), Settings. A global filter bar — date range, customer, product, cost centre — stored in the URL query string so drill-downs, back navigation and shared links keep the same filters.

### P14.4 Charts (NFR-UI-2)
Recharts in responsive containers; tap shows the tooltip (no hover-only information); legends usable by touch; colour is never the only carrier of meaning; tapping a bar or point drills down.

### P14.5 Required labels and states
"Top N" + "View All" (TOPN-1.3); exactly one of "Product Attribution Difference" / "Unattributed / Non-product Sales Revenue" (ACC-VAL-1); "opening balance unavailable"; "bill details not available"; "insufficient history"; stock snapshot date and unit limitation banner; "Full sync only" badges; cash-flow note on voucher types counted (D-021); Unclassified Adjustments view.

### P14.6 CSV export — `app/exports/csv.py`
Header block: report title, company name, date range, active filters, generation timestamp in `company_timezone` (EXP-1.1). Summary lines — for sales: Total Sales Revenue, Product-attributed Revenue, and whichever difference label is active, as separate lines (EXP-1.4). Detail rows from the same metric functions (EXP-1.3), including mapped custom-field columns (EXP-1.5). UTF-8 with BOM so Excel opens it correctly.

### P14.7 PDF export — `app/exports/pdf.py`
HTML template rendered with WeasyPrint; charts rendered server-side as SVG with matplotlib from the same series data shown on screen (EXP-1.2); Indian number formatting; header/footer with company, range, generated time, page numbers. Add WeasyPrint's system libraries to the backend Dockerfile.

### P14.8 Export endpoint
`GET /companies/{id}/exports/{report}?format=csv|pdf&…filters` — re-checks permission (EXPORT) and company scope on the server (EXP-1.6, SEC-1.11), audits the export with its data range (LOG-1.1), streams large CSVs.

### P14.9 Tests
- AC-39: for the same filters, dashboard API figure = drill-down `total_amount` = parsed CSV summary = text extracted from the PDF.
- Property test: random filter combinations → drill-down total equals summary for every metric (FR-DD-5).
- AC-61: a mapped custom voucher field appears in voucher detail, drill-down and export, and no analytics total changes.
- Export by a user without company access → 403; export audited.
- Playwright: each section at 360 px has no page-level horizontal scroll; filters and drill-downs work with touch (AC-65 for analytics pages).

## Definition of done
All sections render real data from `make up` with the synthetic dataset; AC-39 and AC-61 pass; exports open correctly in Excel and a PDF viewer.

## Kickoff prompt
~~~text
Read CLAUDE.md, docs/plan/phase-14-analytics-ui-exports.md, docs/metrics.md and SRS Section 13. In plan mode, propose the drill-down API shapes for every path, the page list, and the export pipeline (CSV and PDF). Implement P14.1–P14.5 this session and P14.6–P14.9 in the next. Tests first where practical, commit per task, update docs/progress.md.
~~~
