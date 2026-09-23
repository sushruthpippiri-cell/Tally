# Phase 3 — Agent control plane (backend)

**Size:** L (split: P3.1–P3.6, then P3.7–P3.12) · **Depends on:** P2
**SRS:** 4.2–4.9, 4.13, 5.4, 19.2 (agent rows)
**Requirements:** SEC-2.0–2.4, AGT-1.1–1.10, AGT-3.1, AGT-3.4, RTE-1.1–1.6, VER-1.1–1.2, AGT-4.2, AGT-5.4, AGT-6.4
**Acceptance:** AC-13, 14, 15, 16, 17 (API), 18, 19, 20, 22, 24 (setting part) · **Decisions:** D-006, D-011, D-012, D-017, D-023, D-025

## Goal
Everything the backend needs to onboard Agents, authenticate them, hand them commands through polling, and recover from lost Agents — without ever opening a connection to one.

## Tasks

### P3.1 Credential utilities — `app/core/agent_credentials.py` (D-011)
- Generate `agt_<agent_id>.<secret>`; store salted SHA-256 hash and salt; verify with `hmac.compare_digest`.
- Registration tokens: 32 random bytes, stored as SHA-256 hash, 24 h expiry, single use.

### P3.2 Registration token endpoint
`POST /companies/{id}/agents/register-token` (MANAGE_AGENTS) → token returned once with `expires_at`. Audited.

### P3.3 Agent registration — `POST /agent/register`
Body: `token, agent_name, tally_guid, tally_company_name, agent_version, tdl_version, tally_version?, tally_host?, tally_port?`. One transaction implementing SRS 4.2 steps 6–8:
- Token valid, unused, unexpired → else 401.
- Company has no `tally_guid` → set it (first Agent). Otherwise the reported GUID must match or → 409 `COMPANY_MISMATCH`, token stays unused (AC-14).
- Duplicate `agent_name` in the company → 409.
- Create agent (status REGISTERING), credential, mark token used, mark company active, create default schedules per D-023.
- Response: `agent_id`, credential (only time it is shown), config (poll interval, extraction batch size, Tally host/port/company name, expected TDL version, per-collection sync mode from `gates.py`). Audited.

### P3.4 Agent authentication — `AgentContext` dependency
Parses the bearer credential; unknown/wrong secret → 401 `CREDENTIAL_INVALID`; revoked → 401 `AGENT_REVOKED` (SEC-2.2, AC-15). Provides `agent_id` and `company_id` for scoping. User JWTs are rejected on agent routes and vice versa.

### P3.5 Heartbeat and polling — `POST /agent/heartbeat` (AGT-1.1, VER-1.1)
- Payload: versions, `tally_uptime_seconds`, `queue_status {records, oldest_age_seconds, dead_letter_count, full}`, `tally_status` (OK | TALLY_UNREACHABLE | TALLY_SERVER_DISABLED | TDL_NOT_LOADED | COMPANY_NOT_LOADED | COMPANY_MISMATCH), `confirmed_tally_guid`.
- Update `last_heartbeat_at` and reported fields; update `last_tally_status`/`tally_status_since` on change (D-025).
- Version below `MIN_AGENT_VERSION` or `MIN_TDL_VERSION` (compare with `packaging.version`) → INCOMPATIBLE, no command returned (VER-1.2, AC-22). Back above minimum → ACTIVE.
- REGISTERING → ACTIVE when `confirmed_tally_guid` equals the stored GUID. OFFLINE → ACTIVE on any heartbeat.
- COMPANY_MISMATCH reported → keep the Agent's status, surface a warning; never re-bind (AGT-3.4).
- Response: status, current config, and the oldest PENDING command for this Agent (if any).

### P3.6 Offline detection job
APScheduler every 60 s under an advisory lock (D-017): ACTIVE Agents with no heartbeat for `agent.offline_threshold_minutes` → OFFLINE.

### P3.7 Command creation (AGT-1.5, RTE-1.x)
- `POST /companies/{id}/agents/{agent_id}/sync` and `POST /companies/{id}/sync` (optional `agent_id`; D-006). Body: `sync_mode` (FULL | INCREMENTAL | DATE_RANGE | RECONCILIATION), `date_from`, `date_to` (required for DATE_RANGE). Permission RUN_SYNC.
- Routing: exactly one ACTIVE Agent → auto-target (RTE-1.1); more than one and no `agent_id` → 422 `AGENT_SELECTION_REQUIRED` (RTE-1.2, AC-18); Agent not in this company → 403 (RTE-1.5); REVOKED/INCOMPATIBLE → 409 (D-012).
- Creates PENDING; never contacts the Agent. For an OFFLINE Agent the response carries `waiting_label: "Waiting — Agent offline since <local time>"` (RTE-1.6, AC-19). Audited.

