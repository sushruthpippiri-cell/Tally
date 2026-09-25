# Phase 02 test report

Generated 2026-09-25 06:31 UTC by `make phase-report PHASE=02`, on a freshly created and migrated `_test` database.

**Result: PASS**

| | |
|---|---|
| Tests run | 416 |
| Passed | 415 |
| Failed | 0 |
| Skipped | 1 |
| Coverage (lines) | 90.2% |
| `make check` (lint, types, imports) | PASS |
| Log | `logs/test-runs/p02-20260925T063116Z.log` |

## Skipped tests

| Test | Reason |
|---|---|
| backend.tests.api.test_route_access::test_agent_routes_reject_user_tokens[none] | no Agent-credential routes until P3 |

## Acceptance criteria covered

AC-59, AC-60

## Other requirement IDs covered

DR-4.6, DR-ML-1, Q-1.2, RBAC-1.1, RBAC-1.2, RTE-1.4, SEC-1.1, SEC-1.2, SEC-1.4, SEC-1.9

## Partially covered (not counted as covered)

AC-12, AC-62, AC-63, ACC-7.3, DR-4.1, DR-4.2, DR-4.4, LOG-1.1, LOG-1.2, Q-1.1, SEC-1.13, SEC-1.14, SEC-1.15, SEC-1.3, TZ-1.1, TZ-1.2, VAL-1.1, VAL-1.2
