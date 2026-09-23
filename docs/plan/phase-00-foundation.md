# Phase 0 — Foundation & guardrails

**Size:** S · **Depends on:** — · **SRS:** 2.3, 2.4, 17.6, 21, TEST-1.3
**Decisions:** D-005, D-010, D-029

## Goal
A monorepo where every later phase has an obvious home, CI that enforces lint, types, tests and the architecture rules in `CLAUDE.md`, and the documentation scaffolding later sessions rely on.

## Read first
`CLAUDE.md` · `docs/plan/00-OVERVIEW.md` · `docs/decisions.md` · SRS Sections 2.3, 2.4, 21

## Tasks

### P0.1 Workspace
- uv workspace at the repo root with members `shared` (import name `tally_contract`), `backend` (`app`), `agent` (`tally_agent`), `tools`.
- Python 3.12 everywhere. `shared` and `agent` must not depend on FastAPI, SQLAlchemy or other backend-only libraries (the Agent ships to Windows machines).
- Create the directory tree shown in `CLAUDE.md`, each top-level folder with a two-line README saying what belongs there.

### P0.2 Backend skeleton
- `app/main.py` app factory.
- `app/core/config.py` (pydantic-settings): `DATABASE_URL` (app role), `DATABASE_MIGRATION_URL` (owner role), `JWT_SECRET`, `JWT_ACCESS_TTL_MINUTES=30`, `JWT_REFRESH_TTL_HOURS=24`, `CORS_ORIGINS`, `ENV` (dev|test|prod), `MIN_AGENT_VERSION`, `MIN_TDL_VERSION`, `ALLOW_UNVERIFIED_INCREMENTAL` (true in dev/test, false in prod — D-029), `ANTHROPIC_API_KEY` (optional), `ANOMALY_EXPLAINER_MODEL` (optional). In prod, missing secrets fail startup (SEC-1.14).
- `app/core/db.py`: async SQLAlchemy engine (asyncpg), session dependency, `transaction()` helper.
- `app/core/errors.py`: `AppError(code, message, http_status, details=None)`; handlers return `{"code", "message", "details"}`. Pydantic validation → 422 `VALIDATION_ERROR`; authentication → 401; authorization → 403 (SRS 19.2).
- `GET /health` and `GET /health/db`.

### P0.3 Shared contract skeleton
- `tally_contract/errors.py`: `ErrorCode` StrEnum with every SRS code and the proposed ones (comment `# proposed` on the latter):
  - SRS: `TALLY_SERVER_DISABLED`, `TDL_NOT_LOADED`, `COMPANY_NOT_LOADED`, `COMPANY_MISMATCH`, `TALLY_EXPORT_TIMEOUT`, `QUEUE_FULL`, `SYNC_LOCKED`, `STALE_ALTERID`, `CREDENTIAL_INVALID`, `AGENT_REVOKED`, `UDF_NOT_FOUND`, `UNRESOLVED_GROUP`, `UNSUPPORTED_ALLOCATION_TYPE`, `UNLINKED_CREDIT_NOTE`, `UNLINKED_DEBIT_NOTE`.
  - Proposed: `TALLY_UNREACHABLE`, `DEBIT_CREDIT_IMBALANCE`, `UNKNOWN_MASTER_REFERENCE`, `PARSE_ERROR`, `AGENT_SELECTION_REQUIRED`, `AGENT_INCOMPATIBLE`, `INVALID_COMMAND_STATE`, `KEY_LIST_SUSPICIOUS`, `GATE_NOT_PASSED`, `VALIDATION_ERROR`, `NOT_AUTHENTICATED`, `FORBIDDEN`, `NOT_FOUND`, `CONFLICT`.
- `tally_contract/version.py`: `CONTRACT_VERSION = "1.0"`.

### P0.4 Agent skeleton
`tally_agent/__main__.py` with a typer CLI exposing stubs `register`, `run`, `status`, `set-credential`, `test-tally`.

### P0.5 Quality tooling
- ruff (lint + format), mypy (strict for `shared` and `backend/app/core`), pytest, pytest-asyncio, coverage, time-machine (clock control), hypothesis (property tests).
- import-linter contracts:
  1. `app.analytics`, `app.reconciliation`, `app.sync`, `app.exports` may not import `app.anomaly`, `anthropic` or `mcp` (SRS 2.4-1, NFR-REL-1).
  2. `tally_contract` may not import `app` or `tally_agent`.
  3. `tally_agent` may not import `app`.

### P0.6 Local environment
- `deploy/docker-compose.yml`: `postgres:16` and `backend`. A Postgres init script creates `tally_owner` (owns the schema; used only by Alembic) and `tally_app` (SELECT/INSERT/UPDATE/DELETE only, no DDL) with default privileges for future tables (SEC-1.15).
- `backend/Dockerfile` (multi-stage, non-root). `.env.example` documenting every variable.

### P0.7 Makefile
Targets: `up`, `down`, `migrate`, `test`, `test-backend`, `test-agent`, `lint`, `format`, `typecheck`, `importlint`, `check` (= lint + typecheck + importlint + test), `traceability`. README notes for Windows developers (WSL, or the equivalent `uv run` commands).

### P0.8 CI
GitHub Actions: a `check` job on ubuntu with a Postgres 16 service container; an `agent-windows` job on `windows-latest` running agent unit tests (allowed to fail until P7). Cache uv.

