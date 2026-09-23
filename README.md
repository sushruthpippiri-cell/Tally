# Tally Integration & Business Analytics Platform

Read-only analytics beside TallyPrime: a Windows Sync Agent extracts data over Tally's XML/HTTP
interface using this project's TDL, uploads it over outbound HTTPS to a FastAPI/PostgreSQL backend,
and a React dashboard shows deterministic analytics with an independent reconciliation.

- **Requirements:** `docs/srs/SRS_v7_3.md` (searchable copy of the PDF beside it)
- **Work plan:** `docs/plan/00-OVERVIEW.md`, one file per phase
- **Rules for contributors and agents:** `CLAUDE.md`
- **Progress and decisions:** `docs/progress.md`, `docs/decisions.md`

## Getting started

```bash
brew install poppler          # SRS transcription tests
uv sync --all-packages
make up                       # Postgres 16 + backend on :8000
curl localhost:8000/health
make check                    # lint + types + import contracts + tests
```

`make up` creates two databases: `tally` (dev) and `tally_test` (tests). Two roles: `tally_owner`
(DDL, Alembic only) and `tally_app` (DML only, SEC-1.15).

## Common commands

| Command | Does |
|---|---|
| `make up` / `make down` | Start / stop Postgres + backend |
| `make migrate` | `alembic upgrade head` as the owner role |
| `make test PHASE=pNN` | Full suite; log + JUnit XML in `logs/test-runs/` |
| `make check` | lint, typecheck, import-linter, tests |
| `make phase-report PHASE=NN` | Fresh `_test` DB, full suite, `make check`, writes `docs/test-reports/phase-NN.md` |
| `make traceability` | Regenerate `docs/traceability.md` |

## Windows developers

Use WSL for `make`, or run the underlying commands directly (`uv run pytest`, `uv run ruff check .`,
`uv run mypy`). The Agent's own Windows service work lands in Phase 7.
