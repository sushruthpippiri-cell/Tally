# CLAUDE.md

Project memory for Claude Code. Read this whole file at the start of every session. Keep it short; detail lives in `docs/`.

## The project in one paragraph
A read-only analytics platform that sits beside TallyPrime. A Windows **Tally Sync Agent** extracts data from TallyPrime using the project's own TDL Collections/Reports over Tally's XML/HTTP interface (default `localhost:9000`) and uploads normalized records over **outbound HTTPS only** to a **FastAPI** backend on **PostgreSQL**. A **React** dashboard shows deterministic analytics with drill-down and CSV/PDF export, plus an independent **reconciliation** against Tally totals. An optional, feature-flagged anomaly module may use Claude via MCP **only to explain evidence the application has already computed**.

## Where things are
| What | Where |
|---|---|
| Requirements (source of truth) | `docs/srs/Tally_SRS_v7_3_Complete.pdf`; searchable copy `docs/srs/SRS_v7_3.md` (grep by ID, e.g. `grep -n "SYNC-3" docs/srs/SRS_v7_3.md`) |
| Work plan | `docs/plan/00-OVERVIEW.md`, one file per phase, `docs/plan/gate-track.md` |
| Decisions and spec clarifications | `docs/decisions.md` (ACCEPTED = binding; PROPOSED = use the stated default until changed) |
| Live-Tally validation status | `docs/validation-gate.md` (evidence) and `backend/app/config/gate_status.yaml` (read by code) |
| Progress log | `docs/progress.md` |

## Repository layout
```
.
├── CLAUDE.md
├── Makefile
├── pyproject.toml               # uv workspace root
├── shared/tally_contract/       # Agent<->backend contract: record schemas, XML request builder, parser, normalization, error codes
├── backend/
│   ├── app/
│   │   ├── main.py
│   │   ├── core/                # config, db, errors, security, permissions, periods, audit, gates, settings_registry
│   │   ├── models/              # SQLAlchemy models + enums
│   │   ├── schemas/             # Pydantic API schemas
│   │   ├── api/                 # thin routers
│   │   ├── services/            # companies, users, agents, commands, schedules, data_quality
│   │   ├── sync/                # ingest, upserts, vouchers, watermarks, leases, lifecycle, hierarchy
│   │   ├── analytics/           # filters, classification, metrics/*, aging, stock, ranking
│   │   ├── reconciliation/
│   │   ├── exports/
│   │   ├── anomaly/             # the ONLY package allowed to touch MCP / Claude
│   │   ├── jobs/                # APScheduler jobs
│   │   └── config/gate_status.yaml
│   ├── alembic/
│   └── tests/
├── agent/tally_agent/           # Windows Sync Agent
├── tdl/                         # TDL sources (version-controlled)
├── fixtures/xml/synthetic/      # hand-built XML fixtures (NOT verified Tally output)
├── fixtures/xml/live/           # XML captured from real TallyPrime (gate track)
├── tools/                       # tally_probe, dataset_gen, traceability, benchmarks
├── frontend/                    # React + TypeScript + Tailwind + Recharts
├── deploy/                      # docker-compose, Dockerfiles, reverse proxy, backup
└── docs/
```

## Commands
| Command | Does |
|---|---|
| `make up` / `make down` | Start / stop Postgres + backend (docker compose) |
| `make migrate` | `alembic upgrade head` using the owner role |
| `make test PHASE=pNN` | All Python tests (backend, shared, agent) against real Postgres; saves log + JUnit XML under `logs/test-runs/` |
| `make phase-report PHASE=NN` | Fresh DB + migrate + full suite + `make check`, then writes `docs/test-reports/phase-NN.md` |
| `make check` | lint + typecheck + import-linter + tests. Run before calling any task done |
| `make traceability` | Regenerate `docs/traceability.md` from `@pytest.mark.req` tags |
| `cd frontend && npm run dev / test / e2e / gen:api` | Frontend dev server, unit tests, Playwright, regenerate API types |

