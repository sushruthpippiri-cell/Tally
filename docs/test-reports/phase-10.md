# Phase 10 test report

Generated 2026-09-29 06:59 UTC by `make phase-report PHASE=10`, on a freshly created and migrated `_test` database.

**Result: PASS**

| | |
|---|---|
| Tests run | 1327 |
| Passed | 1324 |
| Failed | 0 |
| Skipped | 3 |
| Coverage (lines) | 89.9% |
| `make check` (lint, types, imports) | PASS |
| Log | `logs/test-runs/p10-20260929T065603Z.log` |

## Skipped tests

| Test | Reason |
|---|---|
| agent.tests.test_secret_store::test_on_windows_the_data_directory_is_restricted_and_a_widened_one_is_refused | DPAPI and ACLs exist only on Windows |
| agent.tests.test_secret_store::test_on_windows_the_secret_is_dpapi_encrypted_in_machine_scope | DPAPI and ACLs exist only on Windows |
| agent.tests.test_winservice::test_stopping_the_service_asks_the_agent_loop_to_finish | a Windows service |

## Acceptance criteria covered

AC-01, AC-02, AC-04, AC-05, AC-06, AC-07, AC-08, AC-09, AC-10, AC-11, AC-12, AC-13, AC-14, AC-15, AC-16, AC-18, AC-20, AC-21, AC-22, AC-23, AC-26, AC-27, AC-28, AC-29, AC-30, AC-31, AC-32, AC-33, AC-35, AC-36, AC-37, AC-38, AC-40, AC-41, AC-42, AC-43, AC-44, AC-59, AC-60, AC-62, AC-63, AC-66

## Other requirement IDs covered

ACC-1.1, ACC-1.10, ACC-1.2, ACC-1.4, ACC-1.8, ACC-1.9, ACC-2.1, ACC-3.1, ACC-4.5, ACC-5.1, ACC-5.2, ACC-5.3, ACC-5.4, ACC-5.5, ACC-6.1, ACC-6.2, ACC-6.3, ACC-6.4, ACC-7.2, ACC-7.5, ACC-9.2, ACC-9.3, ACC-9.4, ACC-9.6, ACC-DATA-1, ACC-DATA-2, ACC-VAL-1, AGT-1.10, AGT-1.2, AGT-1.3, AGT-1.4, AGT-1.5, AGT-1.7, AGT-1.8, AGT-1.9, AGT-2.1, AGT-2.2, AGT-2.3, AGT-2.4, AGT-2.5, AGT-3.1, AGT-3.2, AGT-3.3, AGT-3.4, AGT-4.2, AGT-4.3, AGT-5.1, AGT-5.3, AGT-5.4, AGT-6.3, AGT-6.4, DR-4.4, DR-4.6, DR-ML-1, DR-ML-2, DR-ML-3, DR-ML-4, DR-UDF-1, DR-UDF-4, DR-VE-3, DR-VE-4, FR-1.4, FR-2.4, Q-1.2, RBAC-1.1, RBAC-1.2, REC-1.2, REC-1.3, REC-1.4, REC-1.5, RTE-1.1, RTE-1.2, RTE-1.3, RTE-1.4, RTE-1.5, RTE-1.6, SEC-1.1, SEC-1.2, SEC-1.4, SEC-1.9, SEC-2.0, SEC-2.0a, SEC-2.0b, SEC-2.1, SEC-2.2, SEC-2.3, SYNC-1.1, SYNC-1.2, SYNC-3.1, SYNC-3.2, SYNC-3.3, SYNC-3.4, SYNC-3.5, SYNC-4.1, SYNC-4.2, SYNC-4.3, SYNC-4.4, SYNC-5.2, SYNC-6.1, SYNC-6.2, SYNC-6.3, SYNC-6.4, SYNC-6.6, TEST-1.2, TEST-1.3, TEST-1.4, TEST-3.1, TEST-3.2, TEST-3.3, TOPN-1.1, TOPN-1.2, TOPN-1.4, VAL-1.2, VER-1.1, VER-1.2

## Partially covered (not counted as covered)

AC-03, AC-17, AC-19, AC-24, AC-25, AC-34, ACC-1.5, ACC-1.6, ACC-1.7, ACC-2.2, ACC-3.3, ACC-3.4, ACC-4.4, ACC-7.3, ACC-7.4, ACC-7.6, ACC-8.2, ACC-8.3, ACC-9.1, ACC-9.5, AGT-1.1, AGT-1.6, AGT-2.6, DR-4.1, DR-4.2, DR-UDF-2, DR-UDF-3, FR-1.1, FR-1.2, FR-1.3, FR-2.1, FR-4.1, FR-4.4, FR-4.5, FR-DD-5, FR-STK-10, FR-STK-15, LOG-1.1, LOG-1.2, NFR-REL-2, Q-1.1, REC-1.1, SEC-1.13, SEC-1.14, SEC-1.15, SEC-1.3, SYNC-1.3, SYNC-5.3, SYNC-5.4, SYNC-6.5, TEST-1.1, TEST-2.1, TEST-4.2, TOPN-1.3, TZ-1.1, TZ-1.2, VAL-1.1

## Notes (added by hand)
- **Phase 10 IDs still partial, and where they finish.**
  - REC-1.1, ACC-9.5, TEST-4.2: the Tally side is our draft TDL (`TA_ReconTotals`, `TA_LedgerClosing`) until GATE-G36 and GATE-G19 pass on live captures; the synthetic half runs end to end (real Agent, real backend, mock Tally) and every ledger is compared. The live half joins with the G-E captures.
  - FR-4.1: the reconciliation status is on `sync/status`; the home view itself is P13.
  - TEST-2.1: the reconciliation examples are covered (all six SRS 9.3 rows); the ACC rules were P8/P9.
  - SYNC-5.3: the reconciliation lists every collection over explicit dates and checks totals; the daily schedule is D-023 (P3).
- **Owner changes in D-048**, each tested:
  - #2 every voucher request names its dates (books-from to 2099-12-31); a post-dated voucher syncs in the run after it is created (`test_a_post_dated_voucher_syncs_in_the_run_after_it_is_created`), whatever period Tally has selected.
  - #3 stock is compared with the snapshot the same run stored, moments apart.
  - #5 the shared-filter case: a voucher the voucher Collection wrongly drops fails LEDGER_BALANCE while SALES_CREDITS passes (`test_a_voucher_the_shared_filter_wrongly_drops_fails_ledger_balance_only`).
- **One path to MISSING_IN_TALLY**: an architecture test allows `lifecycle.MISSING` only in `app/sync/keylists.py`; reconciliation key lists go through the D-007 guard (tested empty and short).
- **New gates** G36 (reconciliation totals) and G37 (explicit voucher dates, post-dated vouchers), NOT TESTED; the capture kit gains `recon_totals`, dated `voucher_keys` and scenario G37.
