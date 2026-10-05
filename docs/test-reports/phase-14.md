# Phase 14 test report

Generated 2026-10-04 15:59 UTC by `make phase-report PHASE=14`, on a freshly created and migrated `_test` database.

**Result: PASS**

| | |
|---|---|
| Tests run | 1744 |
| Passed | 1741 |
| Failed | 0 |
| Skipped | 3 |
| Coverage (lines) | 90.8% |
| `make check` (lint, types, imports) | PASS |
| Log | `logs/test-runs/p14-20261004T155405Z.log` |

## Skipped tests

| Test | Reason |
|---|---|
| agent.tests.test_secret_store::test_on_windows_the_data_directory_is_restricted_and_a_widened_one_is_refused | DPAPI and ACLs exist only on Windows |
| agent.tests.test_secret_store::test_on_windows_the_secret_is_dpapi_encrypted_in_machine_scope | DPAPI and ACLs exist only on Windows |
| agent.tests.test_winservice::test_stopping_the_service_asks_the_agent_loop_to_finish | a Windows service |

## Acceptance criteria covered

AC-01, AC-02, AC-04, AC-05, AC-06, AC-07, AC-08, AC-09, AC-10, AC-11, AC-12, AC-13, AC-14, AC-15, AC-16, AC-18, AC-20, AC-21, AC-22, AC-23, AC-26, AC-27, AC-28, AC-29, AC-30, AC-31, AC-32, AC-33, AC-35, AC-36, AC-37, AC-38, AC-39, AC-40, AC-41, AC-42, AC-43, AC-44, AC-45, AC-46, AC-47, AC-48, AC-49, AC-50, AC-51, AC-52, AC-53, AC-54, AC-59, AC-60, AC-61, AC-62, AC-63, AC-66

## Other requirement IDs covered

ACC-1.1, ACC-1.10, ACC-1.2, ACC-1.4, ACC-1.8, ACC-1.9, ACC-2.1, ACC-3.1, ACC-4.4, ACC-4.5, ACC-5.1, ACC-5.2, ACC-5.3, ACC-5.4, ACC-5.5, ACC-6.1, ACC-6.2, ACC-6.3, ACC-6.4, ACC-7.2, ACC-7.5, ACC-9.2, ACC-9.3, ACC-9.4, ACC-9.6, ACC-DATA-1, ACC-DATA-2, ACC-VAL-1, AGE-BILL-1, AGE-BILL-2, AGE-BILL-3, AGE-BILL-4, AGT-1.10, AGT-1.2, AGT-1.3, AGT-1.4, AGT-1.5, AGT-1.7, AGT-1.8, AGT-1.9, AGT-2.1, AGT-2.2, AGT-2.3, AGT-2.4, AGT-2.5, AGT-3.1, AGT-3.2, AGT-3.3, AGT-3.4, AGT-4.2, AGT-4.3, AGT-5.1, AGT-5.3, AGT-5.4, AGT-6.3, AGT-6.4, D-053, DR-4.4, DR-4.6, DR-ML-1, DR-ML-2, DR-ML-3, DR-ML-4, DR-UDF-1, DR-UDF-4, DR-VE-3, DR-VE-4, EXP-1.1, EXP-1.2, EXP-1.3, EXP-1.4, EXP-1.5, EXP-1.6, FR-1.4, FR-2.4, FR-4.3, FR-AGE-1, FR-AGE-2, FR-DD-1, FR-DD-2, FR-DD-3, FR-DD-4, FR-DD-5, FR-PAY-1, FR-PAY-3, FR-PAY-4, FR-PAY-5, FR-PAY-6, FR-STK-1, FR-STK-10, FR-STK-12, FR-STK-13, FR-STK-14, FR-STK-16, FR-STK-17, FR-STK-19, FR-STK-2, FR-STK-20, FR-STK-3, FR-STK-4, FR-STK-5, FR-STK-6, LOG-1.1, Q-1.2, RBAC-1.1, RBAC-1.2, REC-1.2, REC-1.3, REC-1.4, REC-1.5, RTE-1.1, RTE-1.2, RTE-1.3, RTE-1.4, RTE-1.5, RTE-1.6, SEC-1.1, SEC-1.11, SEC-1.2, SEC-1.4, SEC-1.5, SEC-1.9, SEC-2.0, SEC-2.0a, SEC-2.0b, SEC-2.1, SEC-2.2, SEC-2.3, SYNC-1.1, SYNC-1.2, SYNC-3.1, SYNC-3.2, SYNC-3.3, SYNC-3.4, SYNC-3.5, SYNC-4.1, SYNC-4.2, SYNC-4.3, SYNC-4.4, SYNC-5.2, SYNC-6.1, SYNC-6.2, SYNC-6.3, SYNC-6.4, SYNC-6.6, TEST-1.2, TEST-1.3, TEST-1.4, TEST-3.1, TEST-3.2, TEST-3.3, TOPN-1.1, TOPN-1.2, TOPN-1.3, TOPN-1.4, VAL-1.2, VER-1.1, VER-1.2

