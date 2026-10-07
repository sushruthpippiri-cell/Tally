# Phase 16 test report

Generated 2026-10-07 12:35 UTC by `make phase-report PHASE=16`, on a freshly created and migrated `_test` database.

**Result: the suite PASSES. The phase is NOT complete.**

> "PASS" above is the test suite, not Phase 16. Ten tasks are finished, part of an eleventh is,
> and the rest wait on things only the owner can supply. The list is below, and in
> `docs/progress.md`'s Blocked table. Nothing here should be read as "Phase 16 done".

| | |
|---|---|
| Tests run | 1924 |
| Passed | 1921 |
| Failed | 0 |
| Skipped | 3 |
| Coverage (lines) | 90.9% |
| `make check` (lint, types, imports) | PASS |
| Log | `logs/test-runs/p16-20261007T122835Z.log` |

## Skipped tests

| Test | Reason |
|---|---|
| agent.tests.test_secret_store::test_on_windows_the_data_directory_is_restricted_and_a_widened_one_is_refused | DPAPI and ACLs exist only on Windows |
| agent.tests.test_secret_store::test_on_windows_the_secret_is_dpapi_encrypted_in_machine_scope | DPAPI and ACLs exist only on Windows |
| agent.tests.test_winservice::test_stopping_the_service_asks_the_agent_loop_to_finish | a Windows service |

## Acceptance criteria covered

AC-01, AC-02, AC-03, AC-04, AC-05, AC-06, AC-07, AC-08, AC-09, AC-10, AC-11, AC-12, AC-13, AC-14, AC-15, AC-16, AC-18, AC-20, AC-21, AC-22, AC-23, AC-26, AC-27, AC-28, AC-29, AC-30, AC-31, AC-32, AC-33, AC-35, AC-36, AC-37, AC-38, AC-39, AC-40, AC-41, AC-42, AC-43, AC-44, AC-45, AC-46, AC-47, AC-48, AC-49, AC-50, AC-51, AC-52, AC-53, AC-54, AC-55, AC-56, AC-57, AC-58, AC-59, AC-60, AC-61, AC-62, AC-63, AC-66

## Other requirement IDs covered