### P3.8 Claim, progress, result
- `POST /agent/commands/{id}/claim`: atomic compare-and-set (AGT-1.3):
  `UPDATE agent_commands SET status='CLAIMED', claimed_at=now(), lease_expires_at=now()+:lease WHERE command_id=:id AND agent_id=:caller AND status='PENDING' RETURNING *` — no row → 409 `INVALID_COMMAND_STATE`.
- `POST /agent/commands/{id}/progress`: first call moves CLAIMED → RUNNING; every call extends `lease_expires_at` (AGT-1.7).
- `POST /agent/commands/{id}/result`: COMPLETED or FAILED with `error_code`, `error_message`.
- A transition table in `app/services/commands.py` rejects illegal transitions; only the owning Agent may act.

### P3.9 Expiry and lost-Agent job
Every 60 s under advisory lock: PENDING older than `agent.command_claim_timeout_minutes` → EXPIRED (AGT-1.10); CLAIMED/RUNNING past `lease_expires_at` → FAILED_AGENT_LOST with reason (AGT-1.8). Never reassigned, never retried (AGT-1.4, AGT-1.9). Leave a hook `on_command_lost(command)` that P5 uses to fail the sync run and release leases.

### P3.10 Schedules (RTE-1.3)
- `GET/POST/PUT /companies/{id}/sync-schedules` (MANAGE_SCHEDULES): `agent_id` fixed at creation, cron validated, `sync_mode`, `is_active`. Audited.
- Scheduler job evaluates cron expressions in `company_timezone` (TZ-1.1) and creates PENDING commands with `created_by = NULL` (system), under an advisory lock so replicas never double-fire (D-017).

### P3.11 Agent management
- `GET /companies/{id}/agents`: FR-4.4 fields plus derived `uptime_advisory` (uptime > `agent.tally_uptime_advisory_days`; AGT-6.4 emphasis added in P10) and `waiting_label`.
- `POST …/{agent_id}/rotate-credential`: new salt + hash replace the old in one transaction; returns the new credential once; same `agent_id` (SEC-2.1, SEC-2.3, AC-16). Audited.
- `POST …/{agent_id}/revoke`: REVOKED, `revoked_at`, permanent. Audited.
- `PUT …/{agent_id}/tally-settings`: host, port, company name (AGT-5.4), `extraction_batch_size` 1–10,000 (15,000 → 422, AGT-4.2, AC-24). Audited; delivered to the Agent via the next heartbeat.

### P3.12 Tests
- AC-13 registration issues a credential bound to one company; AC-14 GUID mismatch; AC-15 revoked → AGENT_REVOKED, no commands; AC-16 rotation (old → 401 CREDENTIAL_INVALID immediately, new works).
- AC-17 (API): PENDING → CLAIMED → RUNNING → COMPLETED, each visible via command status.
- AC-18 routing with 1 and 2 Agents; AC-19 offline Agent → PENDING with label, claimed on return; expiry after 10 min (time-machine).
- AC-20 / TEST-3.2: RUNNING command past lease → FAILED_AGENT_LOST, never reassigned.
- AC-22 version check; AC-24 batch size 15,000 rejected.
- Concurrency: 10 simultaneous claims of one command (separate sessions, `asyncio.gather`) → exactly one succeeds (AGT-1.3).
- Tenant: Agent of company A cannot claim a company B command; user of A cannot create a command for B's Agent.

## Definition of done
All listed ACs pass at API level; the OpenAPI spec documents every agent endpoint; `docs/agent-protocol.md` describes the heartbeat/command sequence (with a Mermaid sequence diagram) for the P7 session to follow.

## Kickoff prompt
~~~text
Read CLAUDE.md, docs/plan/phase-03-agent-control-plane.md, docs/decisions.md (D-006, D-011, D-012, D-017, D-023, D-025) and SRS Sections 4.2–4.9, 4.13, 19.2. In plan mode, propose the endpoint schemas, the command state machine, and the SQL for the atomic claim. Implement P3.1–P3.6 first; stop, update docs/progress.md, and wait for me before P3.7–P3.12. Tests first, commit per task.
~~~
