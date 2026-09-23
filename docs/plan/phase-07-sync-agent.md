# Phase 7 — Tally Sync Agent (Windows)

**Size:** L (split: P7.1–P7.4, P7.5–P7.7, P7.8–P7.10) · **Depends on:** P3, P4, P5, P6
**SRS:** 4 (all), 3.2, 16 (Agent and Tally rows), 21 (Agent rows)
**Requirements:** AGT-1.1, 1.7, AGT-2.1–2.6, AGT-3.1–3.4, AGT-4.1–4.4, AGT-5.1–5.5, AGT-6.1–6.4, VER-1.1, FR-1.4, SEC-2.0
**Acceptance:** AC-21, AC-23, AC-24, AC-25, plus end-to-end AC-01, AC-02, AC-04 · **Decisions:** D-005, D-013, D-026, D-027

## Goal
A Windows service that registers once, heartbeats and polls, runs sync commands against TallyPrime with the project TDL, survives Tally being closed and the internet dropping without losing data, and reports its own and Tally's health.

## Tasks

### P7.1 Package structure and configuration
- Modules: `config.py`, `credentials.py`, `cli.py`, `backend_client.py`, `tally_client.py`, `tally_process.py`, `preflight.py`, `executor.py`, `queue.py`, `service.py`, `logging_setup.py`.
- Config: `%ProgramData%\TallyAgent\agent.toml` (backend URL, Tally host/port default `localhost:9000`, company name, poll interval, batch size, process name) — values from the backend's heartbeat response override local ones where the backend owns them.
- Credentials stored encrypted with Windows DPAPI (`win32crypt`); on Linux (tests) a file restricted to the current user.
- Rotating file logs under `%ProgramData%\TallyAgent\logs`.

### P7.2 CLI (typer)
`register --token --name`, `run` (foreground), `status`, `set-credential` (for rotation, SRS 4.4 step 4), `test-tally` (connectivity, TDL version, company GUID). Registration follows SRS 4.2 steps 4–9: test Tally → read company name/GUID via `TallyAnalyticsInfo` → `POST /agent/register` → store credential.

### P7.3 Tally client and error mapping
- httpx POST of `tally_contract` requests to `http://host:port`; response streamed to the parser.
- Error mapping: connection refused and the Tally process running → `TALLY_SERVER_DISABLED`; process not running → `TALLY_UNREACHABLE` ("Tally not running — the Windows user may have logged off", SRS 16); unknown report → `TDL_NOT_LOADED` (never fall back to default reports, FR-1.4); company not loaded → `COMPANY_NOT_LOADED`.
- Timeout (default 10 min): abandon, log `TALLY_EXPORT_TIMEOUT`, retry once with half the window/batch; a second timeout fails that segment and the run becomes PARTIAL (AGT-4.3).
- `tally_process.py`: find the TallyPrime process with psutil (process name configurable), report uptime (AGT-6.3).

### P7.4 Preflight before every sync (AGT-3.2, AGT-5.x, VER-1.1)
TDL version check → `TallyAnalyticsInfo` for the **named** company (never the active one, AGT-5.1) → GUID must equal the registered GUID. Mismatch → `COMPANY_MISMATCH`: halt, pull nothing, upload nothing, report in heartbeat and command result (AGT-3.3). Not loaded or renamed → `COMPANY_NOT_LOADED` (AGT-5.3, 5.4).

### P7.5 Main loop and command execution
- Heartbeat every `poll_interval` (±10 % jitter) with the AGT-1.1 payload; `tally_status` from the last Tally interaction.
- On a command: claim → create run (P5.1) → preflight → collections in dependency order: COMPANY, GROUP, VOUCHER_TYPE, LEDGER (+ opening balances, opening bills), COST_CENTRE, STOCK_ITEM (+ opening), VOUCHER, stock snapshot as of today in company TZ, key lists when due → finish run → result.
- Per collection: acquire lease (SYNC_LOCKED → skip, note it, continue) → plan mode and watermark → pull in ALTERID windows of `extraction_batch_size` (D-013; full pull starts at 0) → parse → enqueue batches sorted by ALTERID (D-026) → release lease.
- Progress heartbeats at least every lease/3 to extend the command lease (AGT-1.7).
- DATE_RANGE and RECONCILIATION modes: request by date window; reconciliation payloads are built in P10.
- Backend replies: 401 `CREDENTIAL_INVALID` → pause, log "enter the new credential with `tally-agent set-credential`"; `AGENT_REVOKED` → stop permanently; INCOMPATIBLE → keep heartbeating, run nothing.

