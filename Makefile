# Developer entry points. Windows: use WSL, or run the `uv run ...` commands directly.
COMPOSE := docker compose -f deploy/docker-compose.yml
PHASE ?= dev
TEST_DB_URL ?= postgresql+psycopg://tally_owner:tally_owner_dev@localhost:5432/tally_test

.PHONY: up down migrate test test-backend test-agent lint format typecheck importlint check dev-tls dev-https \
        traceability phase-report hooks capture-kit update-fixtures dataset bench-data bench-analytics \
        loadtest demo-data

hooks:  ## Install the git pre-commit hook (ruff + mypy); once per clone
	git config core.hooksPath .githooks

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
	uv run python -m tally_tools.traceability --check
	@git diff --quiet docs/traceability.md || { \
	  echo 'docs/traceability.md is stale - commit the regenerated file'; \
	  git --no-pager diff --stat docs/traceability.md; exit 1; }

phase-report:  ## Fresh DB + full suite + check, then docs/test-reports/phase-NN.md
	@test -n "$(PHASE)" || (echo "usage: make phase-report PHASE=00" && exit 1)
	uv run python -m tally_tools.phase_report --phase $(PHASE)

dev-tls:  ## A throwaway CA + certificate for HOST (this Mac's LAN address), in dev-https/
	uv run python -m tally_tools.dev_backend tls --host $(HOST)

dev-https:  ## The dev backend over HTTPS on :8443 for a Windows Agent (docs/agent-windows-checklist.md)
	cd backend && ENV=dev \
	DATABASE_URL=postgresql+asyncpg://tally_app:tally_app_dev@localhost:5432/tally \
	DATABASE_MIGRATION_URL=postgresql+psycopg://tally_owner:tally_owner_dev@localhost:5432/tally \
	JWT_SECRET=dev-only-jwt-secret-change-me-in-prod \
	uv run uvicorn app.main:create_app --factory --host 0.0.0.0 --port 8443 \
	  --ssl-keyfile ../dev-https/server-key.pem --ssl-certfile ../dev-https/server.pem

capture-kit:  ## Build the PowerShell capture kit into dist/tally-capture-kit/ (+ .zip), D-038
	uv run python -m tally_tools.capture_kit build --out dist

update-fixtures:  ## Show fixture expectations that would change; FORCE=1 rewrites them (review the diff)
	uv run python -m tally_tools.fixtures update $(if $(FORCE),--force,)

demo-data:  ## Migrate the dev database and load a small, realistic demo company (D-053 #8)
	uv run python -m tally_tools.demo_data

dataset:  ## Write the SRS 17.2 dataset as Tally XML into dataset/ (for mock Tally); VOUCHERS=n
	uv run python -m tally_tools.dataset_gen --out dataset $(if $(VOUCHERS),--vouchers $(VOUCHERS))

bench-data:  ## Recreate tally_bench (never dev/test) with the seeded SRS 17.2 dataset
	uv run python -m tally_tools.benchmark

loadtest:  ## PERF-1.1 under concurrency: USERS (default 10), HOST, LOAD_EMAIL, LOAD_PASSWORD
	uv run --group dev locust -f tools/tally_tools/loadtest/locustfile.py --headless \
	  --users $(or $(USERS),10) --spawn-rate $(or $(USERS),10) --run-time $(or $(RUNTIME),2m) \
	  --host $(or $(HOST),http://localhost:8000) \
	  --html logs/loadtest.html --csv logs/loadtest

bench-analytics:  ## Time every metric on tally_bench; writes docs/benchmarks/p8-analytics.md
	uv run python -m tally_tools.bench_analytics
