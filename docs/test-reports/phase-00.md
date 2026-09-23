# Phase 00 test report

Generated 2026-09-23 15:26 UTC by `make phase-report PHASE=00`, on a freshly created and migrated `_test` database.

**Result: PASS**

| | |
|---|---|
| Tests run | 78 |
| Passed | 78 |
| Failed | 0 |
| Skipped | 0 |
| Coverage (lines) | 81.8% |
| `make check` (lint, types, imports) | PASS |
| Log | `logs/test-runs/p00-20260923T152638Z.log` |

## Skipped tests

_none_

## Acceptance criteria covered

AC-12

## Other requirement IDs covered

SEC-1.14, SEC-1.15, TEST-1.3, VAL-1.1, VAL-1.2

## Correction (2026-09-23)

The requirement lists above were generated before `req` / `req_partial` were separated and
overclaim: several IDs are only partly proven or were tagged on tests that do not prove them
(e.g. AC-12, TEST-1.3, ACC-DATA-1, SEC-1.7). The re-audited coverage is in
[`docs/traceability.md`](../traceability.md); test counts and results above are unaffected.
