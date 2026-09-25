# Progress log

Claude Code updates this at the end of every session. Newest entries at the top of each section.

## Current phase
P3 (Agent control plane) — local suite PASS 2026-09-25 ([phase-03](test-reports/phase-03.md), 613 tests, 0 skipped); waiting on CI. Next: P4 (Tally contract) — not started; waits for the owner, and **D-002 must be confirmed before P4**.

P2 (identity, RBAC, settings) — **complete** 2026-09-25. Local suite PASS ([phase-02](test-reports/phase-02.md), 416 tests, 1 skipped with reason) and CI green (run 36103266538, both `check` and `agent-windows`). Next: P3 (Agent control plane) — not started; waits for the owner.

P1 (data model) — **complete** 2026-09-23. Local suite PASS ([phase-01](test-reports/phase-01.md), 183 tests, 0 skipped) and CI green (run 35887137380, both `check` and `agent-windows`). Next: P2 (identity, RBAC, settings) — not started; waits for the owner.

P0 — **complete** 2026-09-23. Local suite PASS ([phase-00](test-reports/phase-00.md), 78 tests) and CI green (run 35881605525, both `check` and `agent-windows`).

## Done
| Date | Phase.Task | Commit | Notes |
|---|---|---|---|
| 2026-09-25 | P3.7 commands + migration 0004 | b08caed | D-036 ACCEPTED. `created_at` from the app clock + `seq` identity: oldest = (created_at, seq); the P3.6 test workaround removed. Routing: one eligible Agent targeted even if OFFLINE/REGISTERING (waiting label); several need one ACTIVE or `agent_id`. |
| 2026-09-25 | P3.8 claim/progress/result | c86e7fd | Single conditional UPDATEs. Committed races: 10 claims → 1; claims blocked behind an uncommitted claim all lose; one Agent, two commands → 1 (unique index). Mutation-checked (naive claim; dropped index). |
| 2026-09-25 | P3.9 timeouts | 5be8794 | EXPIRED / FAILED_AGENT_LOST jobs; AGT-1.9 late calls → 409 with the row unchanged; on-time progress blocked behind the lost job loses (mutation-checked). `on_command_lost` hook for P5. |
| 2026-09-25 | P3.10 schedules | 8805249 | `next_fire_at`, cron in company TZ, missed runs coalesce; simultaneous firings INCREMENTAL first (tested in both insertion orders; removing the sort fails it). |
| 2026-09-25 | P3.11 Agent management | 27e63a5 | Agents view (+ `NO_ACTIVE_SCHEDULE`), rotation (committed races: one-instant switch, vs revocation, two rotations), revocation deactivates schedules, tally-settings (AC-24). Replacement path tested end to end. Phase 5 plan gains the required schedule-activation item. |
| 2026-09-25 | P3.12 docs | 2b31319 | `docs/agent-protocol.md` complete (states, sequence diagram); OpenAPI summary test for every Agent endpoint. Smoke test on the dev DB: register → heartbeat → Sync Now → claim/progress/result → COMPLETED. |
| 2026-09-25 | P3 tag review | (see log) | Downgraded to partial: AGT-1.1, VER-1.1 (the Agent's side: P7), AC-17, AC-19, AGT-1.6, FR-4.4 (dashboard: P13). |
| 2026-09-25 | P3.1 credentials + committing fixture | 7e43c09 | `agt_<id>.<secret>`, salted SHA-256; `reg_` tokens hashed. `committed` fixture: real commits on separate connections, TRUNCATE only on a `_test` database (D-035 #14). D-035 ACCEPTED. APScheduler added. |
| 2026-09-25 | P3.2 registration token | 7f4a380 | MANAGE_AGENTS, shown once, 24 h, audited. |
| 2026-09-25 | P3.3 registration | cb05398 | CAS on token and GUID binding in one transaction; mismatch leaves the token usable (AC-13, AC-14). Committed races: one token x8 → one Agent; two first Agents with different GUIDs → one binds. Mutation-checked against a naive read-then-write. |
| 2026-09-25 | P3.4 AgentContext | 2cab749 | CREDENTIAL_INVALID vs AGENT_REVOKED (SEC-2.2); a wrong secret never reveals revocation. |
| 2026-09-25 | P3.5 heartbeat | 3ea4b23 | Migration 0003 (`error_code`, partial unique index: one command in progress per Agent, D-035 #13). INCOMPATIBLE (AC-22), GUID confirmation, D-025, COMPANY_MISMATCH warning (AGT-3.4). Route test: P2 skip removed; Agent routes checked; user/company routes reject Agent credentials. `docs/agent-protocol.md` started (independent progress timer). |
| 2026-09-25 | P3.6 offline job | 03db83b | `mark_offline` per company threshold; `run_exclusive` advisory lock tested on real connections (D-017). **This commit went in with one failing test** (my check pipeline did not stop on failure); fixed in 74f5d17 — a heartbeat test tied on `created_at`. |
| 2026-09-25 | P2 follow-up | (see log) | D-034 ACCEPTED. Per-replica rate-limit ceiling added to the Phase 16 plan as required task P16.11 (before production). |
| 2026-09-25 | P2.7 audit service | 330c906 | `audit.record()` writes every LOG-1.2 field; `diff()`. D-033 ACCEPTED with the plan. |
| 2026-09-25 | P2.9 periods | 922b481 | TZ-safe day bounds, FY/quarter labels; AC-62 run under 3 server time zones. AC-62/AC-63 partial until analytics group by them (P8). |
| 2026-09-25 | P2.2 auth | ba670d2 | Migration 0002 (`refresh_tokens`, login index). Rotation; reuse revokes all sessions; per-email throttle from audit rows (D-033 #7). `RATE_LIMITED` code. |
| 2026-09-25 | P2.3/P2.4 permissions | e9bfb8c | SRS 14.1 matrix, `require()` (a `Require` object the route test can read), `CompanyContext`, `scoped()`. |
| 2026-09-25 | P2.5 companies + route access test | c5266d9 | `tests/api/test_route_access.py` enumerates every route (`fastapi.routing.iter_route_contexts`); verified it fails for a route without `require()`, a view permission on a write route, and an unlisted route. D-034 PROPOSED (FY start day 1-28). |
| 2026-09-25 | P2.6 users and roles | 580c28d | Attach existing accounts; per-company removal; last-Owner 409 (company row locked); all audited. |
| 2026-09-25 | P2.8 settings and flags | 0227a9d | Registry of all SRS 18.2 keys + 3 additions; allow-lists by identifier, shown by current name; AC-59. |
| 2026-09-25 | P2.10 middleware | 4514eb0 | CORS, 100/1000 rate limits, trusted-proxy IP and scheme, HTTPS in prod, request IDs, headers; `HTTPS_REQUIRED` code; `docs/security-review.md`. |
| 2026-09-25 | P2.1 create-owner CLI | 5b4f1cb | Manual smoke test on the dev DB: owner login, company, Accountant PUT settings → 403, Owner → 200. |
| 2026-09-25 | Env | — | The repo moved to `~/Desktop/tally-platform`; `.venv` scripts still pointed at the old path, so `uv sync --all-packages --reinstall` was needed once. |
| 2026-09-23 | P1.1 model conventions, types, enums | 631d0e7 | Money/Quantity/Rate NUMERIC, timestamptz, StrEnum CHECKs, tenant composite-FK helper; metadata convention tests. |
| 2026-09-23 | P1.2 companies, users, roles | 92e7776 | Single migration 0001 started; roles seeded. Rollback-per-test `session` fixture (cannot test commits; SYNC-6.1/6.2, TEST-3.3 need a committing fixture). |
| 2026-09-23 | P1.3 agents, commands, schedules | 0eccccc | RTE-1.4 trigger: agent_id/company_id immutable. |
| 2026-09-23 | P1.4 masters (D-001 columns) | a0c4db0 | Anchor columns, partial unique reserved_name, no-DELETE trigger (DR-ML-1). |
| 2026-09-23 | P1.5 opening balances, snapshots | 6a09f02 | opening_bill_allocations per D-022. |
| 2026-09-23 | P1.6 vouchers and children | 3ab7b56 | Normalized-amount CHECKs, cascading children for 6.9, identity tests on all 6 synced tables. |
| 2026-09-23 | P1.7 sync control | 892714b | Watermarks/lease, runs, errors, batches (D-024), reconciliation results. |
| 2026-09-23 | P1.8 settings, audit, anomaly | 10154d0 | Allow-list defaults in `app/models/defaults.py` (D-031 #13); rename-survival test; audit append-only for every role. |
| 2026-09-23 | P1.9 migration round-trip | 7cdae52 | Upgrade == models (no autogenerate diff), downgrade leaves nothing. Review fixed INTEGER→BIGINT FKs; convention tests for FK types and redundant indexes. |
| 2026-09-23 | P1.10 factories | bb033b3 | `backend/tests/factories.py`. |
| 2026-09-23 | Req-tag audit | (see log) | `req` now means the test fully proves the requirement; new `req_partial` marker, listed separately in traceability and phase reports. Every tag re-checked against the SRS: fully covered RTE-1.4, DR-ML-1, DR-4.6; 10 partial; removed TEST-1.3, ACC-DATA-1, DR-VE-3/4, SEC-1.7 (and DR-ML-1 on vouchers); AC-12 moved to the FAILED-gate test as partial. Phase 00/01 reports carry a correction note. |
| 2026-09-23 | P1 docs | (see log) | `docs/schema.md` (Mermaid ER + invariants); D-031 and D-032 ACCEPTED. |
| 2026-09-23 | Setup: repo, plan, SRS v7.3 PDF, .gitignore | 9b83697 | No application code. SRS PDF verified as "v7.3 Complete Edition", 34 pages. |
| 2026-09-23 | Setup: origin added, answers and toolchain recorded | e769a15 | Pushed `main` to origin. |
| 2026-09-23 | P0.1 workspace and directory tree | ba0987a | uv workspace: shared, backend, agent, tools. |
| 2026-09-23 | P0.5 quality tooling | (see log) | ruff (T20: no print), mypy strict on tally_contract + app.core, 3 import-linter contracts. |
| 2026-09-23 | P0.12 logging and test-run infrastructure | 30db670 | structlog via stdlib logging, `assert_logged`, req-ID JUnit properties, skips must give a reason. |
| 2026-09-23 | P0.3 error codes and contract version | (see log) | 15 SRS + 14 additions (D-030). |
| 2026-09-23 | P0.6 docker environment | (see log) | postgres 16 + backend; `tally_owner` (DDL) / `tally_app` (DML only). |
| 2026-09-23 | P0.2 backend skeleton | (see log) | config, db, AppError handlers, /health, /health/db, alembic skeleton. |
| 2026-09-23 | P0.10 gate plumbing | (see log) | gate_status.yaml G1-G33 NOT_TESTED; `collection_sync_mode` per VAL-1.1/1.2. |
| 2026-09-23 | P0.4 Agent CLI stubs | (see log) | register, run, status, set-credential, test-tally. |
| 2026-09-23 | P0.11 SRS transcription | b926e89 | `docs/srs/SRS_v7_3.md`, proven word-for-word against the PDF. |
| 2026-09-23 | P0.9 traceability | (see log) | 356 requirement IDs found; 6 covered so far. |
| 2026-09-23 | P0.7/P0.8 Makefile and CI | (see log) | GitHub Actions: `check` (ubuntu + postgres 16) and `agent-windows` (may fail until P7). |
| 2026-09-23 | P0 CI fixes | 2f0c340 | First CI run failed in both jobs. (1) Windows: `read_text()` defaults to cp1252 -> UnicodeDecodeError; every text I/O call now names `encoding="utf-8"`, guarded by `tools/tests/test_text_io_encoding.py`. (2) Linux: the SRS tests re-ran `pdftotext` and demanded byte-equality, so Ubuntu's older poppler failed them; `docs/srs/SRS_v7_3.raw.txt` is now the committed reference extraction. Markdown unchanged; no test skipped or weakened. CI run 35881605525 green. |

## In progress
-

## Blocked
| Item | Blocked by (gate / decision / question) | Since |
|---|---|---|
| _(none)_ | D-002 is still needed before P4, D-021 before P8. | |

## Questions for the product owner
| # | Question | Raised in | Answer |
|---|---|---|---|
| 1 | Install poppler and use `pdftotext -layout` for the P0.11 SRS transcription? | Setup | Yes. poppler 26.09.0 installed via brew (2026-09-23). |
| 2 | GitHub remote for CI (P0.8)? | Setup | `origin` = https://github.com/sushruthpippiri-cell/Tally (private). |
| 3 | Repo location? | Setup | Moved to `/Users/sushruthp/code/tally-platform` (2026-09-23). |
| 4 | Git author correct? | Setup | Yes: `sushruthpippiri-cell <sushruth.pippiri@gmail.com>`. |
| 5 | D-001 (before P1), D-002 (before P4), D-021 (before P8)? | Setup | Noted. Owner will confirm D-001 before P1 and D-002 before P4, and answer D-021 before P8. Do not start those phases until confirmed. |
| 6 | Confirm D-001 (classification anchor). | P0 end | **ACCEPTED 2026-09-23.** Anchor = nearest predefined group, else the chain's own top-level group; only a broken chain is UNRESOLVED_GROUP. Allow-list entries are stored by reserved name (predefined) or GUID (company groups), never by display name, and shown by current name. P1 is unblocked. |
| 7 | Accept the P1 plan's new schema choices (D-031) and the allow-list seeding approach? | P1 plan | **ACCEPTED 2026-09-23**, with the note that the rollback-per-test fixture must say it cannot test commit behaviour. D-032 (smaller choices made during implementation) **ACCEPTED 2026-09-23** — none changes a business rule or drops an SRS requirement. |

## Owner rules added at P0 start (2026-09-23)
Testing and logs rules (logs captured at DEBUG and saved per run, log-record assertions, per-phase full-suite report in `docs/test-reports/phase-NN.md`, no next phase on a red suite) are in `CLAUDE.md` -> "Testing and logs" and in `docs/plan/phase-00-foundation.md` (P0.12).

## Test reports
| Phase | Report | Result |
|---|---|---|
| 03 | [phase-03.md](test-reports/phase-03.md) | PASS - 613 tests, 0 failed, 0 skipped, 89.3% coverage; CI pending |
| 02 | [phase-02.md](test-reports/phase-02.md) | PASS - 416 tests, 0 failed, 1 skipped (no Agent routes until P3), 90.2% coverage; CI run 36103266538 green |
| 01 | [phase-01.md](test-reports/phase-01.md) | PASS - 183 tests, 0 failed, 0 skipped, 91.4% coverage; CI run 35887137380 green |
| 00 | [phase-00.md](test-reports/phase-00.md) | PASS - 78 tests, 0 failed, 0 skipped, 83% coverage; CI run 35881605525 green |

## Environment (recorded 2026-09-23, macOS arm64)
| Tool | Version |
|---|---|
| uv | 0.12.17 |
| Python | 3.12.14 (`python3.12`, /opt/homebrew/bin) |
| Node | v24.13.0 (npm 11.6.2) |
| Docker | 29.8.0 (Compose v5.5.1). Daemon running (verified 2026-09-23). |
| poppler / pdftotext | 26.09.0 |
| make | /usr/bin/make |

Notes for P0.11: the Read tool cannot render PDFs without poppler (now installed); transcribe with `pdftotext -layout docs/srs/Tally_SRS_v7_3_Complete.pdf`. Plain `pypdf` output flattens tables, so do not use it for the transcription.

## Gate status summary
All gates NOT TESTED (see docs/validation-gate.md).