## Partially covered (not counted as covered)

AC-03, AC-17, AC-19, AC-24, AC-25, AC-34, ACC-1.5, ACC-1.6, ACC-1.7, ACC-2.2, ACC-3.3, ACC-3.4, ACC-7.3, ACC-7.4, ACC-7.6, ACC-8.2, ACC-8.3, ACC-9.1, ACC-9.5, AGE-BILL-5, AGT-1.1, AGT-1.6, AGT-2.6, DR-4.1, DR-4.2, DR-UDF-2, DR-UDF-3, FR-1.1, FR-1.2, FR-1.3, FR-2.1, FR-4.1, FR-4.4, FR-4.5, FR-PAY-2, FR-STK-15, FR-STK-7, LOG-1.2, NFR-REL-2, Q-1.1, REC-1.1, SEC-1.13, SEC-1.14, SEC-1.15, SEC-1.3, SYNC-1.3, SYNC-5.3, SYNC-5.4, SYNC-6.5, TEST-1.1, TEST-2.1, TEST-4.2, TZ-1.1, TZ-1.2, VAL-1.1

## Notes (added by hand)
- **The frontend is outside the pytest count above.** Its own suites run in `make check`'s neighbour CI job `frontend` and before every P14 commit:
  - Vitest: 141 tests in 17 files (`cd frontend && npm test`);
  - Playwright on a mocked API: 64 tests, 32 each in the `desktop` and `mobile` (360×740) projects (`npm run e2e`);
  - live check against `make up` (`npm run e2e:live`).
  Frontend tests carry no `req` tags, so the traceability lists above do not include the UI side.
- **UI side of this session's requirements:**
  - EXP-1.1 / AC-65 (exports): `analytics.spec.ts` "a section exports to CSV and to PDF, by touch, under the CSP" — a real attachment is downloaded at 360 px by tap and on desktop by click, with no page-level horizontal scroll and no CSP violation. The rest of AC-65 for the analytics pages was proven in session 1.
  - `exportLinks.test.tsx`: the view's own report and its filters go out with the signed-in user's token; PDF when PDF is pressed; three files on the Sales page (EXP-1.4); a 403 shown in the error catalogue's own wording rather than as a broken file; a drill-down exporting with its `by` narrowing.
- **AC-39 end to end** (`tests/api/test_exports.py`): for five metrics, the dashboard figure, the drill-down total, the CSV summary line and the text extracted from the PDF with `pdftotext` are one and the same number. **ACC-4.4 is proved in full**, not merely as agreement: the dashboard, the drill-down, the CSV and the PDF are each shown to take their figure from `app.analytics.query.total`.
- **Live check, the phase's definition of done.** Against `make up` + `make demo-data`, every one of the 20 reports was exported as CSV and PDF — 40 files — with the figures reconciling: Total Sales Revenue 27,01,875.00 − Product-attributed 26,95,475.00 = the difference 6,400.00. The CSVs open in Numbers/Excel and their amount columns add to their summary lines; the PDFs open in a viewer, with the charts, the page footers and only the bundled faces embedded.
- **D-053 #7a's measurement:** a 2,000-row PDF renders in **3.1 s** (median of 3) using about **234 MB** of RSS on the dev Mac (Apple M4, 16 GB), producing a 209 KB file. An earlier 16 s reading was `tracemalloc`'s own overhead, not the render; the test deliberately measures without it.
- **Three defects found and fixed in this session**, each with a regression test:
  - `GET /analytics/aging` returned 500 for any company with no bills on that side — GROUPING SETS emits one row per set even over empty input, and `SUM()` of no rows is NULL. Fixed in the SQL, so the API, the export and any later caller are fixed together. A new company's Aging page would have hit this.
  - A sales export narrowed by one of its own `group_by` keys passed that `by` to Product-attributed Revenue, which has no `ledger` option and refused it with a 422. Found by the FR-DD-5 property test.
  - The PDF's running header and footer are page margin boxes, which inherit from the page context rather than from `body`, so they were set in whatever serif the machine offered — DejaVu Serif on the dev Mac, nothing at all in the Docker image. `@page` now names the bundled stack, and a test asserts only faces from `app/exports/fonts/` are ever embedded.
  - Also: `StreamingResponse` sends its headers before asking for a chunk, so a reversed date range arrived after a 200 had gone out. The handler now pulls the first chunk itself, keeping such refusals ordinary 422s.
- **Still partial, deliberately:**
  - `DR-UDF-2` — this phase proves "shown in drill-down and export"; the sync side that writes `custom_fields` is proven in P5's tests.
  - `FR-4.1`, `FR-4.4`, `FR-4.5`, `TZ-1.1`, `TZ-1.2` and the other entries above are partial for the reasons their test comments give; none is a gap opened by this session.
- **Gate-dependent, unchanged:** Payment Behaviour exports its reason rather than figures until G25 passes (FR-PAY-6), and the stock export carries its unverified gates (G18, G27) as notes.
