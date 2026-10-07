# Manual verification

Requirements that cannot be proved by a test in this repository, with how each **is** verified —
or what it is waiting for. Created in P16.9, where `make traceability CHECK=1` became a CI gate:
every SRS requirement must have a `req` test, a `req_partial` test, or a row here. A requirement
with none of the three fails the build, which is the point — a new requirement cannot arrive
untracked.

**A row here is not a pass.** The last column is what it waits for; `-` means it has been
verified and the "How" column says how. `docs/traceability.md` lists the two groups separately,
and the acceptance run (P16.10) is where the blocked ones are reported as outstanding.

Four honest categories, and it is worth being clear which is which:

1. **Proved by a test this tool does not scan.** `tools/tally_tools/traceability.py` reads
   `@pytest.mark.req` from the Python suites only; the Playwright and Vitest suites carry no such
   markers. These requirements *are* tested — the row names the spec and the test title. Teaching
   the scanner to read the TypeScript suites would turn these into ordinary covered rows, and is
   the obvious next improvement.
2. **Structural, and true by construction.** Enforced by the repository's layout, by
   import-linter, or by a guard already in the suite under a different id.
3. **Needs a measurement.** A benchmark run, with its numbers recorded.
4. **Needs the owner.** Live TallyPrime, a real x64 PC, hosting, or an accountant. These are the
   rows in `docs/progress.md`'s Blocked table.