ACC-1.1, ACC-1.10, ACC-1.2, ACC-1.4, ACC-1.8, ACC-1.9, ACC-2.1, ACC-3.1, ACC-4.4, ACC-4.5, ACC-4.6, ACC-5.1, ACC-5.2, ACC-5.3, ACC-5.4, ACC-5.5, ACC-6.1, ACC-6.2, ACC-6.3, ACC-6.4, ACC-7.2, ACC-7.5, ACC-9.2, ACC-9.3, ACC-9.4, ACC-9.6, ACC-DATA-1, ACC-DATA-2, ACC-VAL-1, AGE-BILL-1, AGE-BILL-2, AGE-BILL-3, AGE-BILL-4, AGT-1.10, AGT-1.2, AGT-1.3, AGT-1.4, AGT-1.5, AGT-1.7, AGT-1.8, AGT-1.9, AGT-2.1, AGT-2.2, AGT-2.3, AGT-2.4, AGT-2.5, AGT-2.6, AGT-3.1, AGT-3.2, AGT-3.3, AGT-3.4, AGT-4.1, AGT-4.2, AGT-4.3, AGT-5.1, AGT-5.3, AGT-5.4, AGT-6.3, AGT-6.4, BKP-1.2, D-015, D-053, D-055, DR-4.4, DR-4.6, DR-ML-1, DR-ML-2, DR-ML-3, DR-ML-4, DR-UDF-1, DR-UDF-4, DR-VE-3, DR-VE-4, EXP-1.1, EXP-1.2, EXP-1.3, EXP-1.4, EXP-1.5, EXP-1.6, FR-1.4, FR-2.4, FR-3.1, FR-3.2, FR-3.3, FR-3.4, FR-3.5, FR-3.6, FR-3.8, FR-3.9, FR-4.3, FR-AGE-1, FR-AGE-2, FR-DD-1, FR-DD-2, FR-DD-3, FR-DD-4, FR-DD-5, FR-PAY-1, FR-PAY-3, FR-PAY-4, FR-PAY-5, FR-PAY-6, FR-STK-1, FR-STK-10, FR-STK-12, FR-STK-13, FR-STK-14, FR-STK-16, FR-STK-17, FR-STK-19, FR-STK-2, FR-STK-20, FR-STK-3, FR-STK-4, FR-STK-5, FR-STK-6, LOG-1.1, LOG-1.2, NFR-MAINT-2, NFR-SCALE-1, PERF-1.4, Q-1.2, RBAC-1.1, RBAC-1.2, REC-1.2, REC-1.3, REC-1.4, REC-1.5, RTE-1.1, RTE-1.2, RTE-1.3, RTE-1.4, RTE-1.5, RTE-1.6, SEC-1.1, SEC-1.10, SEC-1.11, SEC-1.12, SEC-1.13, SEC-1.14, SEC-1.2, SEC-1.3, SEC-1.4, SEC-1.5, SEC-1.6, SEC-1.7, SEC-1.8, SEC-1.9, SEC-2.0, SEC-2.0a, SEC-2.0b, SEC-2.1, SEC-2.2, SEC-2.3, SRS-19.3, SYNC-1.1, SYNC-1.2, SYNC-3.1, SYNC-3.2, SYNC-3.3, SYNC-3.4, SYNC-3.5, SYNC-4.1, SYNC-4.2, SYNC-4.3, SYNC-4.4, SYNC-5.2, SYNC-6.1, SYNC-6.2, SYNC-6.3, SYNC-6.4, SYNC-6.6, TEST-1.2, TEST-1.3, TEST-1.4, TEST-3.1, TEST-3.2, TEST-3.3, TOPN-1.1, TOPN-1.2, TOPN-1.3, TOPN-1.4, VAL-1.2, VER-1.1, VER-1.2

## Partially covered (not counted as covered)

AC-17, AC-19, AC-24, AC-25, AC-34, ACC-1.5, ACC-1.6, ACC-1.7, ACC-2.2, ACC-3.3, ACC-3.4, ACC-7.3, ACC-7.4, ACC-7.6, ACC-8.2, ACC-8.3, ACC-9.1, ACC-9.5, AGE-BILL-5, AGT-1.1, AGT-1.6, DR-4.1, DR-4.2, DR-UDF-2, DR-UDF-3, FR-1.1, FR-1.2, FR-1.3, FR-2.1, FR-4.1, FR-4.4, FR-4.5, FR-PAY-2, FR-STK-15, FR-STK-7, NFR-REL-2, Q-1.1, REC-1.1, SEC-1.15, SYNC-1.3, SYNC-5.3, SYNC-5.4, SYNC-6.5, TEST-1.1, TEST-2.1, TEST-4.2, TZ-1.1, TZ-1.2, VAL-1.1

## Notes (added by hand)

### Phase 16 is not complete

**Done:** P16.1, P16.2, P16.3, P16.4, P16.6 (code and docs), P16.7, P16.8 (code and docs),
P16.9, P16.11, P16.12 (code and docs).

**Part done:** P16.5 — the Locust concurrency harness and `docs/benchmarks/TEMPLATE.md` are in;
`tools/dataset_gen`, the mock-Tally sync benchmark (PERF-1.2/1.3) and the EXPLAIN ANALYZE review
are not. The database half of dataset_gen is nearly free, since `benchmark.generate()` is already
pure over a `Sink`; the mock-Tally XML half is net-new, and the mock holds every row's XML in
memory and re-joins the whole list per request, so 100,000 vouchers needs work on the mock too.

**Not started, by instruction:** P16.10 (the acceptance run), P16.8a (code signing), P16.8b (the
Agent on real x64 hardware).