### P7.6 Local queue — `queue.py` (AGT-2.x)
- SQLite (WAL) table `batches(id, batch_id, command_id, run_id, collection, seq, payload (compressed), record_count, created_at, attempts, next_attempt_at, last_error)`.
- Limits: 50,000 records or oldest batch 7 days (configurable) → QUEUE_FULL: stop pulling, keep uploading, report (AGT-2.2, 2.4).
- Backoff: 30 s doubling to 15 min, with jitter (AGT-2.3). After 20 failed attempts → append to `deadletter.jsonl` and report the count; never drop silently (AGT-2.5).
- Queue and dead-letter files restricted to the service account (AGT-2.6), set by the installer with `icacls`.
- Uploader runs independently of commands; if a command's lease was lost mid-run, queued batches still upload later under D-027 and stale protection.

### P7.7 Status reporting
Uptime, queue status, dead-letter count, Tally status, versions, and the last error per collection in each heartbeat.

### P7.8 Mock Tally server — `agent/tests/mock_tally/`
Small HTTP server that answers requests from fixture XML by report name and static variables. Modes: down; server disabled (connection refused with "process running" injected); TDL missing; company not loaded; slow (exceeds timeout); GUID mismatch; two companies loaded with the other one active; data edits between runs (to simulate modify/cancel/delete). The process table is injectable for tests.

### P7.9 Windows service
Service wrapper (pywin32 `ServiceFramework`; NSSM script as the alternative — the choice is an IMPLEMENTATION TEST, record the result as a D-entry). PyInstaller one-folder build script. `docs/agent-install.md`: prerequisites, TDL loading, running Tally in a logged-in session, Remote Desktop users must **disconnect, not log off** (AGT-6.1, 6.2). The full installer comes in P16.

### P7.10 Tests
- AC-21: queue at limit → pulling stops, uploads continue, QUEUE_FULL reported.
- AC-23: two companies loaded, other active → pulls only the registered one; registered company closed → COMPANY_NOT_LOADED, nothing pulled.
- AC-24: slow response → one retry at half size, `TALLY_EXPORT_TIMEOUT` logged.
- AC-25 (agent side): uptime reported; backend flags the advisory above threshold.
- COMPANY_MISMATCH → zero requests to the upload endpoint; TALLY_SERVER_DISABLED vs TALLY_UNREACHABLE mapping; backoff schedule; dead-letter after 20 failures.
- End-to-end (CI, Linux): Postgres + backend + mock Tally + Agent: register → FULL sync → DB counts equal fixture counts, rerun adds nothing (AC-01) → edit a fixture voucher → INCREMENTAL → updated and audited (AC-02) → remove a voucher from the key list → MISSING_IN_TALLY (AC-04) → kill the backend mid-upload → queue holds → restart → drains with no duplicates.

## Definition of done
All tests pass on Linux CI; the Windows CI job runs the unit tests; a manual run on a Windows machine with TallyPrime completes `tally-agent test-tally` (this also feeds the gate track).

## Kickoff prompt
~~~text
Read CLAUDE.md, docs/plan/phase-07-sync-agent.md, docs/agent-protocol.md, docs/sync-engine.md, docs/decisions.md (D-005, D-013, D-026, D-027) and SRS Section 4 and the Agent/Tally rows of Section 16. In plan mode, propose the module design, the main loop as a state diagram, the queue schema and the mock Tally server. Implement P7.1–P7.4 this session, P7.5–P7.7 next, P7.8–P7.10 after that. Tests first, commit per task, update docs/progress.md each time.
~~~
