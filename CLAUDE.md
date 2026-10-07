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
| `make hooks` | Install the git pre-commit hook (once per clone, see below) |
| `make traceability` | Regenerate `docs/traceability.md` from `@pytest.mark.req` tags |
| `cd frontend && npm run dev / test / e2e / gen:api` | Frontend dev server, unit tests, Playwright, regenerate API types |

## Pre-commit hook
`.githooks/pre-commit` runs `ruff check`, `ruff format --check` and `mypy`; any failure blocks the commit. Git does not install hooks from a clone, so after a fresh clone run `make hooks` once (on Windows without make: `git config core.hooksPath .githooks`). Check with `git config core.hooksPath` (prints `.githooks`). Fix the failure rather than committing with `--no-verify`; CI runs `make check` regardless. The hook is fast and skips tests and import-linter, so still run `make check` before calling a task done.

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
- Tag each test with the requirement/acceptance IDs it proves: `@pytest.mark.req("SYNC-3.2", "AC-06")`. **`req` means the test fully proves that requirement as the SRS words it** (every clause, the real behaviour, not just the schema or a helper that enables it). A test that proves only part uses `@pytest.mark.req_partial(...)` with a one-line comment naming what is missing and where it will be proven (e.g. `# sync upserts: P5`). Partial coverage is listed separately in `docs/traceability.md` and the phase reports and never counts as covered. A test that proves none of a requirement (a prerequisite, a neighbouring rule) gets no tag for it. Check the SRS text before tagging: `grep -n "SYNC-3.2" docs/srs/SRS_v7_3.md`.
- Frontend: TypeScript strict; API types generated from OpenAPI (`npm run gen:api`), never hand-written.

## Testing and logs (apply to every phase)
**Logs in tests**
- Use the app's structured logger (`tally_contract.log.get_logger`), never `print()` (ruff `T20` enforces it) in tests or app code.
- pytest runs with `log_level = DEBUG`; captured logs are shown for every failing test.
- Every test run saves its output to `logs/test-runs/<phase>-<timestamp>.log` plus a JUnit XML with the same stem. `logs/` is git-ignored. Run with `make test PHASE=p05`.
- Where a requirement says something is logged (`STALE_ALTERID`, `UDF_NOT_FOUND`, `TALLY_EXPORT_TIMEOUT`, malformed XML, ...), the test asserts on the log record with `assert_logged(caplog, event, level=..., **fields)`, not only on the return value.
- Frontend and end-to-end tests keep traces and screenshots on failure (Playwright `trace: 'retain-on-failure'`, `screenshot: 'only-on-failure'`, output under `logs/e2e/`).

**Time and dates in tests**
- Tests never depend on the real date or time. The root `conftest.py` starts every test at `FIXED_NOW` (`tally_contract.testing`, ticking forward from there), so a test gets the same date on any day it runs.
- A test about a particular moment sets the clock explicitly: `with time_machine.travel(<instant>, tick=False):`, or pass `now` into the code under test. Never compute a test's dates from the real clock or compare against `date.today()`.
- Code takes "now" from the app clock (`datetime.now(UTC)`, or an injected `now`) and "today" from `app/core/periods.py` in `company_timezone`. Never SQL `now()` for anything compared with "now": every timestamp that is compared is written by the app (the `created_at()` column helper does this).
- "Days since today" logic (aging, payment behaviour, stock classification, schedules, expiries) is tested at fixed instants, including day, month, financial-year and time-zone boundaries.

**Test after every phase**
- At the end of each phase run the **full** suite (not only the new tests) plus `make check`, against a freshly migrated database: `make phase-report PHASE=NN`.
- That writes `docs/test-reports/phase-NN.md`: tests run / passed / failed / skipped; the reason for every skip (e.g. "waiting on GATE-G23"; a skip without a reason fails the report); coverage; acceptance-criteria IDs covered; the log file name.
- Anything failing is fixed before the phase is marked done. **Never start the next phase with a failing suite.**
- After the phase's final push, check CI: `gh run watch` (or `gh run list -L1`), and on failure `gh run view <id> --log-failed`. **A phase is done only once the CI run is green** — a green local suite is not enough, because CI runs on Linux and Windows with different tool versions. Fix the cause; never skip or weaken a test to get green.
- Link the report from `docs/progress.md` and commit it.

