# Phase 08 test report

Generated 2026-09-28 15:27 UTC by `make phase-report PHASE=08`, on a freshly created and migrated `_test` database.

**Result: PASS**

| | |
|---|---|
| Tests run | 1204 |
| Passed | 1201 |
| Failed | 0 |
| Skipped | 3 |
| Coverage (lines) | 89.5% |
| `make check` (lint, types, imports) | PASS |
| Log | `logs/test-runs/p08-20260928T152439Z.log` |

## Skipped tests

| Test | Reason |
|---|---|
| agent.tests.test_secret_store::test_on_windows_the_data_directory_is_restricted_and_a_widened_one_is_refused | DPAPI and ACLs exist only on Windows |
| agent.tests.test_secret_store::test_on_windows_the_secret_is_dpapi_encrypted_in_machine_scope | DPAPI and ACLs exist only on Windows |
| agent.tests.test_winservice::test_stopping_the_service_asks_the_agent_loop_to_finish | a Windows service |

## Acceptance criteria covered

AC-01, AC-02, AC-04, AC-05, AC-06, AC-07, AC-08, AC-09, AC-11, AC-12, AC-13, AC-14, AC-15, AC-16, AC-18, AC-20, AC-21, AC-22, AC-23, AC-26, AC-27, AC-28, AC-29, AC-35, AC-36, AC-37, AC-59, AC-60, AC-62, AC-63, AC-66

## Other requirement IDs covered

ACC-1.1, ACC-1.2, ACC-2.1, ACC-3.1, ACC-4.5, ACC-5.1, ACC-5.2, ACC-5.3, ACC-5.4, ACC-5.5, ACC-7.2, ACC-7.5, ACC-9.2, ACC-9.3, ACC-9.4, ACC-9.6, ACC-DATA-1, ACC-DATA-2, AGT-1.10, AGT-1.2, AGT-1.3, AGT-1.4, AGT-1.5, AGT-1.7, AGT-1.8, AGT-1.9, AGT-2.1, AGT-2.2, AGT-2.3, AGT-2.4, AGT-2.5, AGT-3.1, AGT-3.2, AGT-3.3, AGT-3.4, AGT-4.2, AGT-4.3, AGT-5.1, AGT-5.3, AGT-5.4, AGT-6.3, DR-4.4, DR-4.6, DR-ML-1, DR-ML-2, DR-ML-3, DR-ML-4, DR-UDF-1, DR-UDF-4, DR-VE-3, DR-VE-4, FR-1.4, Q-1.2, RBAC-1.1, RBAC-1.2, RTE-1.1, RTE-1.2, RTE-1.3, RTE-1.4, RTE-1.5, RTE-1.6, SEC-1.1, SEC-1.2, SEC-1.4, SEC-1.9, SEC-2.0, SEC-2.0a, SEC-2.0b, SEC-2.1, SEC-2.2, SEC-2.3, SYNC-1.1, SYNC-1.2, SYNC-3.1, SYNC-3.2, SYNC-3.3, SYNC-3.4, SYNC-3.5, SYNC-4.1, SYNC-4.2, SYNC-4.3, SYNC-4.4, SYNC-5.2, SYNC-6.1, SYNC-6.2, SYNC-6.3, SYNC-6.4, SYNC-6.6, TEST-1.2, TEST-1.3, TEST-1.4, TEST-3.1, TEST-3.2, TEST-3.3, VAL-1.2, VER-1.1, VER-1.2

## Partially covered (not counted as covered)

AC-03, AC-10, AC-17, AC-19, AC-24, AC-25, AC-34, AC-38, ACC-1.5, ACC-1.6, ACC-1.7, ACC-2.2, ACC-3.3, ACC-3.4, ACC-4.4, ACC-7.3, ACC-7.4, ACC-7.6, ACC-8.2, ACC-8.3, ACC-9.1, AGT-1.1, AGT-1.6, AGT-2.6, AGT-6.4, DR-4.1, DR-4.2, DR-UDF-2, DR-UDF-3, FR-1.1, FR-1.2, FR-1.3, FR-2.1, FR-4.4, FR-4.5, FR-DD-5, FR-STK-15, LOG-1.1, LOG-1.2, NFR-REL-2, Q-1.1, SEC-1.13, SEC-1.14, SEC-1.15, SEC-1.3, SYNC-1.3, SYNC-5.4, SYNC-6.5, TEST-1.1, TZ-1.1, TZ-1.2, VAL-1.1

## Notes (added by hand)
- **Superseded as worded, by owner decisions.** ACC-1.5 (expenses: net movement, D-044 #5); ACC-1.6, 1.7, 3.3, 3.4 (cash flow: every Cash/Bank movement netted per voucher, journals on by default, D-021); ACC-9.1 (balances roll forward from books-beginning, D-039 #5). Tests prove the owner's rules and tag these IDs as partial with a "superseded" comment (D-045 #4).
- **Partial for later phases.**
  - AC-34 is split: the parse half is proven in `shared/`, the analytics half here.
  - ACC-4.4: exports, P14.
  - FR-DD-5: later phases' metrics.
  - AC-38: matching Tally within tolerance, P10.
  - ACC-7.4: listed in Data Quality, P6.
- **Coverage** is 89.5% (P7: 90.5%). `tally_tools/benchmark.py` and `bench_analytics.py` run only against `tally_bench`, never in CI; the generator itself is tested.