### P0.9 Requirement tagging and traceability
- Register pytest marker `req`: `@pytest.mark.req("ACC-1.1", "AC-26")`.
- `tools/traceability.py`: extracts requirement IDs from `docs/srs/SRS_v7_3.md` (regex over the SRS prefixes: FR, AGT, RTE, VER, SYNC, VAL, DR, ACC, REC, AGE, FR-AGE, FR-PAY, FR-STK, FR-DD, EXP, RBAC, SEC, LOG, PERF, NFR, TZ, Q, BKP, TEST, TOPN, AC), scans tests for `req` markers, writes `docs/traceability.md` (ID → tests) and lists IDs with no test. Non-blocking in CI until P16.

### P0.10 Gate status plumbing
- `backend/app/config/gate_status.yaml`: G1–G33 = `NOT_TESTED`, mirroring `docs/validation-gate.md`.
- `app/core/gates.py`: `gate_status(id)`, `gate_passed(id) -> bool`, `collection_sync_mode(collection_type) -> "INCREMENTAL" | "FULL_ONLY"`, using this mapping:
  - LEDGER → G1, G5, G6, G7, G10 · STOCK_ITEM → G2, G5, G6, G7, G10 · VOUCHER → G3, G5, G6, G7, G8 · COST_CENTRE → G4, G5, G6, G7, G10 · GROUP / VOUCHER_TYPE / COMPANY → G5, G6, G7, G10
  - any FAILED → FULL_ONLY (VAL-1.2); all PASSED → INCREMENTAL; otherwise INCREMENTAL only if `ALLOW_UNVERIFIED_INCREMENTAL`.
- Unit tests for all three branches.

### P0.12 Logging and test-run infrastructure (rules in `CLAUDE.md` → "Testing and logs")
- `tally_contract/log.py`: `get_logger(name)` (structlog on top of stdlib `logging`, so pytest `caplog` sees every record; JSON renderer in prod, console renderer in dev/test). Shared by backend, agent and contract code. `configure_logging(env)` called from `app/main.py` and the Agent CLI. Each record carries `event`, plus bound `request_id`, `company_id`, `agent_id` when known (SRS 15).
- ruff rule `T20` (no `print`) enabled for every package including tests.
- pytest config: `log_level = DEBUG`, `log_format` with logger name, `-ra`, strict markers; a `conftest.py` hook records each test's `req` marker IDs as JUnit properties (used by the phase report and P0.9), and fails any `skip` that has no reason.
- `tally_contract/testing.py`: `assert_logged(caplog, event, *, level=None, **fields)` and `assert_not_logged(...)`; unit-tested here so later phases can rely on it.
- `make test PHASE=pNN` runs pytest with `--junitxml` and tees output to `logs/test-runs/<phase>-<UTC timestamp>.log|.xml`; `logs/` added to `.gitignore`. Default `PHASE=dev`.
- `tools/phase_report.py` + `make phase-report PHASE=NN`: drop and recreate the test database, `alembic upgrade head` (empty skeleton in P0; real migration from P1), run the full suite via `make test`, run `make check`, then write `docs/test-reports/phase-NN.md` (tests run/passed/failed/skipped, each skip's reason, coverage from `coverage xml`, AC IDs covered from the JUnit properties, the log file name). Exits non-zero when anything failed, so a phase cannot be reported done on a red suite. Unit-tested against a small fake JUnit file.
- Playwright settings (trace and screenshot on failure) are recorded now and applied when P13.1 scaffolds the frontend.

### P0.11 Documentation
- Confirm `docs/progress.md`, `docs/decisions.md`, `docs/validation-gate.md` exist.
- Create `docs/srs/SRS_v7_3.md`: a faithful text copy of `docs/srs/Tally_SRS_v7_3_Complete.pdf` with section headings and requirement tables preserved (read the PDF and transcribe; do not summarize or reword requirement text). This file is what later sessions grep.

## Tests
- `/health`, `/health/db` return 200; error handler shape for 401/403/422.
- `gates.py` branches.
- `tools/traceability.py` against a tiny sample SRS and sample tests.
- Logging: `assert_logged` passes on a matching record and fails on a missing one; `get_logger` output reaches `caplog`; a `print()` in a sample file fails ruff.
- `tools/phase_report.py` against a fake JUnit file: counts, skip reasons, missing-reason failure, non-zero exit on failure.

## Definition of done
- `make test PHASE=p00` writes `logs/test-runs/p00-<timestamp>.log` and `.xml`; `logs/` is not tracked by git.
- `make phase-report PHASE=00` runs on a freshly migrated database, is green, and writes `docs/test-reports/phase-00.md`, linked from `docs/progress.md` and committed.
- `make up` starts Postgres and the backend; `/health` and `/health/db` return 200.
- `make check` passes locally and in CI.
- Adding `import anthropic` inside `app/analytics` makes import-linter fail (try it, then revert).
- `make traceability` writes `docs/traceability.md`.
- `docs/srs/SRS_v7_3.md` exists and `grep -n "SYNC-3.2" docs/srs/SRS_v7_3.md` finds the requirement.

## Out of scope
Any table, business endpoint or UI beyond health checks.

## Kickoff prompt
~~~text
Read CLAUDE.md and docs/plan/phase-00-foundation.md. In plan mode, propose the repository scaffold for P0.1–P0.11: files, tool versions, CI jobs, and how you will transcribe the SRS PDF into docs/srs/SRS_v7_3.md. After I approve, implement task by task, run `make check` after each, commit per task ("P0.x: …"), and finish by updating docs/progress.md.
~~~