**Cross-platform**: the Agent ships to Windows, and CI runs `agent-windows`. Always pass `encoding="utf-8"` to `open()`, `read_text()` and `write_text()` (Windows defaults to cp1252), and write generated files with `newline="\n"`. `tools/tests/test_text_io_encoding.py` enforces this. Never assume a system tool's output is byte-identical across versions; pin the artifact instead (see `docs/srs/README.md`).

## Session workflow
1. Read this file, the phase file named in the prompt, `docs/decisions.md`, and the SRS sections the phase lists.
2. Plan first (plan mode): task IDs, files you will touch, schemas/SQL, tests, open questions. Wait for approval.
3. Implement one task at a time: tests first for the listed IDs, then code, then `make check`.
   **Gate every commit on `make check`'s exit status only: `make check && git commit ...`.** Never decide from its output (`make check | grep passed`, `; echo exit=$?` then commit): a pipeline or `;` lets a failing check through. Redirect the output to a log if it is long, but keep the `&&`.
4. Commit per task: `P5.3: stale-record protection for master upserts`.
5. New assumption? Add a `D-0xx` entry (status PROPOSED) to `docs/decisions.md` and mention it in your summary.
6. Blocked on a Tally fact or a business decision? Stop, record it under Questions in `docs/progress.md`, and ask.
7. End of session: update `docs/progress.md`. Never leave work uncommitted; never start the next phase unasked.

## Branches, PRs and merging (from P14 on)
Every phase goes through one branch and one pull request; nothing is committed straight to `main`.
- **Branch** `phase-NN` from an up-to-date `main` (or a worktree on it). All of the phase's sessions commit to it, one commit per task (step 4), each gated on `make check`.
- **Pull request**: push the branch and open a **draft** PR to `main` after the first session, titled `Phase NN: <name>`. CI (`check`, `frontend`; `agent-windows` and `capture-kit` when their paths change) runs on the PR. A failing run is fixed on the branch, never skipped.
- **Merge** only when the owner says so and the PR's latest CI run is green: mark it ready, merge with a **merge commit** (`gh pr merge N --merge --delete-branch`; never squash or rebase, so the per-task commits stay), then remove the worktree, pull `main`, and check that CI on `main` is green.
- **A PR that changes a manual-dispatch workflow, or anything that workflow builds, runs it once on the PR before it merges**, and the summary cites that run's ID. The push-triggered jobs never exercise it, so without this the change ships untested: P16.8's installer step was merged believing it worked, and the first real run found two defects — a PowerShell path that never reached the compiler, and an `.iss` that did not compile. `gh workflow run <file> --ref <branch>`; it is free on a public repository. This covers `agent-build.yml` and `capture-kit.yml`, and the Agent, TDL and packaging files they build.
- **The phase is done** (Testing and logs above) once the phase report is committed on the branch, the PR is merged, and CI on `main` is green. `docs/progress.md` records the PR number and the CI runs.
- **A phase that is blocked on something outside the repository** (hosting, hardware, a certificate, live-Tally captures, a third party) does not hold its finished work on a branch waiting. Merge what is done, keep the phase marked **not done**, and take the rest in **follow-up PRs** off `main`, one per task or group of tasks, branched `phase-NN-<what>` (e.g. `phase-16-dataset-gen`). Each follows the same rules: per-task commits gated on `make check`, a PR, CI green. `docs/progress.md` lists what remains and which PR closed each piece, and the phase is marked done only when the last of them is merged and the blocked items have come back. **Phase 16 is the first phase run this way** — PR #4 merged ten of its tasks on 2026-10-07 with P16.5 part done, P16.10 not started, and six items waiting on the owner.