**Blocked on the owner**, with what each waits for in `docs/progress.md`: the real-Tally
benchmark and PERF-VAL-1 evidence (the x64 PC); the restore drill (hosting and staging); code
signing (an EV certificate in an HSM or token); P16.12's three live checks (hosting, a domain,
TLS); the acceptance run and six still-PROPOSED decisions (the capture kit — all 37 gates are
NOT_TESTED); the Agent Windows checklist (the VM); and the accountant's review of
`reconciliation-basis.md`.

### Frontend suites, outside the count above

- Vitest: 152 tests in 18 files (`cd frontend && npm test`)
- Playwright on a mocked API: 66 tests in 4 files, across the `desktop` and `mobile` (360×740)
  projects
- `make loadtest` against the local backend: 60 dashboard opens, 0 failures, p95 **49 ms**
  against a 3,000 ms budget — see `docs/benchmarks/p16-concurrency.md`, which states twice that
  this is **not** PERF-1.1 evidence because it ran on the demo dataset, not the SRS 17.2 one.

### Six defects found and fixed, each with a regression test

1. **`pyjwt` 2.14.0 carried PYSEC-2026-4141 / CVE-2026-102275** — in the token-signing path.
   Upgraded to 2.15.1. Found by the `pip-audit` step P16.2 added; it had never been run.
2. **The XML parser expanded internal entities.** External entities never resolved, so there was
   no file-disclosure path, but a billion-laughs document from Tally would have exhausted the
   Agent before a single record was built. A DTD is now refused outright — Tally's reports carry
   none — which closes the class without taking on `defusedxml`.
3. **A database outage returned 500, not SRS 16's 503**, on every route but `/health/db`. Needed
   separate handling in the middleware too, because the rate limiter now touches the database
   outside the exception handlers.
4. **The gitleaks allowlist excused a whole directory.** gitleaks ORs a path and a regex, so the
   path alone was suppressing every finding in `docs/benchmarks/`. Now ANDed and matched on the
   line, and proven narrow by planting a credential-shaped line in that same file: 25 plan lines
   stayed suppressed and the planted one was reported.
5. **Three audited actions were written but unclassified** — `USER_ATTACHED`,
   `GROUP_RESOLUTION_CHANGED`, `VOUCHER_TYPE_RESOLUTION_CHANGED`. The last two are passed
   positionally, which a source scan missed and the new runtime guard caught immediately.
6. **`/health` was rate-limited.** The limiter runs before auth, so a load balancer polling
   faster than the anonymous limit was answered 429 and would have taken the backend out of
   service. Latent since P2; found by moving the counters.

### Two test-infrastructure hazards the Postgres counters exposed

Nothing reached `app.core.db`'s process-wide cached engine from tests before P16.11, because
`get_session` is always overridden. The limiter counts on its own session, so a
`TestClient(create_app())` test was handing the next test asyncpg connections from a closed event
loop. Each test's limiter now gets a loop-local engine, and an autouse fixture disposes the
cached engine after every test.

### Traceability

328 requirement ids (down from 356: the regex was taking "FR-1" out of the SRS's own "FR-1.x"
group references, so 28 section headings were being reported as uncovered). 237 covered by a
test, 11 verified by hand, 30 accounted for but **not yet verified**, 50 partially covered, **0
unaccounted for**. `make traceability` is now a blocking gate and also fails on a stale committed
`docs/traceability.md`, which previously passed CI silently.

`docs/manual-verification.md` is honest about four different things, and one of them is for the
owner: **NFR-UI-3** ("a non-technical owner can read the dashboard without training") cannot be
assessed by the people who built it. Two more are our own work, not the owner's: ACC-7.1 and
ACC-8.1 want a source guard nobody has written.

### Known gaps carried forward

- The anomaly review buttons are exercised on the Playwright desktop project only (P15).
- The Inno Setup installer has **not been compiled**: `agent-build` is manual-dispatch only
  because Windows minutes cost twice as much (D-038 #7). Trigger it once to confirm.
- ACC-7.1 / ACC-8.1 have behavioural tests but no structural guard.