## Non-negotiable rules (breaking one is a bug, not a style issue)
1. **No AI/ML/LLM in analytics.** `app.analytics`, `app.reconciliation`, `app.sync`, `app.exports` never import `app.anomaly`, `anthropic` or `mcp` (import-linter enforces). Every figure is a deterministic SQL query.
2. **Analytics read normalized fields only**: `accounting_direction`, `amount_absolute`, `amount_signed`. `amount_raw` is written by the parser and read only by audit/debug views (ACC-DATA-1).
3. **Tenant isolation**: every company-scoped query uses the `company_id` from the `CompanyContext` / `AgentContext` dependency, never from a request body or query string. Repository functions take `company_id` as a required argument (SEC-1.7).
4. **Identity is `(company_id, tally_guid)`.** `voucher_number` is display-only (DR-4.x).
5. **No hard deletes** of synced masters or vouchers; lifecycle is a status change. Sole exception: replacing a modified voucher's child rows inside one transaction (SRS 6.9).
6. **Stale-record protection on every upsert**: incoming ALTERID lower → reject and log `STALE_ALTERID`; equal → no-op; higher → apply (SYNC-3.x).
7. **Classification** uses the ledger's resolved predefined group (see D-001) and the voucher type's `base_voucher_type`. Never names, never the immediate parent.
8. **Standard analytics include ACTIVE vouchers only** (CANCELLED and MISSING_IN_TALLY excluded unless explicitly requested).
9. **One query per metric**: dashboard, drill-down and export call the same function in `app/analytics/metrics/` (ACC-4.4, FR-DD-5, EXP-1.3).
10. **Money is Decimal**: `NUMERIC` in Postgres, `decimal.Decimal` in Python, strings in JSON. Never `float`. Aggregate money in SQL, not pandas.
11. **Dates**: `voucher_date` is a `DATE`. "Today", period boundaries, schedules and displayed timestamps use `company_timezone` via `app/core/periods.py`. Timestamps are stored as `timestamptz` (UTC).
12. **The backend never connects to an Agent**; the Agent never falls back to Tally's default reports (`TDL_NOT_LOADED`).
13. **`audit_logs` is append-only**, written only through `app/core/audit.py`.
14. **Every request body is a Pydantic model; every error is `AppError(code, message, status)`** with codes from `tally_contract.errors.ErrorCode`.
15. **Never guess Tally behaviour.** Anything the SRS marks LIVE TALLY VERIFICATION REQUIRED lives in one isolated constant/module tagged `# GATE-Gxx`, has a safe default, and switches behaviour via `app/core/gates.py`. If a task needs a Tally fact that is not in `fixtures/xml/live/` or `docs/validation-gate.md`, stop and ask.

## Coding conventions
- Python 3.12, full type hints, ruff + mypy clean. SQLAlchemy 2.0 typed ORM with async engine (asyncpg); Alembic migrations are hand-reviewed and never edited once applied.
- Routers stay thin; logic lives in services; SQL for metrics lives in `app/analytics/metrics/`.
- Tests run against real PostgreSQL (docker), never SQLite, for anything that touches SQL. Use `backend/tests/factories.py`.
- Tag each test with the requirement/acceptance IDs it proves: `@pytest.mark.req("SYNC-3.2", "AC-06")`.
- Frontend: TypeScript strict; API types generated from OpenAPI (`npm run gen:api`), never hand-written.

## Testing and logs (apply to every phase)
**Logs in tests**
- Use the app's structured logger (`tally_contract.log.get_logger`), never `print()` (ruff `T20` enforces it) in tests or app code.
- pytest runs with `log_level = DEBUG`; captured logs are shown for every failing test.
- Every test run saves its output to `logs/test-runs/<phase>-<timestamp>.log` plus a JUnit XML with the same stem. `logs/` is git-ignored. Run with `make test PHASE=p05`.
- Where a requirement says something is logged (`STALE_ALTERID`, `UDF_NOT_FOUND`, `TALLY_EXPORT_TIMEOUT`, malformed XML, ...), the test asserts on the log record with `assert_logged(caplog, event, level=..., **fields)`, not only on the return value.
- Frontend and end-to-end tests keep traces and screenshots on failure (Playwright `trace: 'retain-on-failure'`, `screenshot: 'only-on-failure'`, output under `logs/e2e/`).

**Test after every phase**
- At the end of each phase run the **full** suite (not only the new tests) plus `make check`, against a freshly migrated database: `make phase-report PHASE=NN`.
- That writes `docs/test-reports/phase-NN.md`: tests run / passed / failed / skipped; the reason for every skip (e.g. "waiting on GATE-G23"; a skip without a reason fails the report); coverage; acceptance-criteria IDs covered; the log file name.
- Anything failing is fixed before the phase is marked done. **Never start the next phase with a failing suite.**
- Link the report from `docs/progress.md` and commit it.

## Session workflow
1. Read this file, the phase file named in the prompt, `docs/decisions.md`, and the SRS sections the phase lists.
2. Plan first (plan mode): task IDs, files you will touch, schemas/SQL, tests, open questions. Wait for approval.
3. Implement one task at a time: tests first for the listed IDs, then code, then `make check`.
4. Commit per task: `P5.3: stale-record protection for master upserts`.
5. New assumption? Add a `D-0xx` entry (status PROPOSED) to `docs/decisions.md` and mention it in your summary.
6. Blocked on a Tally fact or a business decision? Stop, record it under Questions in `docs/progress.md`, and ask.
7. End of session: update `docs/progress.md`. Never leave work uncommitted; never start the next phase unasked.