| ID | Why it cannot be a test | How it is verified | Blocked on |
|---|---|---|---|
| FR-3.7 | A layout requirement: evidence and explanation in separate, clearly labelled areas | `frontend/e2e/pages.spec.ts` "the Anomalies section separates evidence from the explanation" and `src/pages/anomalies.test.tsx`, which assert two `aria-label`led regions | - |
| FR-4.2 | The list of dashboard sections is a property of the built app's routes | `frontend/e2e/pages.spec.ts` walks all 20 `ROUTES` and asserts each renders its own `h1` | - |
| NFR-UI-1 | Page-level horizontal scrolling can only be observed in a browser | `frontend/e2e/pages.spec.ts` `expectNoHorizontalScroll` on every route, in the 360 px project, with deliberately long names and wide tables | - |
| NFR-UI-2 | Touch interaction needs a real event stream | `frontend/e2e/analytics.spec.ts` drives chart, filter, drill-down and export **by `tap()`** in the 360 px project, which Playwright configures with `hasTouch` | - |
| NFR-UI-3 | "A non-technical owner can read the dashboard without training" is a judgement, not an assertion | Reviewed against the wording rules in `docs/metrics.md` and the error catalogue in `frontend/src/lib/errorMessages.ts`. **Not independently verified**: it needs someone who has not seen the product | An owner or accountant to read the dashboard cold and say what was unclear |
| AC-65 | Same as NFR-UI-1/2 | `frontend/e2e/analytics.spec.ts` and `pages.spec.ts` in the `mobile` (360×740, touch) Playwright project. **Known gap:** the anomaly review buttons are exercised on the desktop project only — see `docs/test-reports/phase-15.md` | - |
| NFR-MAINT-1 | "Kept in separate, version-controlled modules" is a property of the repository layout | `tdl/` holds the TDL sources, `shared/tally_contract/` the field mappings and parser, `backend/app/anomaly/mcp_server.py` the one MCP tool; `pyproject.toml`'s import-linter contracts stop the layers merging, and `make importlint` runs in CI | - |
| NFR-REL-1 | "A failure in the optional module leaves the core product unaffected" is a statement about the whole system | Two mechanisms, each proved: import-linter forbids `app.analytics`/`reconciliation`/`sync`/`exports` from importing `app.anomaly` or the AI SDKs (a named contract, `make importlint` in CI), and `backend/tests/anomaly/test_explainer.py::test_claude_unreachable_leaves_the_anomaly_with_its_evidence` shows detection continuing when Claude is unreachable (AC-58) | - |
| ACC-7.1 | "Every rule that classifies a ledger uses the resolved predefined group" is a claim about all present and future rules | Behaviour proved in `backend/tests/analytics/test_classification.py` (resolution by GUID, another company's groups never counting) and `backend/tests/sync/test_hierarchy.py`. **Structurally unguarded**: nothing stops a future metric classifying by name. A source guard like `test_architecture.py`'s is the right fix and is not written | A source guard (our own work, not the owner's) |
| ACC-8.1 | As ACC-7.1, for `base_voucher_type` versus the voucher-type name | `backend/tests/sync/test_hierarchy.py::test_voucher_types_resolve_through_their_chain_to_a_base_type` and the metric tests. Same structural gap as ACC-7.1 | A source guard (our own work) |
| SEC-2.4 | "No HMAC request-signing scheme is used or claimed" — a requirement that something is *absent* | No signing code exists: the Agent authenticates with a bearer credential over TLS (`agent/tally_agent/backend_client.py`), and `backend/tests/core/test_agent_auth.py` shows that is the whole mechanism. A grep for `hmac` in `agent/` and `backend/app/` finds nothing | - |
| VAL-1.3 | "This table is a maintained project artifact, updated with evidence" is about upkeep, not behaviour | `docs/validation-gate.md` is the table and `backend/app/config/gate_status.yaml` is what the code reads; `app/core/gates.py` and its tests make a gate's status change behaviour. Upkeep is only demonstrable once there is evidence to record | The capture kit: all 37 gates are NOT_TESTED, so nothing has been recorded yet |
| PERF-1.1 | A measurement | The Locust run P16.5 adds: 10 concurrent users, dashboard summary ≤ 3 s | P16.5's benchmark run (our own work) |
| PERF-1.2 | A measurement | P16.5's sync benchmark through mock Tally: a full sync of the SRS 17.2 dataset ≤ 30 min | P16.5's benchmark run (our own work) |
| PERF-1.3 | A measurement | P16.5's incremental benchmark: ~500 changed records ≤ 2 min | P16.5's benchmark run (our own work) |
| PERF-VAL-1 | Every field it asks for describes a machine we do not have | `docs/benchmarks/TEMPLATE.md` (P16.5) lists each field; the owner fills it in on the benchmark machine | A real x64 PC running TallyPrime |
| PERF-VAL-2 | "Measured with the stated number of concurrent users" | The Locust run records its concurrency; the single-user figures in `docs/benchmarks/p8-analytics.md` state plainly that they are *not* PERF-VAL evidence | P16.5's benchmark run, then the real machine |
| AC-64 | The acceptance form of PERF-1.x under SRS 17.2 conditions | The performance suite's recorded output | The benchmark machine (P16.5 + the x64 PC) |
| TEST-5.2 | "Performance tests run under Section 17.2 conditions with full recording" | As AC-64 | The benchmark machine |
| TEST-5.1 | End-to-end coverage across RBAC, drill-down totals, export/screen consistency and 360 px layout — a statement about a suite, not one behaviour | P16.7's use-case suite and its coverage map, plus the existing `backend/tests/e2e/test_agent_end_to_end.py` and the Playwright projects | P16.7 (our own work) |
| BKP-1.1 | A provider's backup configuration | `docs/runbooks/restore.md` lists what must be true — daily full, continuous WAL, ≥ 30 days retention, same region, encrypted — and asks for each answer to be recorded | Hosting |
| BKP-1.3 | Whether an alert reaches a person | `docs/runbooks/restore.md` requires alerting on the **absence** of a recent successful backup, not only on a reported failure, and that the alert be tested once on purpose | Hosting and an alerting destination |
| BKP-1.4 | Recovery targets are met or not met by a real restore | D-056 #1 accepts RPO ≤ 24 h / RTO ≤ 4 h as the committed worst case; `restore_drill.sh` prints its own elapsed time so the achieved figures are recorded | Hosting and a staging environment |
| BKP-1.5 | "A fresh full sync recovers records that still exist in Tally" is a property of recovery, not of sync | The mechanism is proved — `backend/tests/e2e/test_agent_end_to_end.py` runs a real FULL sync that re-creates every record from Tally — and `docs/runbooks/restore.md` step 6 makes it part of the procedure. What is unverified is doing it after a real restore | The restore drill (hosting) |
| BKP-1.6 | "Agent queues are transient and not backed up" — again a requirement that something is absent, plus a recovery claim | Nothing backs up the queue: `deploy/backup/` touches only the database. `agent/tests/test_queue.py::test_nothing_is_ever_dropped_silently` and the full-sync test above show a lost queue is re-pulled from Tally | - |
| TEST-2.2 | "The validation gate is executed on a live TallyPrime installation and its evidence recorded" | `make capture-kit` produces the harness; `tools/capture_kit/CHECKLIST.md` is the procedure; evidence lands in `fixtures/xml/live/` and `docs/validation-gate.md` | The owner's Windows VM with TallyPrime |
| TEST-4.1 | "tally-database-loader is run against the project's Tally test company and its output kept" | A third-party tool against a real Tally company | The owner's Windows VM |
| AGT-5.2 | How Tally responds to a company named in a request | The name targets the request and the GUID check (AGT-3.2) confirms it; the GUID half is tested in `backend/tests/api/test_agent_registration.py`. The naming mechanism itself is gated | GATE-G12: the capture kit |
| AGT-5.5 | Marked **LIVE TALLY VERIFICATION REQUIRED** in the SRS | The gated constant and its safe default are in the TDL request builder, tagged `# GATE-`; `app/core/gates.py` switches behaviour when the gate passes | The capture kit |
| AGT-4.4 | "These defaults come from the reference implementation and are confirmed against live Tally" | The defaults are in `agent/tally_agent/config.py` and exercised at size by `agent/tests/test_streaming.py` (AGT-4.1); confirming them against live Tally is the gate | The capture kit |
| AGT-6.1 | TallyPrime must be running in a logged-in Windows session | The Agent's process check is `agent/tally_agent/tally_client.py` with `AGT-6.3` tested; that a *logged-off* session really behaves as described needs Windows | The owner's Windows VM (also SRS 16 row 2's message) |
| AGT-6.2 | Installation guidance, i.e. a document | `docs/agent-install.md` tells Remote Desktop users to disconnect rather than log off, under **Office networks**. Verified by reading it | - |
| VER-1.3 | "Certified TallyPrime releases are recorded in a compatibility table" | The table is `docs/validation-gate.md`'s environment section; it has nothing in it until a real TallyPrime has been tested | The owner's Windows VM |
| ACC-DATA-3 | Marked **LIVE TALLY VERIFICATION REQUIRED**: the exact XML indicator of debit/credit | The parser's indicator is one gated constant with a safe default (`shared/tally_contract/`, tagged `# GATE-`), and normalization is tested against synthetic fixtures | GATE-G01: the capture kit |
| SYNC-5.1 | What Tally returns for a key-only list | The backend half is fully tested (`backend/tests/sync/test_key_lists.py`) and the Agent sends the request (`agent/tests/test_agent_sync.py`); the response *shape* is gated | GATE-G33: the capture kit |
| SYNC-5.5 | "The reference implementation's deletion handling is reviewed before implementation" | A review, recorded in `docs/sync-engine.md` and D-041 | - |
| DR-VE-1 | "A live export is inspected to determine whether a stable per-line identifier exists" | An inspection of real Tally output | The capture kit (gate G31 territory) |
| DR-VE-2 | Conditional on DR-VE-1: if the identifier exists, lines are updated individually | Until DR-VE-1 is answered the safe path applies — children are replaced wholesale in one transaction (SRS 6.9), tested in `backend/tests/sync/test_ingest_vouchers.py` | DR-VE-1, so the capture kit |
| DR-ML-5 | "An INACTIVE state is recorded **if Tally exposes one**" | Gated on G29; the enum value exists and the sync path has a safe default of not using it | GATE-G29: the capture kit |
| FR-STK-8 | "A live export determines whether transaction units, base units and conversion factors are available" | Inspection of real Tally output | GATE-G27: the capture kit |
| FR-STK-9 | Conditional on FR-STK-8 | Quantities are left unconverted until G27 passes, and the stock export carries that as a note | GATE-G27 |

## What this list says about the project

Of the 41 rows, counted from `docs/traceability.md`:

- **11 are verified** and need nothing further: SEC-2.4, AGT-6.2, SYNC-5.5, FR-3.7, FR-4.2,
  NFR-REL-1, NFR-UI-1, NFR-UI-2, NFR-MAINT-1, BKP-1.6, AC-65.
- **11 wait on live Tally** — the capture kit or the Windows VM. The single largest dependency in
  the project, and the reason all 37 gates are NOT_TESTED.
- **7 wait on a benchmark run**, six of which are our own work (P16.5) and two of those then need
  the real x64 PC.
- **4 wait on hosting**, all backup requirements.
- **3 are our own work, not the owner's**: ACC-7.1 and ACC-8.1 want a source guard that is not
  written, and TEST-5.1 wants P16.7. Listed honestly rather than marked verified.
- **1 has no owner and no plan**: **NFR-UI-3** ("a non-technical owner can read the dashboard
  without training") cannot be self-assessed by the people who built it. It needs someone who has
  not seen the product to read the dashboard and say what was unclear. Flagged for the owner.

Five of the eleven verified rows are only *unscanned*, not untested — they are Playwright tests.
Teaching `traceability.py` to read `@req` annotations from the TypeScript suites would move them
into the ordinary covered list and shrink this file, and is the obvious next improvement.
