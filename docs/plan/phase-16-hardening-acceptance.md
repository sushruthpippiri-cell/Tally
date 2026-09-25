# Phase 16 — Hardening, performance, backup, end-to-end & acceptance

**Size:** L (split into three sessions: P16.1–P16.4 + P16.11, P16.5–P16.7, P16.8–P16.10) · **Depends on:** all earlier phases
**SRS:** 14.2, 15, 16, 17, 20, 22, 23, 24, 25, 28
**Requirements:** SEC-1.1–1.15, LOG-1.1–1.2, PERF-1.1–1.4, PERF-VAL-1–2, NFR-REL-1–2, NFR-SCALE-1, NFR-UI-1–3, BKP-1.1–1.6, TEST-5.1–5.2
**Acceptance:** AC-59, AC-60 (exhaustive), AC-64, AC-65, and the full AC-01 to AC-66 run · **Decisions:** D-028

## Goal
Turn a feature-complete system into one that is verifiably secure, fast enough, recoverable, and traceable requirement-by-requirement — ready for the production gates in SRS Section 28.

## Tasks

### P16.1 Endpoint security sweep (automated)
Introspect FastAPI's route table and generate tests for every route:
- company-scoped routes: a user of another company → 403 with no data (AC-60, exhaustive);
- every route × role against the SRS 14.1 matrix (AC-59, exhaustive);
- unauthenticated → 401; agent routes reject user JWTs and user routes reject Agent credentials.
New routes added later fail CI until they declare their permission.

### P16.2 Security review — `docs/security-review.md`
Evidence for SEC-1.1 to SEC-1.15: TLS termination config (Caddy or nginx) in `deploy/` with HSTS and HTTP→HTTPS; CORS; rate limits tested; CSRF rationale; parameterized queries (grep for string-built SQL); Pydantic on every body; secrets only from env/secret store; app DB role has no DDL; audit append-only; anomaly data minimization. Add `pip-audit`, `npm audit`, and `bandit` to CI. Revisit D-028 (token storage).

### P16.3 Logging and retention (SRS 15)
Structured JSON logs with request ID, company ID, Agent ID. Retention jobs: `sync_runs`/`sync_errors` and `ai_tool_log` purged after a configurable age (default 180 days, minimum 90); system logs 30 days (log-service configuration documented); `audit_logs` never purged while the company's data exists. Verify every LOG-1.1 action writes an audit row (table-driven test).

### P16.4 Failure-mode matrix — `docs/failure-modes.md`
One row per SRS Section 16 condition: detection, behaviour, user message, recovery, and the test ID that proves it. Write the missing tests (e.g. database unavailable → 503 with no partial writes; backend unavailable → Agent queues).

### P16.5 Performance (SRS 17.1, 17.2, PERF-VAL-1)
- `tools/dataset_gen`: deterministic, seeded generator for the benchmark dataset (100,000 vouchers, 500,000 entries, 5,000 ledgers, 10,000 stock items), output both as a database seed and as mock-Tally XML; the dataset identifier is its seed + version.
- Load test (Locust): 10 concurrent users; dashboard summary ≤ 3 s (PERF-1.1).
- Sync benchmark: mock Tally → Agent → backend for a full sync (≤ 30 min, PERF-1.2) and an incremental of ~500 changed records (≤ 2 min, PERF-1.3); anomaly evidence call ≤ 2 s (PERF-1.4).
- `EXPLAIN ANALYZE` review of the top queries; add indexes or materialized views only if needed, keeping one definition per metric (ACC-4.4).
- `docs/benchmarks/TEMPLATE.md` capturing every PERF-VAL-1 field. The real-Tally benchmark is run by you on the benchmark machine using this template.

### P16.6 Backup and recovery (SRS 22)
`deploy/backup/`: daily full backup + continuous WAL archiving with ≥ 30-day retention (pgBackRest, or the managed provider's PITR — document which) (BKP-1.1); alert on a failed backup (BKP-1.3); `scripts/restore_drill.sh` restores to staging and compares row counts and a reconciliation snapshot (BKP-1.2); runbook `docs/runbooks/restore.md` including BKP-1.5/1.6 notes; RPO/RTO recorded as proposed values (BKP-1.4, D-016).

### P16.7 End-to-end suite (SRS 20, TEST-5.1)
Playwright + mock Tally + real Agent process where feasible, covering UC-1 to UC-14, on desktop and the 360 px touch project (AC-65). Includes RBAC 403 flows, drill-down totals and export/screen consistency.

### P16.8 Agent distribution
PyInstaller build on `windows-latest` in CI; Inno Setup installer that installs to Program Files, creates `%ProgramData%\TallyAgent` with ACLs for the service account (AGT-2.6), registers the Windows service, and runs a first-time wizard (backend URL, Tally host/port, company name, registration token). Upgrade preserves config, credential and queue; uninstall leaves the queue for inspection. Update `docs/agent-install.md`.

### P16.9 Traceability (SRS 25)
Finalize `tools/traceability.py`: every requirement ID in the SRS maps to at least one test or to an entry in `docs/manual-verification.md` with reason and evidence. Make the CI job blocking.

### P16.10 Acceptance run (SRS 24, 28)
Script that runs the AC-tagged tests and writes `docs/acceptance-report.md`: AC-01 to AC-66 with PASS/FAIL, and "blocked by Gxx" where live-Tally evidence is still missing. Update the readiness summary in the SRS Section 28 format (ready / validation required / implementation test required / business decision required).

### P16.11 Rate limits shared across replicas — REQUIRED before production (SEC-1.9, D-033 #3)
The SEC-1.9 limits (100/min per IP unauthenticated, 1,000/min per user) are counted in each backend process's memory (`RateLimiter` in `app/core/middleware.py`), so N replicas allow N× the limit. Move the counters to shared storage (a Postgres table with an atomic `INSERT … ON CONFLICT … DO UPDATE … RETURNING count`, or Redis if one is deployed by then), keeping the key rules (user id for a valid access token, else the client IP resolved through `TRUSTED_PROXIES`) and the 429 + `Retry-After` response. Test: two app instances sharing the store together allow no more than the limit. Close the ceiling in `docs/security-review.md`. **Production must not run more than one backend replica until this is done.** (The per-email login throttle already counts from `audit_logs` and is unaffected.)

## Definition of done
Rate limits enforced across replicas (P16.11); security sweep, failure-mode tests, E2E suite and traceability all blocking and green in CI; benchmark template filled for the synthetic run; restore drill executed once; acceptance report generated.

## Kickoff prompt
~~~text
Read CLAUDE.md, docs/plan/phase-16-hardening-acceptance.md, docs/progress.md and SRS Sections 14.2, 15, 16, 17, 22–25, 28. In plan mode, propose the three sessions' scope. Implement P16.1–P16.4 and P16.11 this session; P16.5–P16.7 next; P16.8–P16.10 last. Commit per task and update docs/progress.md each session.
~~~
