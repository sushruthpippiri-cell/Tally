# Developer entry points. Windows: use WSL, or run the `uv run ...` commands directly.
COMPOSE := docker compose -f deploy/docker-compose.yml
PHASE ?= dev
TEST_DB_URL ?= postgresql+psycopg://tally_owner:tally_owner_dev@localhost:5432/tally_test

.PHONY: up down migrate test test-backend test-agent lint format typecheck importlint check \
        traceability phase-report

up:  ## Start Postgres + backend
	$(COMPOSE) up -d --build

down:
	$(COMPOSE) down

migrate:  ## alembic upgrade head using the owner role
	cd backend && DATABASE_MIGRATION_URL=$(TEST_DB_URL) uv run alembic upgrade head

test:  ## Full suite; log + JUnit XML under logs/test-runs/ (CLAUDE.md "Testing and logs")
	@uv run python -m tally_tools.run_tests --phase $(PHASE)

test-backend:
	uv run pytest backend

test-agent:
	uv run pytest agent

lint:
	uv run ruff check .
	uv run ruff format --check .

format:
	uv run ruff check --fix .
	uv run ruff format .

typecheck:
	uv run mypy

importlint:
	uv run lint-imports

check: lint typecheck importlint test  ## Run before calling any task done

traceability:
	uv run python -m tally_tools.traceability

phase-report:  ## Fresh DB + full suite + check, then docs/test-reports/phase-NN.md
	@test -n "$(PHASE)" || (echo "usage: make phase-report PHASE=00" && exit 1)
	uv run python -m tally_tools.phase_report --phase $(PHASE)
